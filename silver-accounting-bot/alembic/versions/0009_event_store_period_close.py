from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_event_store_period_close"
down_revision = "0008_production_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stored_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=8), nullable=False, server_default="1"),
        sa.Column("aggregate_id", sa.String(length=64), nullable=True),
        sa.Column("aggregate_type", sa.String(length=64), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stored_events_event_id", "stored_events", ["event_id"])
    op.create_index("ix_stored_events_type", "stored_events", ["event_type", "occurred_at"])
    op.create_index("ix_stored_events_aggregate", "stored_events", ["aggregate_type", "aggregate_id"])
    op.create_index("ix_stored_events_actor", "stored_events", ["actor_user_id"])
    op.create_index("ix_stored_events_correlation", "stored_events", ["correlation_id"])

    op.create_table(
        "financial_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period_type", sa.String(length=16), nullable=False, index=True),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("closed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("income_accounts_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("expense_accounts_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("retained_earnings_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_income_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("closing_journal_entry_id", sa.Integer(), sa.ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reversal_journal_entry_id", sa.Integer(), sa.ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_financial_periods_dates", "financial_periods", ["period_type", "start_date", "end_date"])

    op.add_column("wallets", sa.Column("pending_balance_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("wallets", sa.Column("settlement_balance_usd", sa.Numeric(18, 2), nullable=False, server_default="0"))

    op.create_table(
        "payment_reconciliation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_request_id", sa.Integer(), sa.ForeignKey("payment_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reference_number", sa.String(length=128), nullable=True),
        sa.Column("matched_payment_request_id", sa.Integer(), sa.ForeignKey("payment_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("duplicate_check_hash", sa.String(length=128), nullable=True, index=True),
        sa.Column("is_duplicate", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("reconciliation_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payment_reconciliation_ref", "payment_reconciliation", ["reference_number"])
    op.create_index("ix_payment_reconciliation_dup", "payment_reconciliation", ["duplicate_check_hash"])

    op.create_table(
        "price_anomalies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("price_id", sa.Integer(), sa.ForeignKey("prices.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("anomaly_type", sa.String(length=32), nullable=False, index=True),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="warning"),
        sa.Column("observed_value_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("expected_value_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("deviation_pct", sa.Numeric(18, 6), nullable=False),
        sa.Column("threshold_pct", sa.Numeric(18, 6), nullable=False),
        sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("resolved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_price_anomalies_type_status", "price_anomalies", ["anomaly_type", "is_resolved"])


def downgrade() -> None:
    op.drop_table("price_anomalies")
    op.drop_table("payment_reconciliation")
    op.drop_column("wallets", "settlement_balance_usd")
    op.drop_column("wallets", "pending_balance_usd")
    op.drop_table("financial_periods")
    op.drop_table("stored_events")
