from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone


revision = "0008_production_hardening"
down_revision = "0007_settlement_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "insurance_buffers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("insurance_buffers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("amount_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_insurance_buffers_user_id", "insurance_buffers", ["user_id"])  

    op.create_table(
        "circuit_breaker_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("circuit_name", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("half_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_circuit_breaker_events_name", "circuit_breaker_events", ["circuit_name", "state"])

    op.create_table(
        "dead_letter_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("task_name", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dead_letter_entries_source", "dead_letter_entries", ["source", "task_name"])

    op.create_table(
        "risk_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exposure_kg", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("daily_pnl_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("daily_loss_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("drawdown_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("concentration_ratio", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("risk_score", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("risk_score_level", sa.String(length=16), nullable=False),
        sa.Column("violation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_risk_snapshots_user_id", "risk_snapshots", ["user_id"])
    op.create_index("ix_risk_snapshots_created_at", "risk_snapshots", ["created_at"])


def downgrade() -> None:
    op.drop_table("risk_snapshots")
    op.drop_table("dead_letter_entries")
    op.drop_table("circuit_breaker_events")
    op.drop_table("insurance_buffers")
