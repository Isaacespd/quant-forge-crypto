from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from trading_engine.alpha.indicators import MIN_CANDLES_FOR_INDICATORS
from trading_engine.alpha.strategy import AlphaEngine
from trading_engine.backtesting.engine import BacktestEngine
from trading_engine.backtesting.metrics import max_drawdown
from trading_engine.models.candle import Candle
from trading_engine.models.signal import Signal
from trading_engine.risk.config import RiskConfig
from trading_engine.risk.engine import RiskEngine

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def make_candles(closes, wick=0.1):
    return [
        Candle(
            symbol="BTC/USDT",
            timeframe="1h",
            timestamp=BASE + timedelta(hours=i),
            open=c - wick * 0.5,
            high=c + wick,
            low=c - wick,
            close=c,
            volume=10.0,
        )
        for i, c in enumerate(closes)
    ]


def flat_then_trend_candles():
    # 250 velas planas: warm-up suficiente para MIN_CANDLES_FOR_INDICATORS (214, por la
    # EMA-200 del filtro de tendencia macro) antes de que empiece la tendencia.
    flat = [100.0] * 250
    trend = list(100 + np.arange(1, 41) * 0.8)
    return make_candles(flat + trend)


def cyclical_candles(n=3000, seed=21):
    # Drift de fondo (para que la EMA-200 marque una tendencia real) + oscilación
    # superpuesta de período largo + ruido iid dominante localmente (mantiene ADX bajo
    # entre oscilaciones) — produce operaciones reales en ambas direcciones bajo el
    # filtro de tendencia macro, sin necesidad de que la estrategia sea rentable.
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    drift = 100 + 0.05 * t
    cycle = 20 * np.sin(2 * np.pi * t / 300)
    noise = rng.normal(0, 2.0, n)
    closes = drift + cycle + noise
    return make_candles(closes, wick=0.5)


def new_engine(**overrides):
    kwargs = dict(initial_equity=100_000.0, commission_pct=0.001, slippage_pct=0.0005)
    kwargs.update(overrides)
    return BacktestEngine(AlphaEngine(), RiskEngine(), **kwargs)


# --- Sin look-ahead: el fill de entrada ocurre en el open de la vela SIGUIENTE ---


def test_entry_fills_at_next_bar_open_not_signal_bar_close():
    candles = flat_then_trend_candles()[:252]  # justo hasta un paso después del cruce (bar 250)
    result = new_engine().run(candles)

    assert result.open_position is not None
    assert result.open_position.direction == "BUY"

    expected_fill = candles[251].open * (1 + 0.0005)
    look_ahead_bug_fill = candles[250].close * (1 + 0.0005)

    assert result.open_position.entry_price == expected_fill
    assert result.open_position.entry_price != look_ahead_bug_fill


# --- Determinismo ---


def test_backtest_is_deterministic():
    candles = cyclical_candles()

    first = new_engine().run(candles)
    second = new_engine().run(candles)

    assert first.trades == second.trades
    assert first.final_equity == second.final_equity
    assert first.metrics == second.metrics


# --- El modelo de costos cambia el resultado de forma medible ---
#
# Nota de diseño: el modelado fino de comisión/slippage/trailing-stop se prueba de
# forma aislada y determinista en tests/test_broker_sim.py (SimulatedBroker directo).
# Aquí solo se verifica que BacktestEngine efectivamente conecta esos parámetros —
# comparar corridas completas de varias operaciones es engañoso, porque los circuit
# breakers de Risk Engine reaccionan a la equity: una corrida con más costos puede
# terminar rechazando una operación perdedora que la corrida sin costos sí tomó
# (comprobado empíricamente: 16 vs 15 operaciones, la de más costos "ganando" por
# quedarse afuera de una pérdida). Por eso se usa un fixture corto de una sola
# entrada, sin cierre, donde el único evento de costo es el fill inicial.


def test_commission_and_slippage_change_entry_fill_price():
    candles = flat_then_trend_candles()[:252]

    zero_cost = new_engine(commission_pct=0.0, slippage_pct=0.0).run(candles)
    with_cost = new_engine(commission_pct=0.001, slippage_pct=0.0005).run(candles)

    assert zero_cost.open_position is not None
    assert with_cost.open_position is not None
    assert with_cost.open_position.entry_price > zero_cost.open_position.entry_price  # slippage al comprar
    assert with_cost.final_equity < zero_cost.final_equity  # comisión descontada al abrir


# --- Cooldown del circuit breaker de drawdown acumulado ---
# Bug real encontrado corriendo 8.6 años de historia (specs/002/tasks.md): sin esto,
# una vez cruzado el umbral de drawdown acumulado, el sistema queda bloqueado para
# siempre — la equity congelada nunca vuelve a superar su propio pico.


