from trading_engine.models.risk_decision import RiskDecision
from trading_engine.models.signal import Signal
from trading_engine.risk.config import OpenPosition, RiskConfig
from trading_engine.risk.sizing import apply_notional_cap, position_size_by_volatility


def _rejected(reason: str) -> RiskDecision:
    return RiskDecision(approved=False, rejection_reason=reason)


class RiskEngine:
    """Cortafuegos financiero (docs/SDD.md §3.D): tiene autoridad para bloquear
    cualquier Signal, sin excepción, si viola un límite de riesgo.

    Función pura dado su input (docs/SDD.md §4.3 / plan 004) — no hace I/O propio,
    no recalcula histórico de precios ni mantiene estado entre llamadas. Quien la
    invoca (Motor de Backtesting o, en producción, el orquestador) le entrega el
    estado de cuenta y las posiciones abiertas ya calculados.
    """

    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig()

    def evaluate(
        self,
        signal: Signal,
        equity: float,
        atr: float,
        entry_price: float,
        open_positions: list[OpenPosition],
        correlations: dict[str, float],
        monthly_drawdown_pct: float,
        cumulative_drawdown_pct: float,
        daily_loss_pct: float,
        kill_switch_active: bool = False,
    ) -> RiskDecision:
        """
        `correlations`: symbol -> correlación entre ese símbolo (de una posición ya
        abierta) y `signal.symbol`. Solo hace falta una entrada por símbolo con
        posición abierta; RiskEngine no calcula correlaciones, las recibe ya calculadas.

        `monthly_drawdown_pct` / `cumulative_drawdown_pct` / `daily_loss_pct` se
        expresan como fracciones negativas (ej. -0.12 = -12%).
        """
        if kill_switch_active:
            return _rejected("kill_switch_active")

        if cumulative_drawdown_pct <= -self.config.cumulative_drawdown_limit_pct:
            return _rejected("cumulative_drawdown_limit_exceeded")

        if monthly_drawdown_pct <= -self.config.monthly_drawdown_limit_pct:
            return _rejected("monthly_drawdown_limit_exceeded")

        if daily_loss_pct <= -self.config.daily_loss_limit_pct:
            return _rejected("daily_loss_limit_exceeded")

        if signal.direction == "HOLD":
            return _rejected("signal_is_hold")

        projected_heat = sum(p.risk_pct for p in open_positions) + self.config.risk_per_trade_pct
        if projected_heat > self.config.max_portfolio_heat_pct:
            return _rejected("portfolio_heat_exceeded")

        for position in open_positions:
            if position.direction != signal.direction:
                continue
            correlation = correlations.get(position.symbol)
            if correlation is not None and correlation > self.config.max_correlation:
                return _rejected("correlation_limit_exceeded")

        raw_size = position_size_by_volatility(equity, atr, self.config)
        size, capped = apply_notional_cap(raw_size, entry_price, equity, self.config)
        stop_distance = atr * self.config.stop_atr_multiplier
        stop_loss = entry_price - stop_distance if signal.direction == "BUY" else entry_price + stop_distance

        return RiskDecision(approved=True, size=size, stop_loss=stop_loss, capped=capped)
