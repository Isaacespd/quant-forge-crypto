from datetime import datetime, timezone

import ccxt

from trading_engine.models.candle import Candle, TIMEFRAME_SECONDS


class ExchangeClient:
    """Cliente de solo lectura para histórico OHLCV, vía ccxt (multi-exchange)."""

    def __init__(self, exchange_id: str = "binance"):
        try:
            exchange_class = getattr(ccxt, exchange_id)
        except AttributeError as exc:
            raise ValueError(f"Exchange '{exchange_id}' no soportado por ccxt") from exc
        self.exchange = exchange_class({"enableRateLimit": True})

    def fetch_ohlcv_range(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        until: datetime,
        page_limit: int = 1000,
    ) -> list[Candle]:
        """Descarga todas las velas de [since, until) paginando la API del exchange."""
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"timeframe '{timeframe}' no soportado, esperado uno de {list(TIMEFRAME_SECONDS)}")

        candles: list[Candle] = []
        since_ms = int(since.timestamp() * 1000)
        until_ms = int(until.timestamp() * 1000)

        while since_ms < until_ms:
            batch = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=page_limit)
            if not batch:
                break

            for ts, o, h, l, c, v in batch:
                if ts >= until_ms:
                    break
                candles.append(
                    Candle(
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                        open=o,
                        high=h,
                        low=l,
                        close=c,
                        volume=v,
                    )
                )

            last_ts = batch[-1][0]
            if last_ts < since_ms:
                # El exchange no avanzó; evita loop infinito.
                break
            since_ms = last_ts + 1

        return candles
