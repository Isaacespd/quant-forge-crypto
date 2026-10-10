from datetime import datetime, timedelta, timezone

import pytest

from trading_engine.backtesting.broker_sim import BacktestTrade
from trading_engine.backtesting.walk_forward import evaluate_walk_forward, generate_walk_forward_windows
from trading_engine.models.candle import Candle

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def test_generates_expected_number_of_windows():
    windows = generate_walk_forward_windows(n_candles=100, train_size=50, test_size=20, step=10)
    assert len(windows) == 4


def test_test_window_starts_exactly_where_train_ends():
    windows = generate_walk_forward_windows(n_candles=100, train_size=50, test_size=20, step=10)
    for window in windows:
        assert window.test_start == window.train_end


def test_windows_slide_by_step():
    windows = generate_walk_forward_windows(n_candles=100, train_size=50, test_size=20, step=10)
    starts = [w.train_start for w in windows]
    assert starts == [0, 10, 20, 30]


def test_no_window_exceeds_available_candles():
    windows = generate_walk_forward_windows(n_candles=100, train_size=50, test_size=20, step=10)
    for window in windows:
        assert window.test_end <= 100


def test_rejects_non_positive_parameters():
    with pytest.raises(ValueError):
        generate_walk_forward_windows(n_candles=100, train_size=0, test_size=20, step=10)
    with pytest.raises(ValueError):
        generate_walk_forward_windows(n_candles=100, train_size=50, test_size=0, step=10)
    with pytest.raises(ValueError):
        generate_walk_forward_windows(n_candles=100, train_size=50, test_size=20, step=0)


def test_too_little_data_yields_no_windows():
    windows = generate_walk_forward_windows(n_candles=10, train_size=50, test_size=20, step=10)
    assert windows == []


# --- evaluate_walk_forward: conecta el generador de ventanas con un motor de backtest ---


def make_candles(n):
    return [
        Candle(
            symbol="BTC/USDT",
            timeframe="1h",
            timestamp=BASE + timedelta(hours=i),
            open=100.0,
            high=100.5,
            low=99.5,
            close=100.0,
            volume=10.0,
        )
        for i in range(n)
    ]


def make_trade(opened_at, pnl):
    return BacktestTrade(
        symbol="BTC/USDT",
        direction="BUY",
        entry_price=100.0,
        exit_price=100.0 + pnl,
        size=1.0,
        pnl=pnl,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(hours=1),
    )


class _FakeResult:
    def __init__(self, trades):
        self.trades = trades


class _FakeEngine:
    """Devuelve siempre el mismo conjunto de trades, sin importar qué velas reciba —
    permite probar el filtrado por ventana de `evaluate_walk_forward` de forma aislada,
    sin depender de Alpha/Risk Engine reales.
    """

    def __init__(self, trades):
        self._trades = trades

    def run(self, candles):
        return _FakeResult(self._trades)


def test_evaluate_walk_forward_only_counts_trades_opened_within_test_window():
    candles = make_candles(100)
    windows = generate_walk_forward_windows(n_candles=100, train_size=50, test_size=20, step=30)
    assert len(windows) == 2  # train_start en [0, 30]; ventana 1: test [50,70), ventana 2: test [80,100)

    trades = [
        make_trade(candles[10].timestamp, pnl=100.0),  # antes del test de la ventana 1 (en su train) -> descartado
        make_trade(candles[55].timestamp, pnl=50.0),  # dentro del test de la ventana 1
        make_trade(candles[65].timestamp, pnl=-20.0),  # dentro del test de la ventana 1
    ]
    engine_factory = lambda: _FakeEngine(trades)

    results = evaluate_walk_forward(candles, windows, engine_factory, initial_equity=1000.0)

    assert len(results) == 2
    assert len(results[0].trades) == 2  # solo las dos que abrieron en [50,70)
    assert results[0].metrics["trade_count"] == 2
    assert results[0].test_start_timestamp == candles[50].timestamp


def test_evaluate_walk_forward_builds_equity_curve_from_initial_equity():
    candles = make_candles(100)
    windows = generate_walk_forward_windows(n_candles=100, train_size=50, test_size=20, step=30)

    trades = [make_trade(candles[55].timestamp, pnl=100.0), make_trade(candles[60].timestamp, pnl=-30.0)]
    engine_factory = lambda: _FakeEngine(trades)

    results = evaluate_walk_forward(candles, windows, engine_factory, initial_equity=1000.0)

    assert results[0].metrics["expectancy"] == pytest.approx((100.0 - 30.0) / 2)


def test_evaluate_walk_forward_calls_engine_factory_once_per_window():
    candles = make_candles(100)
    windows = generate_walk_forward_windows(n_candles=100, train_size=50, test_size=20, step=30)

    call_count = 0

    def counting_factory():
        nonlocal call_count
        call_count += 1
        return _FakeEngine([])

    evaluate_walk_forward(candles, windows, counting_factory)
    assert call_count == len(windows) == 2
