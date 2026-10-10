from datetime import datetime

from trading_engine.backtesting.engine import BacktestResult
from trading_engine.db.schema import BacktestRun, Trade
from trading_engine.db.session import get_session


def save_backtest_run(
    result: BacktestResult,
    strategy_id: str,
    symbol: str,
    timeframe: str,
    since: datetime,
    until: datetime,
    initial_equity: float,
    params: dict,
    run_timestamp: datetime,
) -> int:
    """Persiste el resultado de una corrida en `backtest_runs` + sus operaciones en `trades`.

    `run_timestamp` se recibe como parámetro (no `datetime.now()` interno) para que
    la función sea determinista y fácil de probar sin depender del reloj del sistema.
    """
    with get_session() as session:
        run = BacktestRun(
            strategy_id=strategy_id,
            symbol=symbol,
            timeframe=timeframe,
            since=since,
            until=until,
            initial_equity=initial_equity,
            params=params,
            metrics=result.metrics,
            created_at=run_timestamp,
        )
        session.add(run)
        session.flush()  # asigna run.id sin cerrar la transacción

        for trade in result.trades:
            session.add(
                Trade(
                    run_id=run.id,
                    symbol=trade.symbol,
                    side=trade.direction,
                    entry_price=trade.entry_price,
                    exit_price=trade.exit_price,
                    size=trade.size,
                    opened_at=trade.opened_at,
                    closed_at=trade.closed_at,
                    strategy_id=strategy_id,
                    pnl=trade.pnl,
                )
            )

        session.commit()
        return run.id