class _AlwaysBuySignal:
    """AlphaEngine falso: siempre BUY. Aísla la prueba del cooldown de si el mercado
    sintético produce señales reales o no."""

    def evaluate(self, candles):
        from trading_engine.models.signal import Signal

        last = candles[-1]
        return Signal(
            symbol=last.symbol,
            timeframe=last.timeframe,
            direction="BUY",
            confidence=1.0,
            timestamp=last.timestamp,
            strategy_id="fake_always_buy",
        )


def test_drawdown_breaker_releases_after_cooldown_and_resets_peak():
    from trading_engine.risk.config import RiskConfig

    flat = [100.0] * 217
    crash = [80.0]  # perfora el stop de la primera posición -> pérdida que cruza el umbral
    gap = [100.0] * 60  # cubre el cooldown (24h) y deja tiempo a que se abra la segunda posición
    crash2 = [80.0]  # perfora el stop de la segunda posición, para poder comparar dos operaciones cerradas
    tail = [100.0] * 50
    candles = make_candles(flat + crash + gap + crash2 + tail, wick=0.5)

    risk_config = RiskConfig(cumulative_drawdown_limit_pct=0.005)  # umbral bajo: una sola pérdida lo cruza
    engine = BacktestEngine(
        _AlwaysBuySignal(), RiskEngine(risk_config), initial_equity=100_000.0, drawdown_cooldown_days=1
    )

    result = engine.run(candles)

    assert len(result.trades) == 2
    first, second = result.trades
    assert first.pnl < 0  # la pérdida que cruza el umbral

    gap = second.opened_at - first.closed_at
    assert gap >= timedelta(hours=24)  # no reabre antes de que termine el cooldown
    assert gap < timedelta(hours=48)  # pero sí se reanuda, no queda bloqueado para siempre


# --- Advertencia de significancia estadística con pocas operaciones ---


def test_report_warns_when_few_trades():
    candles = cyclical_candles()
    result = new_engine().run(candles)

    assert 0 < result.metrics["trade_count"] < 100
    assert result.metrics["warnings"]


# --- Insuficientes datos: no debe fallar, solo no operar ---


def test_insufficient_history_produces_no_trades_and_no_crash():
    candles = make_candles([100.0] * 10)
    result = new_engine().run(candles)

    assert result.trades == []
    assert result.final_equity == 100_000.0


# --- max_notional_pct: el techo de nocional efectivamente reduce el tamaño y lo marca ---


def test_max_notional_pct_caps_position_size_end_to_end():
    candles = make_candles([105.0] * 225 + [104.0] * 10, wick=0.5)

    uncapped = BacktestEngine(_ThresholdSignal(100.0), RiskEngine(RiskConfig())).run(candles)
    capped = BacktestEngine(_ThresholdSignal(100.0), RiskEngine(RiskConfig(max_notional_pct=0.05))).run(candles)

    assert uncapped.open_position is not None
    assert capped.open_position is not None
    assert uncapped.open_position.capped is False
    assert capped.open_position.capped is True
    assert capped.open_position.size < uncapped.open_position.size


# --- warmup_candles / alpha_lookback_window: configurables por instancia, no una sola ---
# constante compartida — el warm-up correcto depende de qué alpha_engine se conecte
# (AlphaEngine necesita MIN_CANDLES_FOR_INDICATORS con ADX; SimpleTrendAlphaEngine solo
# MIN_CANDLES_FOR_TREND_ONLY, sin ADX/RSI/Bollinger/MACD).


def test_warmup_and_lookback_default_to_the_previous_shared_constants():
    engine = new_engine()
    assert engine.warmup_candles == MIN_CANDLES_FOR_INDICATORS
    assert engine.alpha_lookback_window == BacktestEngine.ALPHA_LOOKBACK_WINDOW


def test_warmup_candles_controls_when_the_loop_starts_evaluating_signals():
    # 205 velas planas bajo el umbral (señal SELL) + 20 velas sobre el umbral (señal BUY).
    candles = make_candles([50.0] * 205 + [150.0] * 20, wick=0.5)

    early = BacktestEngine(_ThresholdSignal(100.0), RiskEngine(RiskConfig()), warmup_candles=180).run(candles)
    late = BacktestEngine(_ThresholdSignal(100.0), RiskEngine(RiskConfig()), warmup_candles=224).run(candles)

    assert early.open_position is not None  # con warmup=180 el bucle sí llega a evaluar señales
    assert late.open_position is None  # con warmup=224 el bucle queda vacío (len(candles)-1 == 224)


# --- exit_on_opposite_signal / allow_short: opt-in para SimpleTrendAlphaEngine ---
# (necesita salir de una posición cuando la tendencia se revierte, no solo por stop-loss)


