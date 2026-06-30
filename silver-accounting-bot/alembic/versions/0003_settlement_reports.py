from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_settlement_reports"
down_revision = "0002_finance_risk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settlement_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("settlement_id", sa.Integer(), sa.ForeignKey("settlements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("settlement_id"),
    )
    op.create_index("ix_settlement_reports_settlement_id", "settlement_reports", ["settlement_id"])
    op.create_index("ix_settlement_reports_created_at", "settlement_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_settlement_reports_created_at", table_name="settlement_reports")
    op.drop_index("ix_settlement_reports_settlement_id", table_name="settlement_reports")
    op.drop_table("settlement_reports")
