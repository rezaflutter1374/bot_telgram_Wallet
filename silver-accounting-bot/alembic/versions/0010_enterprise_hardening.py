from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0010_enterprise_hardening"
down_revision = "0009_event_store_period_close"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("positions", sa.Column("realized_pnl_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("positions", sa.Column("total_fees_paid_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("positions", sa.Column("total_funding_paid_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("positions", sa.Column("trade_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("positions", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("positions", sa.Column("peak_net_kg", sa.Numeric(18, 6), nullable=False, server_default="0"))
    op.add_column("positions", sa.Column("peak_equity_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))

    op.create_index("ix_positions_realized_pnl", "positions", ["realized_pnl_usd"])
    op.create_index("ix_positions_net_kg", "positions", ["net_kg"])

    op.add_column("margin_accounts", sa.Column("position_margin_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("margin_accounts", sa.Column("order_margin_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("margin_accounts", sa.Column("available_margin_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("margin_accounts", sa.Column("funding_balance_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("margin_accounts", sa.Column("margin_call_threshold", sa.Numeric(18, 6), nullable=False, server_default="1.0"))
    op.add_column("margin_accounts", sa.Column("liquidation_threshold", sa.Numeric(18, 6), nullable=False, server_default="0.5"))

    op.add_column("wallets", sa.Column("total_deposits_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("wallets", sa.Column("total_withdrawals_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("wallets", sa.Column("total_trade_volume_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("wallets", sa.Column("total_fees_paid_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("wallets", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "funding_rates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("mark_price_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "position_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("net_kg", sa.Numeric(18, 6), nullable=False, default=0),
        sa.Column("avg_price_usd", sa.Numeric(18, 6), nullable=False, default=0),
        sa.Column("realized_pnl_usd", sa.Numeric(18, 2), nullable=False, default=0),
        sa.Column("unrealized_pnl_usd", sa.Numeric(18, 2), nullable=False, default=0),
        sa.Column("mark_price_usd", sa.Numeric(18, 6), nullable=False, default=0),
        sa.Column("payload_json", sa.Text(), nullable=False, default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "daily_pnl_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("pnl_usd", sa.Numeric(18, 2), nullable=False, default=0),
        sa.Column("volume_kg", sa.Numeric(18, 6), nullable=False, default=0),
        sa.Column("trade_count", sa.Integer(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "date", name="uq_daily_pnl_user_date"),
    )

    op.create_index("ix_funding_rates_timestamp", "funding_rates", ["timestamp"])
    op.create_index("ix_daily_pnl_records_date", "daily_pnl_records", ["date"])


def downgrade() -> None:
    op.drop_table("daily_pnl_records")
    op.drop_table("position_snapshots")
    op.drop_table("funding_rates")

    op.drop_column("wallets", "last_activity_at")
    op.drop_column("wallets", "total_fees_paid_usd")
    op.drop_column("wallets", "total_trade_volume_usd")
    op.drop_column("wallets", "total_withdrawals_usd")
    op.drop_column("wallets", "total_deposits_usd")

    op.drop_column("margin_accounts", "liquidation_threshold")
    op.drop_column("margin_accounts", "margin_call_threshold")
    op.drop_column("margin_accounts", "funding_balance_usd")
    op.drop_column("margin_accounts", "available_margin_usd")
    op.drop_column("margin_accounts", "order_margin_usd")
    op.drop_column("margin_accounts", "position_margin_usd")

    op.drop_index("ix_positions_net_kg", table_name="positions")
    op.drop_index("ix_positions_realized_pnl", table_name="positions")
    op.drop_column("positions", "peak_equity_usd")
    op.drop_column("positions", "peak_net_kg")
    op.drop_column("positions", "created_at")
    op.drop_column("positions", "trade_count")
    op.drop_column("positions", "total_funding_paid_usd")
    op.drop_column("positions", "total_fees_paid_usd")
    op.drop_column("positions", "realized_pnl_usd")
