import statistics

from trading_engine.backtesting.broker_sim import BacktestTrade

MIN_TRADES_FOR_SIGNIFICANCE = 100


def sharpe_ratio(returns: list[float]) -> float:
    """Sharpe por operación (no anualizado) — media/desviación de los retornos por trade."""
    if len(returns) < 2:
        return 0.0
    stdev = statistics.pstdev(returns)
    if stdev == 0:
        return 0.0
    return statistics.mean(returns) / stdev


def sortino_ratio(returns: list[float]) -> float:
    """Sortino por operación: media / desviación a la baja (target=0), sobre todos los retornos."""
    if not returns:
        return 0.0
    downside_deviation = (sum(min(r, 0.0) ** 2 for r in returns) / len(returns)) ** 0.5
    if downside_deviation == 0:
        return 0.0
    return statistics.mean(returns) / downside_deviation


def max_drawdown(equity_values: list[float]) -> float:
    """Máximo drawdown pico-a-valle, como fracción negativa (ej. -0.15 = -15%)."""
    if not equity_values:
        return 0.0

    peak = equity_values[0]
    worst = 0.0
    for value in equity_values:
        peak = max(peak, value)
        drawdown = (value - peak) / peak if peak else 0.0
        worst = min(worst, drawdown)
    return worst


def win_rate(trades: list[BacktestTrade]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return wins / len(trades)


def profit_factor(trades: list[BacktestTrade]) -> float:
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def expectancy(trades: list[BacktestTrade]) -> float:
    if not trades:
        return 0.0
    return statistics.mean(t.pnl for t in trades)


def significance_warning(trade_count: int) -> str | None:
    """docs/SDD.md §5.4: desconfiar de estrategias con pocas operaciones en el backtest."""
    if trade_count < MIN_TRADES_FOR_SIGNIFICANCE:
        return (
            f"Solo {trade_count} operaciones (< {MIN_TRADES_FOR_SIGNIFICANCE}): "
            "resultado sin significancia estadística confiable."
        )
    return None


def compute_metrics(trades: list[BacktestTrade], equity_curve: list[float]) -> dict:
    returns = [t.pnl / (t.entry_price * t.size) for t in trades]
    warning = significance_warning(len(trades))

    return {
        "trade_count": len(trades),
        "sharpe_ratio": sharpe_ratio(returns),
        "sortino_ratio": sortino_ratio(returns),
        "max_drawdown": max_drawdown(equity_curve),
        "win_rate": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "expectancy": expectancy(trades),
        "warnings": [warning] if warning else [],
    }
