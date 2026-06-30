from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_user_language"
down_revision = "0004_payment_cards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("language_code", sa.String(length=16), nullable=True))
    op.create_index("ix_users_language_code", "users", ["language_code"])


def downgrade() -> None:
    op.drop_index("ix_users_language_code", table_name="users")
    op.drop_column("users", "language_code")
