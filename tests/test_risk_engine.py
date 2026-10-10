from datetime import datetime, timezone

import pytest

from trading_engine.models.signal import Signal
from trading_engine.risk.config import OpenPosition, RiskConfig
from trading_engine.risk.engine import RiskEngine
from trading_engine.risk.sizing import apply_notional_cap, position_size_by_volatility

UTC = timezone.utc


def make_signal(direction="BUY", symbol="BTC/USDT"):
    return Signal(
        symbol=symbol,
        timeframe="1h",
        direction=direction,
        confidence=1.0,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        strategy_id="trend_regime_v1",
    )


def base_kwargs(**overrides):
    defaults = dict(
        equity=100_000.0,
        atr=50.0,
        entry_price=60_000.0,
        open_positions=[],
        correlations={},
        monthly_drawdown_pct=0.0,
        cumulative_drawdown_pct=0.0,
        daily_loss_pct=0.0,
        kill_switch_active=False,
    )
    defaults.update(overrides)
    return defaults


# --- Sizing: fórmula de docs/SDD.md §5.2 contra un valor calculado a mano ---


def test_position_size_matches_hand_calculated_value():
    config = RiskConfig(risk_per_trade_pct=0.01, stop_atr_multiplier=2.0)
    # (100_000 * 0.01) / (50 * 2.0) = 1000 / 100 = 10.0
    size = position_size_by_volatility(equity=100_000.0, atr=50.0, config=config)
    assert size == pytest.approx(10.0)


def test_position_size_rejects_non_positive_atr():
    with pytest.raises(ValueError):
        position_size_by_volatility(equity=100_000.0, atr=0.0, config=RiskConfig())


# --- Techo de nocional: max_notional_pct limita el tamaño cuando el ATR% es bajo ---
# (causa raíz de la fragilidad a costos de BTC frente a ETH/SOL, ver
# specs/002-motor-backtesting/tasks.md — mismo riesgo%, más dólares por operación
# cuanto menor es la volatilidad relativa del activo)


def test_notional_cap_reduces_size_when_ideal_notional_exceeds_the_cap():
    config = RiskConfig(max_notional_pct=0.25)  # techo: 25% de 100_000 = $25,000
    size, capped = apply_notional_cap(size=10.0, entry_price=60_000.0, equity=100_000.0, config=config)

    assert capped is True
    assert size == pytest.approx(25_000.0 / 60_000.0)


def test_notional_cap_does_not_reduce_size_when_already_within_the_cap():
    config = RiskConfig(max_notional_pct=0.25)  # techo: $25,000
    size, capped = apply_notional_cap(size=0.1, entry_price=60_000.0, equity=100_000.0, config=config)

    assert capped is False
    assert size == pytest.approx(0.1)


def test_notional_cap_disabled_by_default_leaves_size_unchanged():
    size, capped = apply_notional_cap(size=10.0, entry_price=60_000.0, equity=100_000.0, config=RiskConfig())

    assert capped is False
    assert size == pytest.approx(10.0)


# --- Aprobación normal: tamaño y stop-loss coherentes con la fórmula ---


def test_approved_buy_has_expected_size_and_stop_loss():
    engine = RiskEngine(RiskConfig(risk_per_trade_pct=0.01, stop_atr_multiplier=2.0))
    decision = engine.evaluate(make_signal("BUY"), **base_kwargs())

    assert decision.approved is True
    assert decision.rejection_reason is None
    assert decision.size == pytest.approx(10.0)
    assert decision.stop_loss == pytest.approx(60_000.0 - 50.0 * 2.0)


def test_approved_sell_stop_loss_is_above_entry():
    engine = RiskEngine(RiskConfig(risk_per_trade_pct=0.01, stop_atr_multiplier=2.0))
    decision = engine.evaluate(make_signal("SELL"), **base_kwargs())

    assert decision.approved is True
    assert decision.stop_loss == pytest.approx(60_000.0 + 50.0 * 2.0)


def test_risk_engine_applies_notional_cap_and_flags_the_decision():
    config = RiskConfig(risk_per_trade_pct=0.01, stop_atr_multiplier=2.0, max_notional_pct=0.25)
    engine = RiskEngine(config)
    decision = engine.evaluate(make_signal("BUY"), **base_kwargs())

    # Sin techo, size sería 10.0 (notional $600,000) -- con techo 25% de 100_000 = $25,000
    assert decision.approved is True
    assert decision.capped is True
    assert decision.size == pytest.approx(25_000.0 / 60_000.0)


def test_risk_engine_without_notional_cap_configured_leaves_decision_uncapped():
    engine = RiskEngine(RiskConfig(risk_per_trade_pct=0.01, stop_atr_multiplier=2.0))
    decision = engine.evaluate(make_signal("BUY"), **base_kwargs())

    assert decision.capped is False
    assert decision.size == pytest.approx(10.0)


def test_hold_signal_is_rejected_without_touching_risk_limits():
    engine = RiskEngine()
    decision = engine.evaluate(make_signal("HOLD"), **base_kwargs())

    assert decision.approved is False
    assert decision.rejection_reason == "signal_is_hold"


# --- Cada circuit breaker, aislado ---


def test_kill_switch_rejects_unconditionally():
    engine = RiskEngine()
    decision = engine.evaluate(make_signal("BUY"), **base_kwargs(kill_switch_active=True))

    assert decision.approved is False
    assert decision.rejection_reason == "kill_switch_active"


