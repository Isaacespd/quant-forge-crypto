from datetime import datetime, timedelta, timezone

import numpy as np

from trading_engine.alpha.strategy import AlphaEngine
from trading_engine.models.candle import Candle

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def make_candles(closes):
    return [
        Candle(
            symbol="BTC/USDT",
            timeframe="1h",
            timestamp=BASE + timedelta(hours=i),
            open=c - 0.05,
            high=c + 0.1,
            low=c - 0.1,
            close=c,
            volume=10.0,
        )
        for i, c in enumerate(closes)
    ]


# --- Reglas puras de decisión (docs/SDD.md §5.1), sin depender de pandas-ta ---


def test_trend_signal_bullish_cross_confirmed_by_macd():
    direction, confidence = AlphaEngine._trend_signal(
        prev_ema_fast=99, prev_ema_slow=100, ema_fast=101, ema_slow=100, macd_hist=0.5
    )
    assert (direction, confidence) == ("BUY", 1.0)


def test_trend_signal_bullish_cross_without_macd_confirmation():
    direction, confidence = AlphaEngine._trend_signal(
        prev_ema_fast=99, prev_ema_slow=100, ema_fast=101, ema_slow=100, macd_hist=-0.1
    )
    assert (direction, confidence) == ("BUY", 0.5)


def test_trend_signal_bearish_cross_confirmed_by_macd():
    direction, confidence = AlphaEngine._trend_signal(
        prev_ema_fast=101, prev_ema_slow=100, ema_fast=99, ema_slow=100, macd_hist=-0.5
    )
    assert (direction, confidence) == ("SELL", 1.0)


def test_trend_signal_no_cross_holds():
    direction, confidence = AlphaEngine._trend_signal(
        prev_ema_fast=101, prev_ema_slow=100, ema_fast=102, ema_slow=100, macd_hist=0.5
    )
    assert (direction, confidence) == ("HOLD", 0.0)


def test_mean_reversion_oversold_and_touching_lower_band():
    direction, confidence = AlphaEngine._mean_reversion_signal(rsi=20, close=95, bb_lower=96, bb_upper=110)
    assert (direction, confidence) == ("BUY", 1.0)


def test_mean_reversion_only_oversold_is_partial_confidence():
    direction, confidence = AlphaEngine._mean_reversion_signal(rsi=20, close=100, bb_lower=96, bb_upper=110)
    assert (direction, confidence) == ("BUY", 0.5)


def test_mean_reversion_overbought_and_touching_upper_band():
    direction, confidence = AlphaEngine._mean_reversion_signal(rsi=80, close=115, bb_lower=90, bb_upper=110)
    assert (direction, confidence) == ("SELL", 1.0)


def test_mean_reversion_neither_extreme_holds():
    direction, confidence = AlphaEngine._mean_reversion_signal(rsi=50, close=100, bb_lower=90, bb_upper=110)
    assert (direction, confidence) == ("HOLD", 0.0)


# --- Filtro de tendencia macro (EMA-200): agregado tras evidencia real de backtest ---
# (specs/003-alpha-engine/tasks.md) — no operar en contra de la tendencia de largo plazo.


def test_macro_trend_filter_blocks_buy_below_trend():
    direction, confidence = AlphaEngine._align_with_macro_trend("BUY", 1.0, close=95, ema_trend=100)
    assert (direction, confidence) == ("HOLD", 0.0)


def test_macro_trend_filter_blocks_sell_above_trend():
    direction, confidence = AlphaEngine._align_with_macro_trend("SELL", 1.0, close=105, ema_trend=100)
    assert (direction, confidence) == ("HOLD", 0.0)


def test_macro_trend_filter_allows_buy_above_trend():
    direction, confidence = AlphaEngine._align_with_macro_trend("BUY", 1.0, close=105, ema_trend=100)
    assert (direction, confidence) == ("BUY", 1.0)


def test_macro_trend_filter_allows_sell_below_trend():
    direction, confidence = AlphaEngine._align_with_macro_trend("SELL", 1.0, close=95, ema_trend=100)
    assert (direction, confidence) == ("SELL", 1.0)


def test_macro_trend_filter_passes_hold_through_unchanged():
    direction, confidence = AlphaEngine._align_with_macro_trend("HOLD", 0.0, close=95, ema_trend=100)
    assert (direction, confidence) == ("HOLD", 0.0)


# --- Insuficientes datos: HOLD explícito, nunca excepción (spec 003, requisito 5) ---


def test_evaluate_returns_hold_with_insufficient_history():
    candles = make_candles([100.0] * 10)
    signal = AlphaEngine().evaluate(candles)
    assert signal.direction == "HOLD"
    assert signal.confidence == 0.0


