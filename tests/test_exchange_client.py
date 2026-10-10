from datetime import datetime, timedelta, timezone

import pytest

import trading_engine.ingestion.exchange_client as exchange_client_module
from trading_engine.ingestion.exchange_client import ExchangeClient

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _ts_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class FakeExchange:
    """Simula un exchange real de ccxt: devuelve hasta `limit` velas con timestamp >= since."""

    def __init__(self, candles):
        self._candles = candles
        self.calls: list[int] = []

    def fetch_ohlcv(self, symbol, timeframe=None, since=None, limit=None):
        self.calls.append(since)
        remaining = [c for c in self._candles if c[0] >= since]
        return remaining[:limit]


class StaleExchange:
    """Simula un exchange roto que ignora `since` y siempre devuelve la misma vela vieja."""

    def __init__(self):
        self.calls = 0

    def fetch_ohlcv(self, symbol, timeframe=None, since=None, limit=None):
        self.calls += 1
        return [(0, 100.0, 110.0, 90.0, 105.0, 10.0)]


def _hourly_candles(n: int):
    return [
        (_ts_ms(BASE + timedelta(hours=i)), 100.0 + i, 110.0 + i, 90.0 + i, 105.0 + i, 10.0)
        for i in range(n)
    ]


def _install_fake_exchange(monkeypatch, fake):
    monkeypatch.setattr(exchange_client_module.ccxt, "binance", lambda config: fake, raising=False)


def test_unsupported_exchange_raises_value_error():
    with pytest.raises(ValueError):
        ExchangeClient("no_existe_este_exchange")


def test_unsupported_timeframe_raises_value_error(monkeypatch):
    _install_fake_exchange(monkeypatch, FakeExchange([]))
    client = ExchangeClient("binance")
    with pytest.raises(ValueError):
        client.fetch_ohlcv_range("BTC/USDT", "7m", since=BASE, until=BASE + timedelta(hours=1))


def test_fetch_paginates_across_multiple_pages(monkeypatch):
    fake = FakeExchange(_hourly_candles(10))
    _install_fake_exchange(monkeypatch, fake)
    client = ExchangeClient("binance")

    candles = client.fetch_ohlcv_range(
        "BTC/USDT", "1h", since=BASE, until=BASE + timedelta(hours=5), page_limit=2
    )

    assert [c.timestamp for c in candles] == [BASE + timedelta(hours=i) for i in range(5)]
    assert len(fake.calls) > 1  # confirma que sí paginó, no una sola llamada


def test_fetch_stops_on_empty_batch(monkeypatch):
    fake = FakeExchange([])
    _install_fake_exchange(monkeypatch, fake)
    client = ExchangeClient("binance")

    candles = client.fetch_ohlcv_range("BTC/USDT", "1h", since=BASE, until=BASE + timedelta(hours=5))

    assert candles == []
    assert len(fake.calls) == 1


def test_fetch_does_not_loop_forever_on_stale_exchange(monkeypatch):
    stale = StaleExchange()
    _install_fake_exchange(monkeypatch, stale)
    client = ExchangeClient("binance")

    candles = client.fetch_ohlcv_range(
        "BTC/USDT", "1h", since=BASE + timedelta(days=365), until=BASE + timedelta(days=366)
    )

    assert stale.calls == 1  # se detuvo tras la primera llamada en vez de repetir indefinidamente
