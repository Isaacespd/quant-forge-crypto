from datetime import datetime, timedelta, timezone

from trading_engine.alpha.simple_trend import SimpleTrendAlphaEngine
from trading_engine.models.candle import Candle

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def make_candles(closes, wick=0.5):
    return [
        Candle(
            symbol="BTC/USDT",
            timeframe="1h",
            timestamp=BASE + timedelta(hours=i),
            open=c - wick * 0.3,
            high=c + wick,
            low=c - wick,
            close=c,
            volume=10.0,
        )
        for i, c in enumerate(closes)
    ]


def test_returns_hold_with_insufficient_history():
    candles = make_candles([100.0] * 10)
    signal = SimpleTrendAlphaEngine().evaluate(candles)
    assert signal.direction == "HOLD"
    assert signal.confidence == 0.0


def test_buy_when_price_above_ema_trend():
    # 200 velas planas en 100 (EMA-200 converge a ~100) + una vela claramente por encima.
    candles = make_candles([100.0] * 200 + [120.0])
    signal = SimpleTrendAlphaEngine().evaluate(candles)
    assert signal.direction == "BUY"
    assert signal.confidence == 1.0


def test_sell_when_price_below_ema_trend():
    candles = make_candles([100.0] * 200 + [80.0])
    signal = SimpleTrendAlphaEngine().evaluate(candles)
    assert signal.direction == "SELL"
    assert signal.confidence == 1.0


def test_is_deterministic():
    candles = make_candles([100.0] * 200 + [120.0])
    first = SimpleTrendAlphaEngine().evaluate(candles)
    second = SimpleTrendAlphaEngine().evaluate(candles)
    assert first == second


def test_holds_within_the_atr_band_even_when_warmed_up():
    # Un movimiento minúsculo (dentro de k*ATR) no debe disparar BUY/SELL — es
    # precisamente la histéresis que evita el whipsaw (ver docstring de la clase).
    candles = make_candles([100.0] * 200 + [100.0001])
    signal = SimpleTrendAlphaEngine().evaluate(candles)
    assert signal.direction == "HOLD"


def test_wider_k_requires_a_larger_move_to_signal():
    candles = make_candles([100.0] * 200 + [103.0])
    tight = SimpleTrendAlphaEngine(k=1.0).evaluate(candles)
    wide = SimpleTrendAlphaEngine(k=5.0).evaluate(candles)
    assert tight.direction == "BUY"
    assert wide.direction == "HOLD"
