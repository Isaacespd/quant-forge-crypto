from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from trading_engine.backtesting.broker_sim import BacktestTrade
from trading_engine.backtesting.metrics import compute_metrics
from trading_engine.models.candle import Candle


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: int
    train_end: int  # exclusivo
    test_start: int
    test_end: int  # exclusivo


@dataclass
class WalkForwardResult:
    window: WalkForwardWindow
    test_start_timestamp: datetime
    test_end_timestamp: datetime
    trades: list[BacktestTrade]
    metrics: dict


def generate_walk_forward_windows(
    n_candles: int, train_size: int, test_size: int, step: int
) -> list[WalkForwardWindow]:
    """Partición walk-forward (docs/SDD.md §5.4 / spec 002): ventana de entrenamiento
    seguida inmediatamente por su ventana de validación, deslizando `step` velas.

    `test_start` de una ventana es siempre igual a `train_end` de esa misma ventana —
    la validación nunca usa datos anteriores a donde termina su propio entrenamiento,
    ni dejan hueco entre ambas.
    """
    if train_size <= 0 or test_size <= 0 or step <= 0:
        raise ValueError("train_size, test_size y step deben ser > 0")

    windows = []
    train_start = 0
    while train_start + train_size + test_size <= n_candles:
        train_end = train_start + train_size
        test_end = train_end + test_size
        windows.append(WalkForwardWindow(train_start, train_end, train_end, test_end))
        train_start += step
    return windows


def evaluate_walk_forward(
    candles: list[Candle],
    windows: list[WalkForwardWindow],
    engine_factory: Callable[[], object],
    initial_equity: float = 100_000.0,
) -> list[WalkForwardResult]:
    """Corre una corrida de backtest independiente por ventana y reporta métricas
    calculadas SOLO sobre las operaciones que abrieron dentro de la porción de test.

    Alpha Engine no expone parámetros ajustables (`specs/002-motor-backtesting/plan.md`),
    así que aquí no hay una etapa de "optimizar en train" — el tramo de `train` solo se
    incluye como historia previa necesaria para que los indicadores (EMA-200, ADX, etc.)
    ya estén convergidos al llegar a la porción de `test`. Lo que sí se logra es lo
    esencial de walk-forward: cada ventana de test es un tramo fuera de muestra distinto,
    evaluado con el mismo motor determinista — permite ver si un resultado se sostiene en
    varios períodos o si es específico de uno solo.

    `engine_factory` se llama una vez por ventana (debe devolver una instancia nueva de
    `BacktestEngine`, sin estado compartido entre ventanas).
    """
    results = []
    for window in windows:
        window_candles = candles[window.train_start : window.test_end]
        test_start_timestamp = candles[window.test_start].timestamp
        test_end_timestamp = candles[window.test_end - 1].timestamp

        engine = engine_factory()
        result = engine.run(window_candles)

        test_trades = [t for t in result.trades if t.opened_at >= test_start_timestamp]

        equity_curve = [initial_equity]
        running_equity = initial_equity
        for trade in test_trades:
            running_equity += trade.pnl
            equity_curve.append(running_equity)

        results.append(
            WalkForwardResult(
                window=window,
                test_start_timestamp=test_start_timestamp,
                test_end_timestamp=test_end_timestamp,
                trades=test_trades,
                metrics=compute_metrics(test_trades, equity_curve),
            )
        )
    return results
