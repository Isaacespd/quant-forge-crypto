import pandas as pd

from trading_engine.alpha.indicators import MIN_CANDLES_FOR_TREND_ONLY, candles_to_frame, compute_trend
from trading_engine.models.candle import Candle
from trading_engine.models.signal import Signal


class SimpleTrendAlphaEngine:
    """Estrategia trivial de piso de comparación: `BUY` si el precio está claramente
    sobre su EMA-200, `SELL` si está claramente debajo, `HOLD` en la banda intermedia
    — sin RSI, sin Bollinger, sin filtro de régimen ADX.

    Motivada por evidencia real (specs/002-motor-backtesting/tasks.md): en 8.6 años de
    backtest real, comprar-y-mantener superó ampliamente a la estrategia con reglas más
    sofisticadas, y el único componente que consistentemente ayudó fue el filtro de
    tendencia macro. Esta clase aísla esa única señal para medirla contra buy-and-hold
    directamente, sin el ruido de RSI/Bollinger que generaba entradas/salidas prematuras.

    Banda de histéresis dinámica (ATR), no un % fijo: **sin banda, comparar precio vs.
    EMA vela a vela genera miles de cruces triviales** — cada uno paga comisión de
    entrada y salida. Confirmado con evidencia real: la primera versión sin banda generó
    ~2,700-4,500 operaciones en 8.6 años y destruyó 96-99% del capital, pese a que la
    dirección elegida era casi siempre correcta (profit factor cercano a 1) — el costo
    por volumen de operaciones, no la dirección, fue lo que perdió.

    Un `buffer_pct` fijo tampoco sirve: **confirmado empíricamente que un 8% funcionaba
    razonablemente en BTC (profit factor 1.07) pero no en ETH (profit factor <1 en todo
    el rango probado)** — activos distintos tienen volatilidad intrínseca distinta, y un
    porcentaje fijo no se ajusta a eso. La banda ahora se define como `ema_trend ± k×ATR`:
    se ensancha sola en activos/períodos más volátiles (evita whipsaw) y se angosta en
    los más tranquilos (no pierde el arranque de una tendencia real).

    Pensada para usarse con `BacktestEngine(exit_on_opposite_signal=True)` — de otra
    forma nunca podría salir de una posición salvo por stop-loss, contradiciendo el
    propósito de "seguir la tendencia mientras dure".
    """

    def __init__(self, strategy_id: str = "simple_trend_v1", k: float = 2.0):
        self.strategy_id = strategy_id
        self.k = k

    def evaluate(self, candles: list[Candle]) -> Signal:
        last_candle = candles[-1]

        if len(candles) < MIN_CANDLES_FOR_TREND_ONLY:
            return self._signal(last_candle, "HOLD", 0.0)

        df = candles_to_frame(candles)
        trend = compute_trend(df)
        last = trend.iloc[-1]

        if pd.isna(last["ema_trend"]) or pd.isna(last["atr"]):
            return self._signal(last_candle, "HOLD", 0.0)

        band = self.k * last["atr"]
        upper = last["ema_trend"] + band
        lower = last["ema_trend"] - band

        if last["close"] > upper:
            direction = "BUY"
        elif last["close"] < lower:
            direction = "SELL"
        else:
            direction = "HOLD"

        return self._signal(last_candle, direction, 1.0)

    def _signal(self, candle: Candle, direction: str, confidence: float) -> Signal:
        return Signal(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            direction=direction,
            confidence=confidence,
            timestamp=candle.timestamp,
            strategy_id=self.strategy_id,
        )
