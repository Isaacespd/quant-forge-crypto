from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id = Column(BigInteger, primary_key=True)
    strategy_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)
    since = Column(DateTime(timezone=True), nullable=False)
    until = Column(DateTime(timezone=True), nullable=False)
    initial_equity = Column(Float, nullable=False)
    params = Column(JSONB, nullable=False)  # RiskConfig + comisión/slippage usados en la corrida
    metrics = Column(JSONB, nullable=False)  # salida de backtesting.metrics.compute_metrics
    created_at = Column(DateTime(timezone=True), nullable=False)


class OHLCV(Base):
    __tablename__ = "ohlcv"

    # Sin id surrogate: TimescaleDB exige que la clave primaria de una hypertable
    # incluya la columna de partición (timestamp), así que la clave natural
    # (symbol, timeframe, timestamp) hace ese trabajo directamente.
    symbol = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("symbol", "timeframe", "timestamp", name="pk_ohlcv"),
    )


class Trade(Base):
    __tablename__ = "trades"

    id = Column(BigInteger, primary_key=True)
    run_id = Column(BigInteger, ForeignKey("backtest_runs.id"), nullable=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    size = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    opened_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    strategy_id = Column(String, nullable=False)
    pnl = Column(Float, nullable=True)


class Order(Base):
    __tablename__ = "orders"

    id = Column(BigInteger, primary_key=True)
    trade_id = Column(BigInteger, ForeignKey("trades.id"), nullable=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=True)
    status = Column(String, nullable=False, server_default="pending")
    broker_order_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    filled_at = Column(DateTime(timezone=True), nullable=True)


class AccountState(Base):
    __tablename__ = "account_state"

    id = Column(BigInteger, primary_key=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    equity = Column(Float, nullable=False)
    available_capital = Column(Float, nullable=False)
    open_risk_pct = Column(Float, nullable=False)
