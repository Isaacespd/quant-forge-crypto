from trading_engine.alpha.indicators import MIN_CANDLES_FOR_INDICATORS, candles_to_frame, compute_indicators
from trading_engine.models.candle import Candle
from trading_engine.models.signal import Signal

ADX_TREND_THRESHOLD = 20
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70


class AlphaEngine:
    """Filtro de régimen + estrategia tendencial/reversión de docs/SDD.md §5.1.

    No conoce capital ni tamaño de cuenta (docs/SDD.md §3.C) — solo emite Signal.
    """

    def __init__(self, strategy_id: str = "trend_regime_v1", enable_trend_following: bool = True):
        """`enable_trend_following=False` desactiva la rama de cruce EMA+MACD y opera solo
        reversión a la media (dentro del filtro de tendencia macro). Agregado para poder
        contrastar ambas ramas en validación walk-forward tras evidencia de que la rama
        tendencial es la que arrastra el resultado a negativo en backtests reales
        (ver specs/002-motor-backtesting/tasks.md).
        """
        self.strategy_id = strategy_id
        self.enable_trend_following = enable_trend_following

    def evaluate(self, candles: list[Candle]) -> Signal:
        last_candle = candles[-1]

        if len(candles) < MIN_CANDLES_FOR_INDICATORS:
            return self._signal(last_candle, "HOLD", 0.0)

        df = candles_to_frame(candles)
        indicators = compute_indicators(df)

        last = indicators.iloc[-1]
        prev = indicators.iloc[-2]

        if last.isna().any() or prev[["ema_fast", "ema_slow"]].isna().any():
            return self._signal(last_candle, "HOLD", 0.0)

        if last["adx"] > ADX_TREND_THRESHOLD:
            if self.enable_trend_following:
                direction, confidence = self._trend_signal(
                    prev_ema_fast=prev["ema_fast"],
                    prev_ema_slow=prev["ema_slow"],
                    ema_fast=last["ema_fast"],
                    ema_slow=last["ema_slow"],
                    macd_hist=last["macd_hist"],
                )
            else:
                direction, confidence = "HOLD", 0.0
        else:
            direction, confidence = self._mean_reversion_signal(
                rsi=last["rsi"],
                close=last["close"],
                bb_lower=last["bb_lower"],
                bb_upper=last["bb_upper"],
            )

        direction, confidence = self._align_with_macro_trend(
            direction, confidence, close=last["close"], ema_trend=last["ema_trend"]
        )

        return self._signal(last_candle, direction, confidence)

    def _signal(self, candle: Candle, direction: str, confidence: float) -> Signal:
        return Signal(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            direction=direction,
            confidence=confidence,
            timestamp=candle.timestamp,
            strategy_id=self.strategy_id,
        )

    @staticmethod
    def _trend_signal(
        prev_ema_fast: float, prev_ema_slow: float, ema_fast: float, ema_slow: float, macd_hist: float
    ) -> tuple[str, float]:
        bullish_cross = prev_ema_fast <= prev_ema_slow and ema_fast > ema_slow
        bearish_cross = prev_ema_fast >= prev_ema_slow and ema_fast < ema_slow

        if bullish_cross:
            return "BUY", 1.0 if macd_hist > 0 else 0.5
        if bearish_cross:
            return "SELL", 1.0 if macd_hist < 0 else 0.5
        return "HOLD", 0.0

    @staticmethod
    def _align_with_macro_trend(direction: str, confidence: float, close: float, ema_trend: float) -> tuple[str, float]:
        """Filtro de tendencia macro (EMA-200): no operar en contra de la tendencia de largo plazo.

        Agregado tras evidencia real de backtest (specs/003/tasks.md): la estrategia sin este
        filtro perdía sistemáticamente vendiendo en contra de una tendencia alcista sostenida,
        tanto en la rama tendencial como en la de reversión a la media.
        """
        if direction == "BUY" and close < ema_trend:
            return "HOLD", 0.0
        if direction == "SELL" and close > ema_trend:
            return "HOLD", 0.0
        return direction, confidence

    @staticmethod
    def _mean_reversion_signal(rsi: float, close: float, bb_lower: float, bb_upper: float) -> tuple[str, float]:
        oversold = rsi < RSI_OVERSOLD
        touching_lower_band = close <= bb_lower
        overbought = rsi > RSI_OVERBOUGHT
        touching_upper_band = close >= bb_upper

        if oversold and touching_lower_band:
            return "BUY", 1.0
        if oversold or touching_lower_band:
            return "BUY", 0.5
        if overbought and touching_upper_band:
            return "SELL", 1.0
        if overbought or touching_upper_band:
            return "SELL", 0.5
        return "HOLD", 0.0
