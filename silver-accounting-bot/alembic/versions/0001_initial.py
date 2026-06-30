from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("phone_number", sa.String(length=32), nullable=True),
        sa.Column("national_id_enc", sa.Text(), nullable=True),
        sa.Column("passport_file_id_enc", sa.Text(), nullable=True),
        sa.Column("selfie_file_id_enc", sa.Text(), nullable=True),
        sa.Column("verification_docs_file_ids_enc", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("kyc_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])

    op.create_table(
        "wallets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("available_balance_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("frozen_balance_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("margin_balance_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("equity_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("amount_usd", sa.Numeric(18, 2), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])

    op.create_table(
        "prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("buy_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("sell_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("spread", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("commission", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("premium", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("discount", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_prices_updated_at", "prices", ["updated_at"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("quantity_kg", sa.Numeric(18, 6), nullable=False),
        sa.Column("quoted_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("quote_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("receipt_file_id_enc", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_created_at", "orders", ["created_at"])
    op.create_index("ix_orders_quote_expires_at", "orders", ["quote_expires_at"])

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("net_kg", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("avg_price_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("last_settlement_price_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "margin_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("leverage", sa.Numeric(18, 2), nullable=False, server_default="1"),
        sa.Column("initial_margin_ratio", sa.Numeric(18, 4), nullable=False, server_default="1"),
        sa.Column("maintenance_margin_ratio", sa.Numeric(18, 4), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "settlements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("settlement_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_settlements_settlement_date", "settlements", ["settlement_date"])

    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tickets_user_id", "tickets", ["user_id"])
    op.create_index("ix_tickets_created_at", "tickets", ["created_at"])

    op.create_table(
        "ticket_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("author_role", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("attachment_file_ids_enc", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ticket_messages_ticket_id", "ticket_messages", ["ticket_id"])
    op.create_index("ix_ticket_messages_created_at", "ticket_messages", ["created_at"])

    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("account_number_enc", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("amount_usd", sa.Numeric(18, 2), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ledger_entries_user_id", "ledger_entries", ["user_id"])
    op.create_index("ix_ledger_entries_created_at", "ledger_entries", ["created_at"])

    op.create_table(
        "admin_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_logs_actor_user_id", "admin_logs", ["actor_user_id"])
    op.create_index("ix_admin_logs_created_at", "admin_logs", ["created_at"])

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_perm"),
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])
    op.create_index("ix_role_permissions_permission_id", "role_permissions", ["permission_id"])

    op.create_table(
        "user_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])


def downgrade() -> None:
    op.drop_index("ix_user_roles_role_id", table_name="user_roles")
    op.drop_index("ix_user_roles_user_id", table_name="user_roles")
    op.drop_table("user_roles")

    op.drop_index("ix_role_permissions_permission_id", table_name="role_permissions")
    op.drop_index("ix_role_permissions_role_id", table_name="role_permissions")
    op.drop_table("role_permissions")

    op.drop_table("permissions")
    op.drop_table("roles")

    op.drop_index("ix_admin_logs_created_at", table_name="admin_logs")
    op.drop_index("ix_admin_logs_actor_user_id", table_name="admin_logs")
    op.drop_table("admin_logs")

    op.drop_index("ix_ledger_entries_created_at", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_user_id", table_name="ledger_entries")
    op.drop_table("ledger_entries")

    op.drop_table("bank_accounts")

    op.drop_index("ix_ticket_messages_created_at", table_name="ticket_messages")
    op.drop_index("ix_ticket_messages_ticket_id", table_name="ticket_messages")
    op.drop_table("ticket_messages")

    op.drop_index("ix_tickets_created_at", table_name="tickets")
    op.drop_index("ix_tickets_user_id", table_name="tickets")
    op.drop_table("tickets")

    op.drop_index("ix_settlements_settlement_date", table_name="settlements")
    op.drop_table("settlements")

    op.drop_table("margin_accounts")
    op.drop_table("positions")

    op.drop_index("ix_orders_quote_expires_at", table_name="orders")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_index("ix_orders_user_id", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_prices_updated_at", table_name="prices")
    op.drop_table("prices")

    op.drop_index("ix_transactions_user_id", table_name="transactions")
    op.drop_table("transactions")

    op.drop_table("wallets")

    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_table("users")

