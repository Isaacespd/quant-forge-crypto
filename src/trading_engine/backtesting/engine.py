from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from trading_engine.alpha.indicators import MIN_CANDLES_FOR_INDICATORS, candles_to_frame, compute_atr
from trading_engine.alpha.strategy import AlphaEngine
from trading_engine.backtesting.broker_sim import BacktestTrade, OpenBacktestPosition, SimulatedBroker
from trading_engine.backtesting.metrics import compute_metrics
from trading_engine.models.candle import Candle
from trading_engine.risk.engine import RiskEngine


@dataclass
class BacktestResult:
    trades: list[BacktestTrade]
    equity_curve: list[tuple]
    final_equity: float
    metrics: dict
    open_position: OpenBacktestPosition | None = None


class BacktestEngine:
    """Orquesta Alpha Engine -> Risk Engine -> fill simulado, vela a vela (docs/SDD.md §3.B):
    el mismo código de decisión que correría en producción, nunca una reimplementación.

    Simplificaciones deliberadas de este MVP (ver `specs/002-motor-backtesting/plan.md`):
    - Un solo símbolo por corrida, una sola posición abierta a la vez (sin pirámides).
    - Mientras hay una posición abierta, no se evalúan nuevas señales de entrada —
      solo se vigila el stop-loss (con trailing: se mueve a favor de la posición,
      nunca en contra, a la misma distancia en ATR con la que se abrió).
    - El fill de entrada ocurre en el `open` de la vela SIGUIENTE a la que generó la
      señal, nunca en el `close` de esa misma vela (evita look-ahead bias: no se
      puede ejecutar a un precio que apenas se está usando para decidir).
    - Curva de equity basada en operaciones cerradas (realizado), no mark-to-market
      vela a vela — el drawdown intra-operación no queda reflejado.
    - El circuit breaker de drawdown acumulado de Risk Engine bloquea "hasta revisión
      manual" (docs/SDD.md §5.3) — sin un humano, `drawdown_cooldown_days` simula esa
      revisión: tras ese período bloqueado, se resetea el pico de referencia y se
      reanuda. Sin esto, el breaker nunca se libera solo una vez cruzado el umbral
      (bug real encontrado corriendo 8.6 años de historia, ver plan.md).

    `exit_on_opposite_signal` y `allow_short` son opt-in (default apagado/prendido
    como antes) para no alterar el comportamiento ya validado de la estrategia
    tendencial/reversión — sirven para `SimpleTrendAlphaEngine`, que necesita poder
    salir de una posición cuando la tendencia se revierte, no solo por stop-loss.

    `warmup_candles` y `alpha_lookback_window` son configurables por instancia (en vez
    de una sola constante de clase) porque el warm-up y la ventana correctos dependen
    de qué `alpha_engine` se conecte, no del motor en sí: `AlphaEngine` (EMA cross/MACD +
    RSI/Bollinger, filtro ADX) necesita `MIN_CANDLES_FOR_INDICATORS`; `SimpleTrendAlphaEngine`
    (solo EMA-200 + ATR) solo necesita `MIN_CANDLES_FOR_TREND_ONLY`. Los defaults preservan
    el comportamiento anterior (214 / 1200) para no alterar resultados ya validados.
    """

    # EMA(200) —el filtro de tendencia macro— converge (<0.1% de su valor asintótico) en
    # ~5-6x su período, es decir ~1000-1200 velas; 1200 deja margen cómodo también para
    # EMA(50)/ADX/RSI/Bollinger/MACD, todos de período más corto. Sin este límite,
    # AlphaEngine.evaluate recalcularía indicadores sobre TODO el histórico acumulado en
    # cada vela -> O(n²) en el largo del backtest, inviable con miles de velas (descubierto
    # al correr 2 años de datos reales, ver specs/002-motor-backtesting/tasks.md).
    ALPHA_LOOKBACK_WINDOW = 1200

    def __init__(
        self,
        alpha_engine: AlphaEngine,
        risk_engine: RiskEngine,
        initial_equity: float = 100_000.0,
        commission_pct: float = 0.001,
        slippage_pct: float = 0.0005,
        drawdown_cooldown_days: int = 30,
        exit_on_opposite_signal: bool = False,
        allow_short: bool = True,
        warmup_candles: int | None = None,
        alpha_lookback_window: int | None = None,
    ):
        self.alpha_engine = alpha_engine
        self.risk_engine = risk_engine
        self.initial_equity = initial_equity
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.drawdown_cooldown_days = drawdown_cooldown_days
        self.exit_on_opposite_signal = exit_on_opposite_signal
        self.allow_short = allow_short
        self.warmup_candles = MIN_CANDLES_FOR_INDICATORS if warmup_candles is None else warmup_candles
        self.alpha_lookback_window = (
            self.ALPHA_LOOKBACK_WINDOW if alpha_lookback_window is None else alpha_lookback_window
        )

    def run(self, candles: list[Candle]) -> BacktestResult:
        broker = SimulatedBroker(self.initial_equity, self.commission_pct, self.slippage_pct)

        if len(candles) <= self.warmup_candles + 1:
            return self._build_result(broker, [self.initial_equity])

        atr_series = compute_atr(candles_to_frame(candles))
        cooldown = timedelta(days=self.drawdown_cooldown_days)
        cumulative_breach_since = None
        intrabar_equity = [self.initial_equity]

        for i in range(self.warmup_candles, len(candles) - 1):
            candle = candles[i]
            broker.mark_period(candle.timestamp)

            if not broker.is_flat():
                # Snapshot ANTES de cerrar/mover el stop: la posición estuvo abierta
                # *durante* esta vela, así que su low/high son la excursión adversa
                # real que sufrió mientras estuvo abierta (requisito de MDD preciso,
                # ver docstring de SimulatedBroker.mark_to_market_equity).
                intrabar_equity.append(broker.mark_to_market_equity(candle.low, candle.high))
                if broker.stop_loss_hit(candle.high, candle.low):
                    broker.close_position(broker.position.stop_loss, candle.timestamp)
                else:
                    broker.update_trailing_stop(candle.high, candle.low)
                    if self.exit_on_opposite_signal:
                        history = candles[max(0, i + 1 - self.alpha_lookback_window) : i + 1]
                        signal = self.alpha_engine.evaluate(history)
                        if signal.direction != "HOLD" and signal.direction != broker.position.direction:
                            fill_candle = candles[i + 1]
                            broker.close_position(fill_candle.open, fill_candle.timestamp)
                continue

            # Plana: sin posición abierta, sin excursión que auditar — la equity
            # realizada es la única cifra que existe para esta vela.
            intrabar_equity.append(broker.equity)

            history = candles[max(0, i + 1 - self.alpha_lookback_window) : i + 1]
            signal = self.alpha_engine.evaluate(history)
            if signal.direction == "HOLD":
                continue
            if signal.direction == "SELL" and not self.allow_short:
                continue

            atr = atr_series.iloc[i]
            if pd.isna(atr) or atr <= 0:
                continue

            monthly_dd, cumulative_dd, daily_loss = broker.drawdown_snapshot()

            cumulative_dd_breached = cumulative_dd <= -self.risk_engine.config.cumulative_drawdown_limit_pct
            if cumulative_dd_breached:
                if cumulative_breach_since is None:
                    cumulative_breach_since = candle.timestamp
                elif candle.timestamp - cumulative_breach_since >= cooldown:
                    broker.reset_drawdown_peak()
                    cumulative_breach_since = None
                    monthly_dd, cumulative_dd, daily_loss = broker.drawdown_snapshot()
            else:
                cumulative_breach_since = None

            risk_decision = self.risk_engine.evaluate(
                signal=signal,
                equity=broker.equity,
                atr=float(atr),
                entry_price=candle.close,
                open_positions=[],
                correlations={},
                monthly_drawdown_pct=monthly_dd,
                cumulative_drawdown_pct=cumulative_dd,
                daily_loss_pct=daily_loss,
            )
            if not risk_decision.approved:
                continue

            fill_candle = candles[i + 1]
            broker.open_position(
                symbol=candle.symbol,
                direction=signal.direction,
                price=fill_candle.open,
                size=risk_decision.size,
                stop_loss=risk_decision.stop_loss,
                risk_pct=self.risk_engine.config.risk_per_trade_pct,
                timestamp=fill_candle.timestamp,
                capped=risk_decision.capped,
            )

        return self._build_result(broker, intrabar_equity)

    def _build_result(self, broker: SimulatedBroker, intrabar_equity: list[float]) -> BacktestResult:
        # `equity_curve` (el campo público del resultado) queda como equity realizada
        # vela a vela de operaciones — histórico legible, "cuánto tenía al abrir/cerrar".
        # `intrabar_equity` (más fino, mark-to-market) solo alimenta `max_drawdown`:
        # compute_metrics deriva sharpe/sortino/win_rate/profit_factor/expectancy
        # directamente de `trades`, así que esto no afecta esas métricas (ver
        # metrics.py) — únicamente hace que el MDD refleje la excursión adversa
        # real dentro de una operación, no solo al cerrarla (requisito de precisión
        # del MDD, ver specs/002-motor-backtesting/tasks.md).
        return BacktestResult(
            trades=broker.trades,
            equity_curve=broker.equity_curve,
            final_equity=broker.equity,
            metrics=compute_metrics(broker.trades, intrabar_equity),
            open_position=broker.position,
        )
