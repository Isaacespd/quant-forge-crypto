"""esquema inicial: ohlcv (hypertable), trades, orders, account_state + continuous aggregate 1h

Revision ID: 0001
Revises:
Create Date: 2026-07-29

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "ohlcv",
        # Sin id surrogate: create_hypertable exige que toda clave primaria/unique
        # incluya la columna de partición ('timestamp'); la clave natural la cubre.
        sa.Column("symbol", sa.String, nullable=False),
        sa.Column("timeframe", sa.String, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float, nullable=False),
        sa.Column("high", sa.Float, nullable=False),
        sa.Column("low", sa.Float, nullable=False),
        sa.Column("close", sa.Float, nullable=False),
        sa.Column("volume", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("symbol", "timeframe", "timestamp", name="pk_ohlcv"),
    )
    op.execute("SELECT create_hypertable('ohlcv', 'timestamp', if_not_exists => TRUE)")

    op.create_table(
        "trades",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("symbol", sa.String, nullable=False),
        sa.Column("side", sa.String, nullable=False),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("exit_price", sa.Float, nullable=True),
        sa.Column("size", sa.Float, nullable=False),
        sa.Column("stop_loss", sa.Float, nullable=True),
        sa.Column("take_profit", sa.Float, nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("strategy_id", sa.String, nullable=False),
        sa.Column("pnl", sa.Float, nullable=True),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("trade_id", sa.BigInteger, sa.ForeignKey("trades.id"), nullable=True),
        sa.Column("symbol", sa.String, nullable=False),
        sa.Column("side", sa.String, nullable=False),
        sa.Column("order_type", sa.String, nullable=False),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("price", sa.Float, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("broker_order_id", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "account_state",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("equity", sa.Float, nullable=False),
        sa.Column("available_capital", sa.Float, nullable=False),
        sa.Column("open_risk_pct", sa.Float, nullable=False),
    )

    # Prueba de concepto de la extensión: velas de 1h derivadas de 1m sin recalcular todo.
    op.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_1h
        WITH (timescaledb.continuous) AS
        SELECT
            symbol,
            time_bucket('1 hour', timestamp) AS bucket,
            first(open, timestamp) AS open,
            max(high) AS high,
            min(low) AS low,
            last(close, timestamp) AS close,
            sum(volume) AS volume
        FROM ohlcv
        WHERE timeframe = '1m'
        GROUP BY symbol, bucket
        WITH NO DATA
        """
    )


def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS ohlcv_1h")
    op.drop_table("account_state")
    op.drop_table("orders")
    op.drop_table("trades")
    op.drop_table("ohlcv")
