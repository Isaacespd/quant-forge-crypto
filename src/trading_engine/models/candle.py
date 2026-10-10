from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, field_validator, model_validator

TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


class CandleSeriesError(ValueError):
    pass


class Candle(BaseModel):
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @field_validator("timeframe")
    @classmethod
    def timeframe_supported(cls, v: str) -> str:
        if v not in TIMEFRAME_SECONDS:
            raise ValueError(f"timeframe '{v}' no soportado, esperado uno de {list(TIMEFRAME_SECONDS)}")
        return v

    @field_validator("open", "high", "low", "close")
    @classmethod
    def price_must_be_positive(cls, v: float, info) -> float:
        if v <= 0:
            raise ValueError(f"{info.field_name} debe ser > 0, recibido {v}")
        return v

    @field_validator("volume")
    @classmethod
    def volume_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"volume debe ser >= 0, recibido {v}")
        return v

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_utc_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp debe incluir tzinfo (se espera UTC)")
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def ohlc_consistency(self) -> "Candle":
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) no puede ser menor que low ({self.low})")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"open ({self.open}) fuera de rango [low={self.low}, high={self.high}]")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"close ({self.close}) fuera de rango [low={self.low}, high={self.high}]")
        return self


def validate_candle_series(candles: list[Candle], timeframe: str) -> None:
    """Verifica orden cronológico estricto y ausencia de gaps para una serie de un mismo símbolo/timeframe."""
    if not candles:
        return

    expected_step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])

    for prev, curr in zip(candles, candles[1:]):
        if curr.timestamp <= prev.timestamp:
            raise CandleSeriesError(
                f"Timestamps no estrictamente ascendentes: {prev.timestamp} -> {curr.timestamp}"
            )
        gap = curr.timestamp - prev.timestamp
        if gap != expected_step:
            raise CandleSeriesError(
                f"Gap inesperado entre {prev.timestamp} y {curr.timestamp}: "
                f"esperado {expected_step}, encontrado {gap}"
            )
