import pandas as pd
import pandas_ta as ta  # noqa: F401 -- registra el accessor .ta en los DataFrame

from trading_engine.models.candle import Candle

EMA_FAST_LENGTH = 20
EMA_SLOW_LENGTH = 50
EMA_TREND_LENGTH = 200  # filtro de tendencia macro (ver docs/SDD.md §5.1 y specs/003 plan.md)
ADX_LENGTH = 14
RSI_LENGTH = 14
BBANDS_LENGTH = 20
BBANDS_STD = 2.0
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
ATR_LENGTH = 14  # usado por Risk Engine para sizing (docs/SDD.md §5.2), no por Alpha Engine

# Warm-up mínimo para que ADX/EMA lenta/EMA de tendencia produzcan valores no-NaN
# (no implica que estén plenamente convergidas — eso depende de cuánta historia
# real se les entregue, ver BacktestEngine.ALPHA_LOOKBACK_WINDOW).
MIN_CANDLES_FOR_INDICATORS = EMA_TREND_LENGTH + ADX_LENGTH

# Solo para SimpleTrendAlphaEngine, que únicamente necesita EMA-200 (no ADX/RSI/Bollinger).
MIN_CANDLES_FOR_TREND_ONLY = EMA_TREND_LENGTH


def candles_to_frame(candles: list[Candle]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        },
        index=[c.timestamp for c in candles],
    )


def _column_starting_with(frame: pd.DataFrame, prefix: str) -> pd.Series:
    matches = [c for c in frame.columns if c.startswith(prefix)]
    if not matches:
        raise KeyError(f"No se encontró columna con prefijo '{prefix}' en {frame.columns.tolist()}")
    return frame[matches[0]]


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula los indicadores de la estrategia de docs/SDD.md §5.1 sobre un DataFrame OHLCV."""
    out = pd.DataFrame(index=df.index)
    out["close"] = df["close"]
    out["ema_fast"] = df.ta.ema(length=EMA_FAST_LENGTH)
    out["ema_slow"] = df.ta.ema(length=EMA_SLOW_LENGTH)
    out["ema_trend"] = df.ta.ema(length=EMA_TREND_LENGTH)

    adx = df.ta.adx(length=ADX_LENGTH)
    out["adx"] = _column_starting_with(adx, f"ADX_{ADX_LENGTH}")

    out["rsi"] = df.ta.rsi(length=RSI_LENGTH)

    bbands = df.ta.bbands(length=BBANDS_LENGTH, std=BBANDS_STD)
    out["bb_lower"] = _column_starting_with(bbands, "BBL_")
    out["bb_upper"] = _column_starting_with(bbands, "BBU_")

    macd = df.ta.macd(fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    out["macd_hist"] = _column_starting_with(macd, "MACDh_")

    out["atr"] = df.ta.atr(length=ATR_LENGTH, mamode="rma")

    return out


def compute_atr(df: pd.DataFrame) -> pd.Series:
    """ATR(14) standalone — lo consume Risk Engine (vía Motor de Backtesting) para sizing,
    y `SimpleTrendAlphaEngine` para la banda de histéresis dinámica (ver plan.md de spec 002).

    `mamode="rma"` fuerza explícitamente el suavizado original de Wilder (Running Moving
    Average) — es el default real de `pandas-ta` para ATR, pero se fija sin ambigüedad
    para no depender de un default implícito de la librería que podría cambiar.
    """
    return df.ta.atr(length=ATR_LENGTH, mamode="rma")


def compute_trend(df: pd.DataFrame) -> pd.DataFrame:
    """EMA-200 + ATR-14 — usado por `SimpleTrendAlphaEngine`. Deliberadamente liviano (dos
    indicadores en vez de los 6+ de `compute_indicators`): motivado por evidencia real de
    backtest (specs/002-motor-backtesting/tasks.md) — RSI/Bollinger/ADX generaban el ruido
    que hacía perder a la estrategia original frente a simplemente seguir la tendencia.

    El ATR se incluye para la banda de histéresis dinámica (`upper = ema_trend + k*atr`,
    `lower = ema_trend - k*atr`) — un buffer fijo en % no se ajusta a que activos distintos
    tienen volatilidad intrínseca distinta (confirmado empíricamente: 8% funcionaba bien en
    BTC pero no en ETH, ver tasks.md).
    """
    out = pd.DataFrame(index=df.index)
    out["close"] = df["close"]
    out["ema_trend"] = df.ta.ema(length=EMA_TREND_LENGTH)
    out["atr"] = df.ta.atr(length=ATR_LENGTH, mamode="rma")
    return out
