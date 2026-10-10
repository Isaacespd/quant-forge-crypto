from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from trading_engine.models.signal import Signal

UTC = timezone.utc


def make_signal(**overrides):
    defaults = dict(
        symbol="BTC/USDT",
        timeframe="1h",
        direction="BUY",
        confidence=0.8,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        strategy_id="trend_regime_v1",
    )
    defaults.update(overrides)
    return Signal(**defaults)


def test_valid_signal_is_accepted():
    signal = make_signal()
    assert signal.direction == "BUY"


def test_confidence_above_one_is_rejected():
    with pytest.raises(ValidationError):
        make_signal(confidence=1.5)


def test_confidence_below_zero_is_rejected():
    with pytest.raises(ValidationError):
        make_signal(confidence=-0.1)


def test_invalid_direction_is_rejected():
    with pytest.raises(ValidationError):
        make_signal(direction="MAYBE")


def test_signal_never_exposes_sizing_or_risk_fields():
    # Restricción de docs/SDD.md §3.C: el Alpha Engine no decide tamaño ni stop-loss/take-profit.
    forbidden_fields = {"size", "position_size", "stop_loss", "take_profit"}
    assert forbidden_fields.isdisjoint(Signal.model_fields.keys())
