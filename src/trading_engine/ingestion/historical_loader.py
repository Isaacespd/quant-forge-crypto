from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert

from trading_engine.db.schema import OHLCV
from trading_engine.db.session import get_session
from trading_engine.ingestion.exchange_client import ExchangeClient
from trading_engine.models.candle import CandleSeriesError, validate_candle_series

# Postgres limita cada statement a 65535 parámetros. OHLCV tiene 8 columnas, así que
# el máximo teórico son 8191 filas por INSERT; se deja margen amplio para no rozarlo.
INSERT_BATCH_SIZE = 5000


def load_historical_ohlcv(
    exchange_id: str,
    symbol: str,
    timeframe: str,
    since: datetime,
    until: datetime,
) -> int:
    """Descarga, valida y persiste (idempotente) el histórico OHLCV de un símbolo/timeframe.

    Devuelve el número de velas descargadas y validadas (no necesariamente insertadas,
    ya que velas ya existentes se ignoran vía ON CONFLICT DO NOTHING).
    """
    client = ExchangeClient(exchange_id)
    candles = client.fetch_ohlcv_range(symbol, timeframe, since, until)
    validate_candle_series(candles, timeframe)

    if not candles:
        return 0

    with get_session() as session:
        for i in range(0, len(candles), INSERT_BATCH_SIZE):
            batch = candles[i : i + INSERT_BATCH_SIZE]
            stmt = pg_insert(OHLCV).values([c.model_dump() for c in batch])
            stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "timeframe", "timestamp"])
            session.execute(stmt)
        session.commit()

    return len(candles)


@dataclass
class SkippedRange:
    since: datetime
    until: datetime
    reason: str


def load_historical_ohlcv_resilient(
    exchange_id: str,
    symbol: str,
    timeframe: str,
    since: datetime,
    until: datetime,
    chunk_days: int = 30,
    min_chunk_hours: int = 6,
) -> tuple[int, list[SkippedRange]]:
    """Igual que `load_historical_ohlcv`, pero descarga en tramos de `chunk_days` para
    aislar huecos reales del exchange (ej. una caída de Binance) en vez de descartar
    todo el histórico solicitado por un solo tramo inválido.

    Descubierto al intentar bajar histórico desde 2018: Binance tiene varios huecos reales
    de pocas horas a lo largo de los años (probablemente caídas del exchange) — con la
    descarga en un solo bloque, cada hueco invalidaba años de datos por lo demás buenos.

    Cuando un tramo falla, se **subdivide a la mitad recursivamente** en vez de
    descartarse entero — así una interrupción de 2 horas solo tira esas horas, no los
    `chunk_days` completos alrededor. La recursión para en `min_chunk_hours`: un tramo
    tan chico que sigue fallando se da por perdido y se registra en `skipped`.

    Devuelve `(velas_insertadas, tramos_omitidos)` — cada tramo omitido queda registrado
    con su rango y motivo para poder decidir si vale la pena rellenarlo manualmente.
    """
    total_inserted = 0
    skipped: list[SkippedRange] = []

    def process(chunk_since: datetime, chunk_until: datetime) -> None:
        nonlocal total_inserted
        try:
            total_inserted += load_historical_ohlcv(exchange_id, symbol, timeframe, chunk_since, chunk_until)
        except CandleSeriesError as exc:
            span = chunk_until - chunk_since
            if span <= timedelta(hours=min_chunk_hours):
                skipped.append(SkippedRange(since=chunk_since, until=chunk_until, reason=str(exc)))
                return
            midpoint = chunk_since + span / 2
            process(chunk_since, midpoint)
            process(midpoint, chunk_until)

    chunk_start = since
    while chunk_start < until:
        chunk_end = min(chunk_start + timedelta(days=chunk_days), until)
        process(chunk_start, chunk_end)
        chunk_start = chunk_end

    return total_inserted, skipped
