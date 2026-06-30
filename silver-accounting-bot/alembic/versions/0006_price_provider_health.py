from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_price_provider_health"
down_revision = "0005_user_language"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prices", sa.Column("source", sa.String(length=64), nullable=False, server_default="manual_admin"))
    op.add_column("prices", sa.Column("external_id", sa.String(length=128), nullable=True))
    op.add_column("prices", sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True))
    op.add_column("prices", sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("prices", sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("prices", sa.Column("raw_payload", sa.Text(), nullable=True))
    op.create_index("ix_prices_source", "prices", ["source"])
    op.create_index("ix_prices_external_id", "prices", ["external_id"])
    op.create_index("ix_prices_provider_timestamp", "prices", ["provider_timestamp"])
    op.create_index("ix_prices_is_verified", "prices", ["is_verified"])
    op.create_index("ix_prices_is_stale", "prices", ["is_stale"])

    op.create_table(
        "price_provider_statuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("is_healthy", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_price_usd_per_kg", sa.Numeric(18, 6), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider_name"),
    )
    op.create_index("ix_price_provider_statuses_provider_name", "price_provider_statuses", ["provider_name"])
    op.create_index("ix_price_provider_statuses_updated_at", "price_provider_statuses", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_price_provider_statuses_updated_at", table_name="price_provider_statuses")
    op.drop_index("ix_price_provider_statuses_provider_name", table_name="price_provider_statuses")
    op.drop_table("price_provider_statuses")

    op.drop_index("ix_prices_is_stale", table_name="prices")
    op.drop_index("ix_prices_is_verified", table_name="prices")
    op.drop_index("ix_prices_provider_timestamp", table_name="prices")
    op.drop_index("ix_prices_external_id", table_name="prices")
    op.drop_index("ix_prices_source", table_name="prices")
    op.drop_column("prices", "raw_payload")
    op.drop_column("prices", "is_stale")
    op.drop_column("prices", "is_verified")
    op.drop_column("prices", "provider_timestamp")
    op.drop_column("prices", "external_id")
    op.drop_column("prices", "source")
