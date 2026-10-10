import argparse
from datetime import datetime, timezone

from dotenv import load_dotenv

from trading_engine.ingestion.historical_loader import load_historical_ohlcv_resilient


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Descarga histórico OHLCV y lo persiste en TimescaleDB")
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--symbol", required=True, help="Ej. BTC/USDT")
    parser.add_argument("--timeframe", required=True, help="Ej. 1h, 1m")
    parser.add_argument("--since", required=True, type=_parse_date, help="AAAA-MM-DD")
    parser.add_argument("--until", required=True, type=_parse_date, help="AAAA-MM-DD")
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=30,
        help="Tamaño del tramo de descarga; un tramo con un hueco real del exchange se subdivide en vez de descartarse entero",
    )
    parser.add_argument(
        "--min-chunk-hours",
        type=int,
        default=6,
        help="Piso de la subdivisión recursiva: un tramo tan chico que sigue fallando se da por perdido",
    )
    args = parser.parse_args()

    n, skipped = load_historical_ohlcv_resilient(
        exchange_id=args.exchange,
        symbol=args.symbol,
        timeframe=args.timeframe,
        since=args.since,
        until=args.until,
        chunk_days=args.chunk_days,
        min_chunk_hours=args.min_chunk_hours,
    )
    print(f"{n} velas descargadas y validadas para {args.symbol} ({args.timeframe})")

    if skipped:
        print(f"{len(skipped)} tramo(s) irrecuperable(s) — huecos reales del exchange:")
        for s in skipped:
            print(f"  - {s.since} a {s.until}: {s.reason}")


if __name__ == "__main__":
    main()
