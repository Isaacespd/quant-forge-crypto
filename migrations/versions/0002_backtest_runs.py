"""tabla backtest_runs + run_id en trades (spec 002, Motor de Backtesting)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("strategy_id", sa.String, nullable=False),
        sa.Column("symbol", sa.String, nullable=False),
        sa.Column("timeframe", sa.String, nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_equity", sa.Float, nullable=False),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column("trades", sa.Column("run_id", sa.BigInteger, sa.ForeignKey("backtest_runs.id"), nullable=True))


def downgrade():
    op.drop_column("trades", "run_id")
    op.drop_table("backtest_runs")
