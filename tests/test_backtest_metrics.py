from datetime import datetime, timedelta, timezone

import pytest

from trading_engine.backtesting.broker_sim import BacktestTrade
from trading_engine.backtesting.metrics import (
    compute_metrics,
    expectancy,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    significance_warning,
    sortino_ratio,
    win_rate,
)

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def make_trade(pnl: float, entry_price: float = 100.0, size: float = 1.0) -> BacktestTrade:
    return BacktestTrade(
        symbol="BTC/USDT",
        direction="BUY",
        entry_price=entry_price,
        exit_price=entry_price + pnl / size,
        size=size,
        pnl=pnl,
        opened_at=BASE,
        closed_at=BASE + timedelta(hours=1),
    )


def test_sharpe_ratio_constant_returns_is_zero():
    assert sharpe_ratio([1.0, 1.0, 1.0]) == 0.0


def test_sharpe_ratio_matches_hand_calculation():
    # media=3, desviación poblacional=1 -> sharpe=3.0
    assert sharpe_ratio([2.0, 4.0]) == pytest.approx(3.0)


def test_sharpe_ratio_needs_at_least_two_points():
    assert sharpe_ratio([5.0]) == 0.0
    assert sharpe_ratio([]) == 0.0


def test_sortino_ratio_no_downside_is_zero():
    assert sortino_ratio([2.0, 4.0]) == 0.0


def test_sortino_ratio_matches_hand_calculation():
    # downside deviation = sqrt((4 + 0) / 2) = sqrt(2); media = 1 -> sortino = 1/sqrt(2)
    assert sortino_ratio([-2.0, 4.0]) == pytest.approx(1 / (2**0.5))


def test_max_drawdown_matches_hand_calculation():
    assert max_drawdown([100, 90, 95, 80, 120]) == pytest.approx(-0.20)


def test_max_drawdown_never_below_peak_is_zero():
    assert max_drawdown([100, 105, 110]) == 0.0


def test_max_drawdown_empty_is_zero():
    assert max_drawdown([]) == 0.0


def test_win_rate_matches_hand_calculation():
    trades = [make_trade(10), make_trade(-5), make_trade(20), make_trade(-1)]
    assert win_rate(trades) == pytest.approx(0.5)


def test_win_rate_no_trades_is_zero():
    assert win_rate([]) == 0.0


def test_profit_factor_matches_hand_calculation():
    trades = [make_trade(10), make_trade(-5), make_trade(20)]
    # gross_profit=30, gross_loss=5 -> 6.0
    assert profit_factor(trades) == pytest.approx(6.0)


def test_profit_factor_no_losses_is_infinite():
    trades = [make_trade(10), make_trade(5)]
    assert profit_factor(trades) == float("inf")


def test_profit_factor_no_trades_is_zero():
    assert profit_factor([]) == 0.0


def test_expectancy_matches_hand_calculation():
    trades = [make_trade(10), make_trade(-5), make_trade(1)]
    assert expectancy(trades) == pytest.approx(2.0)


def test_significance_warning_below_threshold():
    warning = significance_warning(50)
    assert warning is not None
    assert "50" in warning


def test_significance_warning_above_threshold_is_none():
    assert significance_warning(150) is None


def test_compute_metrics_includes_warning_for_few_trades():
    trades = [make_trade(10, entry_price=100.0, size=1.0)]
    report = compute_metrics(trades, equity_curve=[100_000.0, 100_010.0])
    assert report["trade_count"] == 1
    assert report["warnings"]  # no vacío
