from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_finance_risk"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payment_type", sa.String(length=16), nullable=False),
        sa.Column("amount_usd", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="uploaded"),
        sa.Column("receipt_file_ids_enc", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("bank_account_id", sa.Integer(), sa.ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payment_requests_user_id", "payment_requests", ["user_id"])
    op.create_index("ix_payment_requests_reviewer_user_id", "payment_requests", ["reviewer_user_id"])
    op.create_index("ix_payment_requests_status", "payment_requests", ["status"])
    op.create_index("ix_payment_requests_created_at", "payment_requests", ["created_at"])
    op.create_index("ix_payment_requests_updated_at", "payment_requests", ["updated_at"])

    op.create_table(
        "journal_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("account_type", sa.String(length=16), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("journal_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_journal_accounts_code", "journal_accounts", ["code"])
    op.create_index("ix_journal_accounts_account_type", "journal_accounts", ["account_type"])

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_journal_entries_reference", "journal_entries", ["reference"])
    op.create_index("ix_journal_entries_posted_at", "journal_entries", ["posted_at"])
    op.create_index("ix_journal_entries_created_by_user_id", "journal_entries", ["created_by_user_id"])
    op.create_index("ix_journal_entries_created_at", "journal_entries", ["created_at"])

    op.create_table(
        "journal_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("journal_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("debit_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("credit_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_journal_lines_entry_id", "journal_lines", ["entry_id"])
    op.create_index("ix_journal_lines_account_id", "journal_lines", ["account_id"])
    op.create_index("ix_journal_lines_user_id", "journal_lines", ["user_id"])
    op.create_index("ix_journal_lines_created_at", "journal_lines", ["created_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="telegram"),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_kind", "notifications", ["kind"])
    op.create_index("ix_notifications_status", "notifications", ["status"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_entity_type", "audit_events", ["entity_type"])
    op.create_index("ix_audit_events_entity_id", "audit_events", ["entity_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])

    op.create_table(
        "risk_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("max_user_exposure_kg", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("max_order_kg", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_risk_rules_created_at", "risk_rules", ["created_at"])

    op.create_table(
        "margin_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("margin_ratio", sa.Numeric(18, 6), nullable=False),
        sa.Column("threshold", sa.Numeric(18, 6), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_margin_calls_user_id", "margin_calls", ["user_id"])
    op.create_index("ix_margin_calls_status", "margin_calls", ["status"])
    op.create_index("ix_margin_calls_created_at", "margin_calls", ["created_at"])

    op.create_table(
        "liquidation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("margin_ratio", sa.Numeric(18, 6), nullable=False),
        sa.Column("critical_level", sa.Numeric(18, 6), nullable=False),
        sa.Column("close_price_usd", sa.Numeric(18, 6), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="triggered"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_liquidation_events_user_id", "liquidation_events", ["user_id"])
    op.create_index("ix_liquidation_events_status", "liquidation_events", ["status"])
    op.create_index("ix_liquidation_events_created_at", "liquidation_events", ["created_at"])

    op.create_table(
        "order_cancellations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="requested"),
        sa.Column("admin_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("order_id"),
    )
    op.create_index("ix_order_cancellations_order_id", "order_cancellations", ["order_id"])
    op.create_index("ix_order_cancellations_requested_by_user_id", "order_cancellations", ["requested_by_user_id"])
    op.create_index("ix_order_cancellations_status", "order_cancellations", ["status"])
    op.create_index("ix_order_cancellations_created_at", "order_cancellations", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_order_cancellations_created_at", table_name="order_cancellations")
    op.drop_index("ix_order_cancellations_status", table_name="order_cancellations")
    op.drop_index("ix_order_cancellations_requested_by_user_id", table_name="order_cancellations")
    op.drop_index("ix_order_cancellations_order_id", table_name="order_cancellations")
    op.drop_table("order_cancellations")

    op.drop_index("ix_liquidation_events_created_at", table_name="liquidation_events")
    op.drop_index("ix_liquidation_events_status", table_name="liquidation_events")
    op.drop_index("ix_liquidation_events_user_id", table_name="liquidation_events")
    op.drop_table("liquidation_events")

    op.drop_index("ix_margin_calls_created_at", table_name="margin_calls")
    op.drop_index("ix_margin_calls_status", table_name="margin_calls")
    op.drop_index("ix_margin_calls_user_id", table_name="margin_calls")
    op.drop_table("margin_calls")

    op.drop_index("ix_risk_rules_created_at", table_name="risk_rules")
    op.drop_table("risk_rules")

    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_entity_id", table_name="audit_events")
    op.drop_index("ix_audit_events_entity_type", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_status", table_name="notifications")
    op.drop_index("ix_notifications_kind", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index("ix_journal_lines_created_at", table_name="journal_lines")
    op.drop_index("ix_journal_lines_user_id", table_name="journal_lines")
    op.drop_index("ix_journal_lines_account_id", table_name="journal_lines")
    op.drop_index("ix_journal_lines_entry_id", table_name="journal_lines")
    op.drop_table("journal_lines")

    op.drop_index("ix_journal_entries_created_at", table_name="journal_entries")
    op.drop_index("ix_journal_entries_created_by_user_id", table_name="journal_entries")
    op.drop_index("ix_journal_entries_posted_at", table_name="journal_entries")
    op.drop_index("ix_journal_entries_reference", table_name="journal_entries")
    op.drop_table("journal_entries")

    op.drop_index("ix_journal_accounts_account_type", table_name="journal_accounts")
    op.drop_index("ix_journal_accounts_code", table_name="journal_accounts")
    op.drop_table("journal_accounts")

    op.drop_index("ix_payment_requests_updated_at", table_name="payment_requests")
    op.drop_index("ix_payment_requests_created_at", table_name="payment_requests")
    op.drop_index("ix_payment_requests_status", table_name="payment_requests")
    op.drop_index("ix_payment_requests_reviewer_user_id", table_name="payment_requests")
    op.drop_index("ix_payment_requests_user_id", table_name="payment_requests")
    op.drop_table("payment_requests")