class _ThresholdSignal:
    """Alpha falso: BUY si el cierre >= umbral, SELL si no. Aísla la prueba del motor
    de si un indicador real produce la señal o no."""

    def __init__(self, threshold=100.0):
        self.threshold = threshold

    def evaluate(self, candles):
        last = candles[-1]
        direction = "BUY" if last.close >= self.threshold else "SELL"
        return Signal(
            symbol=last.symbol,
            timeframe=last.timeframe,
            direction=direction,
            confidence=1.0,
            timestamp=last.timestamp,
            strategy_id="fake_threshold",
        )


def test_exit_on_opposite_signal_closes_position_before_stop_loss():
    # stop_atr_multiplier=100 deja el stop-loss inalcanzable a propósito: cualquier
    # cierre que ocurra sólo puede venir de la señal opuesta, nunca del stop.
    candles = make_candles([105.0] * 225 + [95.0] * 30, wick=0.5)
    engine = BacktestEngine(
        _ThresholdSignal(100.0), RiskEngine(RiskConfig(stop_atr_multiplier=100)), exit_on_opposite_signal=True
    )

    result = engine.run(candles)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.direction == "BUY"
    assert trade.exit_price < 100.0  # cerró ya en la zona de velas bajo el umbral, no en el stop (~5)


def test_exit_on_opposite_signal_fills_at_next_bar_open_not_signal_bar_close():
    # Requisito de look-ahead (specs/002/tasks.md): la señal opuesta se evalúa con el
    # close de la vela t, pero la salida DEBE ejecutarse al open de t+1 — nunca al close
    # de t, que es precisamente el precio que se está usando para decidir.
    candles = make_candles([105.0] * 225 + [95.0] * 30, wick=0.5)
    engine = BacktestEngine(
        _ThresholdSignal(100.0), RiskEngine(RiskConfig(stop_atr_multiplier=100)), exit_on_opposite_signal=True
    )

    result = engine.run(candles)

    assert len(result.trades) == 1
    trade = result.trades[0]

    # La señal opuesta (close=95 < 100) se confirma por primera vez en la vela 225;
    # el fill de salida debe ocurrir al open de la vela SIGUIENTE (226).
    expected_exit = candles[226].open * (1 - engine.slippage_pct)
    look_ahead_bug_exit = candles[225].close * (1 - engine.slippage_pct)

    assert trade.exit_price == pytest.approx(expected_exit)
    assert trade.exit_price != pytest.approx(look_ahead_bug_exit)


def test_exit_on_opposite_signal_off_by_default_keeps_position_open():
    candles = make_candles([105.0] * 225 + [95.0] * 30, wick=0.5)
    engine = BacktestEngine(_ThresholdSignal(100.0), RiskEngine(RiskConfig(stop_atr_multiplier=100)))

    result = engine.run(candles)

    assert result.trades == []  # nunca cierra: ni señal (apagado) ni stop (inalcanzable)
    assert result.open_position is not None
    assert result.open_position.direction == "BUY"


def test_allow_short_false_blocks_new_short_entries():
    candles = make_candles([95.0] * 220, wick=0.5)  # todo el histórico bajo el umbral -> señal SELL
    engine = BacktestEngine(_ThresholdSignal(100.0), RiskEngine(RiskConfig()), allow_short=False)

    result = engine.run(candles)

    assert result.trades == []
    assert result.open_position is None


# --- MDD intrabar: una mecha profunda debe reflejarse aunque el cierre real sea más suave ---


def test_intrabar_low_captures_deeper_drawdown_than_realized_equity_alone():
    # La mecha (low=95) queda muy por debajo de donde efectivamente cierra la posición
    # (el stop-loss, ~103): la equity *realizada* solo ve la pérdida hasta el stop, pero
    # el requisito de MDD preciso exige auditar el low real de la vela mientras la
    # posición estuvo abierta (excursión adversa máxima), no solo el precio de cierre.
    candles = make_candles([105.0] * 226 + [104.0] * 10, wick=0.5)
    candles[226].low = 95.0

    engine = BacktestEngine(_ThresholdSignal(100.0), RiskEngine(RiskConfig()), initial_equity=100_000.0)
    result = engine.run(candles)

    realized_only = max_drawdown([engine.initial_equity] + [equity for _, equity in result.equity_curve])
    assert result.metrics["max_drawdown"] < realized_only


def test_allow_short_true_by_default_opens_short_entries():
    candles = make_candles([95.0] * 220, wick=0.5)
    engine = BacktestEngine(_ThresholdSignal(100.0), RiskEngine(RiskConfig()))

    result = engine.run(candles)

    assert result.open_position is not None
    assert result.open_position.direction == "SELL"