def test_monthly_drawdown_circuit_breaker():
    config = RiskConfig(monthly_drawdown_limit_pct=0.10)
    engine = RiskEngine(config)
    decision = engine.evaluate(make_signal("BUY"), **base_kwargs(monthly_drawdown_pct=-0.10))

    assert decision.approved is False
    assert decision.rejection_reason == "monthly_drawdown_limit_exceeded"


def test_monthly_drawdown_within_limit_is_not_rejected_by_it():
    config = RiskConfig(monthly_drawdown_limit_pct=0.10)
    engine = RiskEngine(config)
    decision = engine.evaluate(make_signal("BUY"), **base_kwargs(monthly_drawdown_pct=-0.05))

    assert decision.rejection_reason != "monthly_drawdown_limit_exceeded"


def test_cumulative_drawdown_circuit_breaker():
    config = RiskConfig(cumulative_drawdown_limit_pct=0.20)
    engine = RiskEngine(config)
    decision = engine.evaluate(make_signal("BUY"), **base_kwargs(cumulative_drawdown_pct=-0.25))

    assert decision.approved is False
    assert decision.rejection_reason == "cumulative_drawdown_limit_exceeded"


def test_daily_loss_circuit_breaker():
    config = RiskConfig(daily_loss_limit_pct=0.03)
    engine = RiskEngine(config)
    decision = engine.evaluate(make_signal("BUY"), **base_kwargs(daily_loss_pct=-0.03))

    assert decision.approved is False
    assert decision.rejection_reason == "daily_loss_limit_exceeded"


def test_portfolio_heat_circuit_breaker():
    config = RiskConfig(risk_per_trade_pct=0.02, max_portfolio_heat_pct=0.06)
    engine = RiskEngine(config)
    open_positions = [
        OpenPosition(symbol="ETH/USDT", direction="BUY", risk_pct=0.05),
    ]
    # 0.05 (ya abierto) + 0.02 (esta operación) = 0.07 > 0.06 -> rechazado
    decision = engine.evaluate(make_signal("BUY"), **base_kwargs(open_positions=open_positions))

    assert decision.approved is False
    assert decision.rejection_reason == "portfolio_heat_exceeded"


def test_portfolio_heat_within_limit_is_approved():
    config = RiskConfig(risk_per_trade_pct=0.01, max_portfolio_heat_pct=0.06)
    engine = RiskEngine(config)
    open_positions = [
        OpenPosition(symbol="ETH/USDT", direction="BUY", risk_pct=0.02),
    ]
    decision = engine.evaluate(make_signal("BUY"), **base_kwargs(open_positions=open_positions))

    assert decision.approved is True


def test_correlation_circuit_breaker_same_direction():
    config = RiskConfig(max_correlation=0.7)
    engine = RiskEngine(config)
    open_positions = [
        OpenPosition(symbol="ETH/USDT", direction="BUY", risk_pct=0.01),
    ]
    decision = engine.evaluate(
        make_signal("BUY", symbol="BTC/USDT"),
        **base_kwargs(open_positions=open_positions, correlations={"ETH/USDT": 0.85}),
    )

    assert decision.approved is False
    assert decision.rejection_reason == "correlation_limit_exceeded"


def test_correlation_circuit_breaker_ignores_opposite_direction():
    config = RiskConfig(max_correlation=0.7)
    engine = RiskEngine(config)
    open_positions = [
        OpenPosition(symbol="ETH/USDT", direction="SELL", risk_pct=0.01),
    ]
    decision = engine.evaluate(
        make_signal("BUY", symbol="BTC/USDT"),
        **base_kwargs(open_positions=open_positions, correlations={"ETH/USDT": 0.85}),
    )

    assert decision.approved is True


def test_correlation_below_limit_is_approved():
    config = RiskConfig(max_correlation=0.7)
    engine = RiskEngine(config)
    open_positions = [
        OpenPosition(symbol="ETH/USDT", direction="BUY", risk_pct=0.01),
    ]
    decision = engine.evaluate(
        make_signal("BUY", symbol="BTC/USDT"),
        **base_kwargs(open_positions=open_positions, correlations={"ETH/USDT": 0.5}),
    )

    assert decision.approved is True


# --- El circuit breaker de drawdown no toca posiciones ya abiertas ---


def test_drawdown_rejection_does_not_mutate_open_positions():
    engine = RiskEngine(RiskConfig(monthly_drawdown_limit_pct=0.10))
    open_positions = [OpenPosition(symbol="ETH/USDT", direction="BUY", risk_pct=0.01)]
    open_positions_snapshot = list(open_positions)

    decision = engine.evaluate(
        make_signal("BUY"), **base_kwargs(open_positions=open_positions, monthly_drawdown_pct=-0.15)
    )

    assert decision.approved is False
    assert open_positions == open_positions_snapshot  # RiskEngine no cierra ni modifica posiciones


# --- Ningún límite hardcodeado: todo sale de RiskConfig ---


def test_all_thresholds_come_from_config_not_hardcoded():
    lenient_config = RiskConfig(
        max_portfolio_heat_pct=0.99,
        max_correlation=0.99,
        monthly_drawdown_limit_pct=0.99,
        cumulative_drawdown_limit_pct=0.99,
        daily_loss_limit_pct=0.99,
    )
    engine = RiskEngine(lenient_config)
    open_positions = [OpenPosition(symbol="ETH/USDT", direction="BUY", risk_pct=0.5)]

    decision = engine.evaluate(
        make_signal("BUY", symbol="BTC/USDT"),
        **base_kwargs(
            open_positions=open_positions,
            correlations={"ETH/USDT": 0.95},
            monthly_drawdown_pct=-0.5,
            cumulative_drawdown_pct=-0.5,
            daily_loss_pct=-0.5,
        ),
    )

    assert decision.approved is True