# --- Integración de punta a punta con pandas-ta real, sobre datos sintéticos ---
# Cada escenario fue verificado manualmente inspeccionando ADX/EMA/RSI/Bollinger/EMA-200
# antes de fijar los parámetros exactos, para no depender de coincidencias numéricas
# frágiles. Con el filtro de tendencia macro (EMA-200), el warm-up mínimo subió a 214
# velas (docs: MIN_CANDLES_FOR_INDICATORS) — los fixtures son más largos que antes.


def test_evaluate_fires_buy_on_bullish_cross_in_clear_uptrend():
    flat = [100.0] * 250
    trend = list(100 + np.arange(1, 41) * 0.8)
    candles = make_candles(flat + trend)

    # Justo antes de que termine el tramo plano: EMA20 == EMA50, sin cruce todavía.
    assert AlphaEngine().evaluate(candles[:250]).direction == "HOLD"

    # Primer vela de tendencia: aquí ocurre el cruce alcista con ADX ya alto y MACD
    # positivo, y el precio ya está por encima de la EMA-200 (que sigue ~100 tras el
    # tramo plano) — pasa también el filtro de tendencia macro.
    signal = AlphaEngine().evaluate(candles[:251])
    assert signal.direction == "BUY"
    assert signal.confidence == 1.0


def test_evaluate_fires_buy_on_oversold_dip_within_aligned_uptrend():
    # Tendencia de fondo alcista (drift + ruido iid dominante para que ADX local se
    # mantenga bajo) seguida de una caída puntual que toca sobreventa/banda inferior
    # sin perforar la EMA-200 — exactamente el caso que el filtro de tendencia macro
    # debe permitir (comprar el retroceso dentro de una tendencia alcista de fondo).
    rng = np.random.default_rng(11)
    n_base = 500
    base_series = 100 + 0.3 * np.arange(n_base) + rng.normal(0, 2.0, n_base)
    closes = np.concatenate([base_series, [base_series[-1] - 28]])
    candles = make_candles(closes)

    signal = AlphaEngine().evaluate(candles)
    assert signal.direction == "BUY"
    assert signal.confidence == 1.0


def test_evaluate_fires_sell_on_overbought_spike_within_aligned_downtrend():
    # Simétrico: tendencia de fondo bajista + repunte puntual que toca sobrecompra/banda
    # superior sin cruzar por encima de la EMA-200.
    rng = np.random.default_rng(13)
    n_base = 500
    base_series = 300 - 0.3 * np.arange(n_base) + rng.normal(0, 2.0, n_base)
    closes = np.concatenate([base_series, [base_series[-1] + 25]])
    candles = make_candles(closes)

    signal = AlphaEngine().evaluate(candles)
    assert signal.direction == "SELL"
    assert signal.confidence == 1.0


def test_macro_trend_filter_blocks_dip_buy_when_price_already_below_trend():
    # Mismo tipo de caída que el test anterior, pero sin la tendencia de fondo alcista
    # que la respalde: el precio ya está por debajo de su EMA-200 antes de la caída,
    # así que el filtro debe bloquear la compra aunque RSI/Bollinger se vean idénticos.
    rng = np.random.default_rng(1)
    baseline = 100 + rng.normal(0, 0.1, 250)
    closes = np.concatenate([baseline, [80.0]])
    candles = make_candles(closes)

    signal = AlphaEngine().evaluate(candles)
    assert signal.direction == "HOLD"


def test_evaluate_is_deterministic():
    flat = [100.0] * 250
    trend = list(100 + np.arange(1, 41) * 0.8)
    candles = make_candles(flat + trend)[:251]

    first = AlphaEngine().evaluate(candles)
    second = AlphaEngine().evaluate(candles)
    assert first == second


# --- enable_trend_following=False: agregado para validación walk-forward ---
# (specs/002-motor-backtesting/tasks.md: la rama tendencial arrastra el resultado)


def test_disabling_trend_following_holds_on_a_trend_signal():
    flat = [100.0] * 250
    trend = list(100 + np.arange(1, 41) * 0.8)
    candles = make_candles(flat + trend)[:251]

    with_trend = AlphaEngine(enable_trend_following=True).evaluate(candles)
    without_trend = AlphaEngine(enable_trend_following=False).evaluate(candles)

    assert with_trend.direction == "BUY"
    assert without_trend.direction == "HOLD"


def test_disabling_trend_following_does_not_affect_mean_reversion_signals():
    rng = np.random.default_rng(11)
    n_base = 500
    base_series = 100 + 0.3 * np.arange(n_base) + rng.normal(0, 2.0, n_base)
    closes = np.concatenate([base_series, [base_series[-1] - 28]])
    candles = make_candles(closes)

    with_trend = AlphaEngine(enable_trend_following=True).evaluate(candles)
    without_trend = AlphaEngine(enable_trend_following=False).evaluate(candles)

    assert with_trend.direction == without_trend.direction == "BUY"
