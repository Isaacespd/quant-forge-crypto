from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import trading_engine.ingestion.historical_loader as loader_module
from trading_engine.models.candle import Candle, CandleSeriesError

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def make_candles(n: int):
    return [
        Candle(
            symbol="BTC/USDT",
            timeframe="1h",
            timestamp=BASE + timedelta(hours=i),
            open=100.0,
            high=110.0,
            low=90.0,
            close=105.0,
            volume=10.0,
        )
        for i in range(n)
    ]


class FakeExchangeClient:
    def __init__(self, candles):
        self._candles = candles

    def fetch_ohlcv_range(self, symbol, timeframe, since, until, page_limit=1000):
        return self._candles


def _patch_exchange_and_session(monkeypatch, candles):
    monkeypatch.setattr(loader_module, "ExchangeClient", lambda exchange_id: FakeExchangeClient(candles))
    fake_session = MagicMock()

    @contextmanager
    def fake_get_session():
        yield fake_session

    monkeypatch.setattr(loader_module, "get_session", fake_get_session)
    return fake_session


def test_load_historical_ohlcv_persists_validated_candles(monkeypatch):
    fake_session = _patch_exchange_and_session(monkeypatch, make_candles(5))

    n = loader_module.load_historical_ohlcv(
        exchange_id="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        since=BASE,
        until=BASE + timedelta(hours=5),
    )

    assert n == 5
    fake_session.execute.assert_called_once()
    fake_session.commit.assert_called_once()


def test_load_historical_ohlcv_returns_zero_when_no_candles(monkeypatch):
    fake_session = _patch_exchange_and_session(monkeypatch, [])

    n = loader_module.load_historical_ohlcv(
        exchange_id="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        since=BASE,
        until=BASE + timedelta(hours=5),
    )

    assert n == 0
    fake_session.execute.assert_not_called()
    fake_session.commit.assert_not_called()


def test_load_historical_ohlcv_rejects_invalid_series(monkeypatch):
    candles = make_candles(3)
    candles[1], candles[2] = candles[2], candles[1]  # rompe el orden cronológico
    fake_session = _patch_exchange_and_session(monkeypatch, candles)

    with pytest.raises(CandleSeriesError):
        loader_module.load_historical_ohlcv(
            exchange_id="binance",
            symbol="BTC/USDT",
            timeframe="1h",
            since=BASE,
            until=BASE + timedelta(hours=5),
        )

    fake_session.execute.assert_not_called()


def test_load_historical_ohlcv_batches_large_inserts(monkeypatch):
    # Postgres limita a 65535 parámetros por statement; con 8 columnas eso son ~8191
    # filas por INSERT. Se fuerza un batch pequeño para probar el chunking sin
    # tener que generar decenas de miles de velas reales en el test.
    monkeypatch.setattr(loader_module, "INSERT_BATCH_SIZE", 2)
    fake_session = _patch_exchange_and_session(monkeypatch, make_candles(5))

    n = loader_module.load_historical_ohlcv(
        exchange_id="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        since=BASE,
        until=BASE + timedelta(hours=5),
    )

    assert n == 5
    assert fake_session.execute.call_count == 3  # ceil(5 / 2)
    fake_session.commit.assert_called_once()


# --- load_historical_ohlcv_resilient: aísla huecos reales del exchange por tramo ---
# (descubierto al bajar histórico desde 2018: Binance tiene un hueco real de 1h el
# 2018-01-04, que invalidaba años de datos por lo demás buenos en un solo bloque)


def test_resilient_load_sums_all_chunks_when_none_fail(monkeypatch):
    calls = []

    def fake_load(exchange_id, symbol, timeframe, since, until):
        calls.append((since, until))
        return 10

    monkeypatch.setattr(loader_module, "load_historical_ohlcv", fake_load)

    total, skipped = loader_module.load_historical_ohlcv_resilient(
        exchange_id="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        since=BASE,
        until=BASE + timedelta(days=10),
        chunk_days=3,
    )

    assert total == 40  # 4 tramos (3+3+3+1 días) * 10 velas
    assert skipped == []
    assert len(calls) == 4


def test_resilient_load_skips_failing_chunk_and_continues(monkeypatch):
    def fake_load(exchange_id, symbol, timeframe, since, until):
        if since == BASE + timedelta(days=3):
            raise CandleSeriesError("hueco simulado")
        return 5

    monkeypatch.setattr(loader_module, "load_historical_ohlcv", fake_load)

    # min_chunk_hours = chunk_days completo, en horas: desactiva la subdivisión
    # recursiva (probada aparte) para verificar aquí solo el "saltar y continuar".
    total, skipped = loader_module.load_historical_ohlcv_resilient(
        exchange_id="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        since=BASE,
        until=BASE + timedelta(days=10),
        chunk_days=3,
        min_chunk_hours=3 * 24,
    )

    assert total == 15  # 3 tramos exitosos * 5 velas (el 4to fue omitido, no hay 4to fallido aqui)
    assert len(skipped) == 1
    assert skipped[0].since == BASE + timedelta(days=3)
    assert skipped[0].until == BASE + timedelta(days=6)
    assert "hueco simulado" in skipped[0].reason


def test_resilient_load_recursively_splits_failing_chunk_instead_of_discarding_it_whole(monkeypatch):
    bad_moment = BASE + timedelta(hours=40)

    def fake_load(exchange_id, symbol, timeframe, since, until):
        if since <= bad_moment < until:
            raise CandleSeriesError("hueco simulado")
        return 1

    monkeypatch.setattr(loader_module, "load_historical_ohlcv", fake_load)

    total, skipped = loader_module.load_historical_ohlcv_resilient(
        exchange_id="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        since=BASE,
        until=BASE + timedelta(days=3),
        chunk_days=3,
        min_chunk_hours=6,
    )

    # Solo se pierde el tramo mínimo alrededor del hueco, no los 3 días completos.
    assert len(skipped) == 1
    assert skipped[0].until - skipped[0].since <= timedelta(hours=6)
    assert skipped[0].since <= bad_moment < skipped[0].until
    assert total > 0  # el resto de los 3 días sí se recuperó
