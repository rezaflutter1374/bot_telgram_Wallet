from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_payment_cards"
down_revision = "0003_settlement_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bank_account_id", sa.Integer(), sa.ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("card_number_enc", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payment_cards_bank_account_id", "payment_cards", ["bank_account_id"])


def downgrade() -> None:
    op.drop_index("ix_payment_cards_bank_account_id", table_name="payment_cards")
    op.drop_table("payment_cards")
