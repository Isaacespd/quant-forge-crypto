from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


@dataclass
class OpenBacktestPosition:
    symbol: str
    direction: Literal["BUY", "SELL"]
    entry_price: float
    size: float
    stop_loss: float
    risk_pct: float
    opened_at: datetime
    trail_distance: float
    capped: bool = False


class BacktestTrade(BaseModel):
    symbol: str
    direction: Literal["BUY", "SELL"]
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    opened_at: datetime
    closed_at: datetime
    risk_pct: float = 0.01
    # True si RiskEngine recortó el tamaño por `max_notional_pct` — sin esto, un trade
    # capado (con menos riesgo real que el `risk_pct` nominal) es indistinguible de uno
    # sin capar al revisar pnl/expectancy, y un análisis posterior podría malinterpretar
    # "ganó menos" como "perdió edge" cuando en realidad arriesgó menos a propósito.
    capped: bool = False


class SimulatedBroker:
    """Contabilidad del backtest: aplica comisión/slippage a cada fill y mantiene
    equity + posición abierta (docs/SDD.md §3.B, spec 002).

    Simplificación deliberada de este MVP (ver plan.md): una sola posición abierta
    a la vez, sobre un solo símbolo — mientras hay posición abierta, el motor no
    evalúa nuevas señales de entrada, solo vigila el stop-loss.
    """

    def __init__(self, initial_equity: float, commission_pct: float = 0.001, slippage_pct: float = 0.0005):
        self.equity = initial_equity
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct

        self.position: OpenBacktestPosition | None = None
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[tuple[datetime, float]] = []

        self._all_time_peak_equity = initial_equity
        self._month_start_equity = initial_equity
        self._day_start_equity = initial_equity
        self._current_month: tuple[int, int] | None = None
        self._current_day = None

    def is_flat(self) -> bool:
        return self.position is None

    def mark_period(self, timestamp: datetime) -> None:
        """Actualiza los anclas de drawdown mensual/diario si cambió el período calendario."""
        month_key = (timestamp.year, timestamp.month)
        if self._current_month != month_key:
            self._current_month = month_key
            self._month_start_equity = self.equity

        day_key = timestamp.date()
        if self._current_day != day_key:
            self._current_day = day_key
            self._day_start_equity = self.equity

    def drawdown_snapshot(self) -> tuple[float, float, float]:
        """(monthly_drawdown_pct, cumulative_drawdown_pct, daily_loss_pct), como fracciones negativas."""
        self._all_time_peak_equity = max(self._all_time_peak_equity, self.equity)
        cumulative = (self.equity - self._all_time_peak_equity) / self._all_time_peak_equity
        monthly = (self.equity - self._month_start_equity) / self._month_start_equity
        daily = (self.equity - self._day_start_equity) / self._day_start_equity
        return monthly, cumulative, daily

    def reset_drawdown_peak(self) -> None:
        """Resetea el pico de referencia del drawdown acumulado a la equity actual.

        Simula que un humano revisó la caída y decidió continuar con el capital que
        queda (docs/SDD.md §5.3: el circuit breaker de drawdown acumulado bloquea
        "hasta revisión manual"). Sin esto, en un backtest sin humano el breaker nunca
        se libera solo una vez cruzado el umbral: sin operaciones nuevas la equity
        queda congelada, y sin que la equity cambie el drawdown nunca mejora — un
        candado que se cierra solo y no tiene llave (bug real encontrado corriendo
        8.6 años de historia real, ver specs/002-motor-backtesting/tasks.md).
        """
        self._all_time_peak_equity = self.equity

    def open_position(
        self,
        symbol: str,
        direction: Literal["BUY", "SELL"],
        price: float,
        size: float,
        stop_loss: float,
        risk_pct: float,
        timestamp: datetime,
        capped: bool = False,
    ) -> None:
        if self.position is not None:
            raise RuntimeError("Ya hay una posición abierta — este broker simulado no soporta pirámides")

        fill_price = price * (1 + self.slippage_pct) if direction == "BUY" else price * (1 - self.slippage_pct)
        commission = fill_price * size * self.commission_pct
        self.equity -= commission

        self.position = OpenBacktestPosition(
            symbol=symbol,
            direction=direction,
            entry_price=fill_price,
            size=size,
            stop_loss=stop_loss,
            risk_pct=risk_pct,
            opened_at=timestamp,
            trail_distance=abs(fill_price - stop_loss),
            capped=capped,
        )
        self.equity_curve.append((timestamp, self.equity))

    def mark_to_market_equity(self, low: float, high: float) -> float:
        """Equity si la posición abierta se liquidara al precio más adverso de esta vela
        (`low` para BUY, `high` para SELL) — no muta nada, es solo una lectura.

        Sin esto, el drawdown máximo solo se medía sobre equity realizada al abrir/cerrar
        operaciones (`plan.md`, limitación conocida desde el inicio de esta spec): una
        posición podía estar profundamente en pérdida *dentro* de una operación sin que
        quedara reflejado, porque el precio nunca tocó el stop. Esto se usa para construir
        una curva de equity más fina, solo para el cálculo de `max_drawdown` — la equity
        real (`self.equity`) no cambia hasta que la posición efectivamente se cierra.
        """
        if self.position is None:
            return self.equity

        adverse_price = low if self.position.direction == "BUY" else high
        if self.position.direction == "BUY":
            unrealized = (adverse_price - self.position.entry_price) * self.position.size
        else:
            unrealized = (self.position.entry_price - adverse_price) * self.position.size
        return self.equity + unrealized

    def stop_loss_hit(self, high: float, low: float) -> bool:
        if self.position is None:
            return False
        if self.position.direction == "BUY":
            return low <= self.position.stop_loss
        return high >= self.position.stop_loss

    def update_trailing_stop(self, high: float, low: float) -> None:
        """Mueve el stop a favor de la posición, nunca en contra (docs: spec 002 plan.md,
        agregado tras evidencia real de backtest: un stop fijo sin trailing devuelve
        ganancias grandes como pérdidas cuando el precio eventualmente retrocede).
        """
        if self.position is None:
            return
        if self.position.direction == "BUY":
            candidate = high - self.position.trail_distance
            self.position.stop_loss = max(self.position.stop_loss, candidate)
        else:
            candidate = low + self.position.trail_distance
            self.position.stop_loss = min(self.position.stop_loss, candidate)

    def close_position(self, price: float, timestamp: datetime) -> BacktestTrade:
        if self.position is None:
            raise RuntimeError("No hay posición abierta para cerrar")

        position = self.position
        fill_price = price * (1 - self.slippage_pct) if position.direction == "BUY" else price * (1 + self.slippage_pct)
        commission = fill_price * position.size * self.commission_pct

        if position.direction == "BUY":
            pnl = (fill_price - position.entry_price) * position.size - commission
        else:
            pnl = (position.entry_price - fill_price) * position.size - commission

        self.equity += pnl

        trade = BacktestTrade(
            symbol=position.symbol,
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=fill_price,
            size=position.size,
            pnl=pnl,
            opened_at=position.opened_at,
            closed_at=timestamp,
            risk_pct=position.risk_pct,
            capped=position.capped,
        )
        self.trades.append(trade)
        self.equity_curve.append((timestamp, self.equity))
        self.position = None
        return trade
