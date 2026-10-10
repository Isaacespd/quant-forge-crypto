from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from trading_engine.models.candle import Candle, CandleSeriesError, validate_candle_series

UTC = timezone.utc


def make_candle(**overrides):
    defaults = dict(
        symbol="BTC/USDT",
        timeframe="1h",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=10.0,
    )
    defaults.update(overrides)
    return Candle(**defaults)


def test_valid_candle_is_accepted():
    candle = make_candle()
    assert candle.close == 105.0


def test_high_below_low_is_rejected():
    with pytest.raises(ValidationError):
        make_candle(high=80.0, low=90.0)


def test_open_outside_range_is_rejected():
    with pytest.raises(ValidationError):
        make_candle(open=200.0)


def test_close_outside_range_is_rejected():
    with pytest.raises(ValidationError):
        make_candle(close=1.0)


def test_zero_or_negative_price_is_rejected():
    with pytest.raises(ValidationError):
        make_candle(open=0)


def test_negative_volume_is_rejected():
    with pytest.raises(ValidationError):
        make_candle(volume=-1.0)


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValidationError):
        make_candle(timestamp=datetime(2026, 1, 1))


def test_unsupported_timeframe_is_rejected():
    with pytest.raises(ValidationError):
        make_candle(timeframe="7m")


def test_series_with_correct_step_passes():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [make_candle(timestamp=base + timedelta(hours=i)) for i in range(5)]
    validate_candle_series(candles, "1h")  # no debe lanzar


def test_series_with_duplicate_timestamp_is_rejected():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [make_candle(timestamp=base), make_candle(timestamp=base)]
    with pytest.raises(CandleSeriesError):
        validate_candle_series(candles, "1h")


def test_series_out_of_order_is_rejected():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [make_candle(timestamp=base + timedelta(hours=1)), make_candle(timestamp=base)]
    with pytest.raises(CandleSeriesError):
        validate_candle_series(candles, "1h")


def test_series_with_gap_is_rejected():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [make_candle(timestamp=base), make_candle(timestamp=base + timedelta(hours=2))]
    with pytest.raises(CandleSeriesError):
        validate_candle_series(candles, "1h")
