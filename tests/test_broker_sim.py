from datetime import datetime, timedelta, timezone

import pytest

from trading_engine.backtesting.broker_sim import SimulatedBroker

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def opened_broker(direction="BUY", commission_pct=0.0, slippage_pct=0.0, entry_price=100.0, stop_loss=98.0):
    broker = SimulatedBroker(initial_equity=100_000.0, commission_pct=commission_pct, slippage_pct=slippage_pct)
    if direction == "SELL":
        stop_loss = 102.0
    broker.open_position(
        symbol="BTC/USDT",
        direction=direction,
        price=entry_price,
        size=10.0,
        stop_loss=stop_loss,
        risk_pct=0.01,
        timestamp=BASE,
    )
    return broker


# --- Comisión y slippage al abrir/cerrar ---


def test_open_position_buy_applies_positive_slippage():
    broker = opened_broker(direction="BUY", entry_price=100.0, slippage_pct=0.0005)
    # BUY paga de más por el slippage: fill > precio de referencia.
    assert broker.position.entry_price == pytest.approx(100.0 * 1.0005)


def test_open_position_sell_applies_negative_slippage():
    broker = opened_broker(direction="SELL", entry_price=100.0, slippage_pct=0.0005)
    # SELL recibe de menos por el slippage: fill < precio de referencia.
    assert broker.position.entry_price == pytest.approx(100.0 * 0.9995)


def test_open_position_deducts_commission_from_equity_immediately():
    broker = opened_broker(commission_pct=0.001, slippage_pct=0.0)
    expected_commission = 100.0 * 10.0 * 0.001
    assert broker.equity == pytest.approx(100_000.0 - expected_commission)


def test_close_position_computes_pnl_net_of_commission():
    broker = opened_broker(direction="BUY", commission_pct=0.001, slippage_pct=0.0, entry_price=100.0)
    trade = broker.close_position(price=110.0, timestamp=BASE + timedelta(hours=1))

    exit_commission = 110.0 * 10.0 * 0.001
    expected_pnl = (110.0 - 100.0) * 10.0 - exit_commission
    assert trade.pnl == pytest.approx(expected_pnl)
    assert broker.position is None


def test_zero_cost_vs_with_cost_same_trade_has_different_pnl():
    zero_cost = opened_broker(commission_pct=0.0, slippage_pct=0.0, entry_price=100.0)
    with_cost = opened_broker(commission_pct=0.001, slippage_pct=0.0005, entry_price=100.0)

    zero_trade = zero_cost.close_position(price=110.0, timestamp=BASE + timedelta(hours=1))
    cost_trade = with_cost.close_position(price=110.0, timestamp=BASE + timedelta(hours=1))

    assert cost_trade.pnl < zero_trade.pnl
    assert with_cost.equity < zero_cost.equity


def test_close_without_open_position_raises():
    broker = SimulatedBroker(initial_equity=100_000.0)
    with pytest.raises(RuntimeError):
        broker.close_position(price=100.0, timestamp=BASE)


def test_capped_flag_and_risk_pct_propagate_to_the_closed_trade():
    broker = SimulatedBroker(initial_equity=100_000.0)
    broker.open_position(
        symbol="BTC/USDT", direction="BUY", price=100.0, size=1.0, stop_loss=98.0,
        risk_pct=0.01, timestamp=BASE, capped=True,
    )
    trade = broker.close_position(price=110.0, timestamp=BASE + timedelta(hours=1))

    assert trade.capped is True
    assert trade.risk_pct == pytest.approx(0.01)


def test_open_position_defaults_to_not_capped():
    broker = opened_broker()
    trade = broker.close_position(price=110.0, timestamp=BASE + timedelta(hours=1))

    assert trade.capped is False


def test_open_position_twice_raises():
    broker = opened_broker()
    with pytest.raises(RuntimeError):
        broker.open_position(
            symbol="BTC/USDT", direction="BUY", price=100.0, size=1.0, stop_loss=90.0, risk_pct=0.01, timestamp=BASE
        )


# --- Mark-to-market intrabar: MDD real (excursión adversa máxima), no solo al cerrar ---
# Requisito: mientras hay posición abierta, el motor debe poder valorarla al precio más
# adverso de la vela (low en BUY, high en SELL) sin cerrarla ni tocar la equity real.


def test_mark_to_market_equity_buy_uses_low_as_the_adverse_price():
    broker = opened_broker(direction="BUY", entry_price=100.0, stop_loss=98.0)  # size=10.0
    assert broker.mark_to_market_equity(low=95.0, high=101.0) == pytest.approx(100_000.0 - 50.0)
    assert broker.equity == 100_000.0  # no muta la equity real


def test_mark_to_market_equity_sell_uses_high_as_the_adverse_price():
    broker = opened_broker(direction="SELL", entry_price=100.0)  # stop_loss=102.0, size=10.0
    assert broker.mark_to_market_equity(low=99.0, high=105.0) == pytest.approx(100_000.0 - 50.0)
    assert broker.equity == 100_000.0


def test_mark_to_market_equity_returns_current_equity_when_flat():
    broker = SimulatedBroker(initial_equity=100_000.0)
    assert broker.mark_to_market_equity(low=1.0, high=1_000_000.0) == 100_000.0


# --- Stop-loss (sin trailing) ---


def test_stop_loss_hit_buy_when_low_breaches_stop():
    broker = opened_broker(direction="BUY", entry_price=100.0, stop_loss=98.0)
    assert broker.stop_loss_hit(high=101.0, low=97.9) is True
    assert broker.stop_loss_hit(high=101.0, low=98.1) is False


def test_stop_loss_hit_sell_when_high_breaches_stop():
    broker = opened_broker(direction="SELL", entry_price=100.0)  # stop_loss=102.0
    assert broker.stop_loss_hit(high=102.1, low=99.0) is True
    assert broker.stop_loss_hit(high=101.9, low=99.0) is False


def test_stop_loss_hit_false_when_flat():
    broker = SimulatedBroker(initial_equity=100_000.0)
    assert broker.stop_loss_hit(high=1000.0, low=0.0) is False


# --- Trailing stop: agregado tras evidencia real de backtest (specs/002/tasks.md) ---
# Un stop fijo sin trailing devolvía ganancias grandes como pérdidas cuando el precio
# eventualmente retrocedía. El trailing se mueve a favor de la posición, nunca en contra.


def test_trailing_stop_moves_up_for_buy_as_price_rises():
    broker = opened_broker(direction="BUY", entry_price=100.0, stop_loss=98.0)  # trail_distance = 2.0
    broker.update_trailing_stop(high=110.0, low=109.0)
    assert broker.position.stop_loss == pytest.approx(108.0)  # 110 - 2.0


def test_trailing_stop_never_loosens_for_buy():
    broker = opened_broker(direction="BUY", entry_price=100.0, stop_loss=98.0)
    broker.update_trailing_stop(high=110.0, low=109.0)  # stop sube a 108.0
    broker.update_trailing_stop(high=103.0, low=102.0)  # precio retrocede, no debe bajar el stop
    assert broker.position.stop_loss == pytest.approx(108.0)


def test_trailing_stop_moves_down_for_sell_as_price_falls():
    broker = opened_broker(direction="SELL", entry_price=100.0)  # stop_loss=102.0, trail_distance=2.0
    broker.update_trailing_stop(high=91.0, low=90.0)
    assert broker.position.stop_loss == pytest.approx(92.0)  # 90 + 2.0


def test_trailing_stop_never_loosens_for_sell():
    broker = opened_broker(direction="SELL", entry_price=100.0)
    broker.update_trailing_stop(high=91.0, low=90.0)  # stop baja a 92.0
    broker.update_trailing_stop(high=99.0, low=98.0)  # precio retrocede, no debe subir el stop
    assert broker.position.stop_loss == pytest.approx(92.0)


def test_trailing_stop_does_nothing_when_flat():
    broker = SimulatedBroker(initial_equity=100_000.0)
    broker.update_trailing_stop(high=110.0, low=109.0)  # no debe lanzar excepción
    assert broker.position is None


# --- Drawdown / períodos calendario ---


def test_drawdown_snapshot_cumulative_from_peak():
    broker = SimulatedBroker(initial_equity=100_000.0)
    broker.equity = 90_000.0
    _, cumulative, _ = broker.drawdown_snapshot()
    assert cumulative == pytest.approx(-0.10)


def test_mark_period_resets_monthly_and_daily_anchors():
    broker = SimulatedBroker(initial_equity=100_000.0)
    broker.mark_period(datetime(2026, 1, 15, tzinfo=UTC))
    broker.equity = 95_000.0

    monthly, _, daily = broker.drawdown_snapshot()
    assert monthly == pytest.approx(-0.05)
    assert daily == pytest.approx(-0.05)

    # Nuevo mes y nuevo día: las anclas se resetean a la equity actual.
    broker.mark_period(datetime(2026, 2, 1, tzinfo=UTC))
    monthly, _, daily = broker.drawdown_snapshot()
    assert monthly == pytest.approx(0.0)
    assert daily == pytest.approx(0.0)


# --- reset_drawdown_peak: sin esto, el breaker de drawdown acumulado nunca se libera solo ---
# (bug real encontrado corriendo 8.6 años de historia — ver specs/002-motor-backtesting/tasks.md)


def test_reset_drawdown_peak_clears_cumulative_drawdown():
    broker = SimulatedBroker(initial_equity=100_000.0)
    broker.equity = 70_000.0  # -30% acumulado respecto al pico inicial

    _, cumulative_before, _ = broker.drawdown_snapshot()
    assert cumulative_before == pytest.approx(-0.30)

    broker.reset_drawdown_peak()

    _, cumulative_after, _ = broker.drawdown_snapshot()
    assert cumulative_after == pytest.approx(0.0)


def test_reset_drawdown_peak_does_not_touch_equity_or_position():
    broker = opened_broker(direction="BUY", entry_price=100.0)
    broker.equity = 70_000.0

    broker.reset_drawdown_peak()

    assert broker.equity == 70_000.0
    assert broker.position is not None  # no cierra ni toca la posición abierta
