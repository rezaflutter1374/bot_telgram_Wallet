from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_settlement_batches"
down_revision = "0006_price_provider_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settlement_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_key", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("target_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lock_key", sa.String(length=128), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_scope_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("verification_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("last_checkpoint", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("batch_key"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_settlement_batches_batch_key", "settlement_batches", ["batch_key"])
    op.create_index("ix_settlement_batches_idempotency_key", "settlement_batches", ["idempotency_key"])
    op.create_index("ix_settlement_batches_mode", "settlement_batches", ["mode"])
    op.create_index("ix_settlement_batches_status", "settlement_batches", ["status"])
    op.create_index("ix_settlement_batches_target_date", "settlement_batches", ["target_date"])
    op.create_index("ix_settlement_batches_actor_user_id", "settlement_batches", ["actor_user_id"])
    op.create_index("ix_settlement_batches_created_at", "settlement_batches", ["created_at"])
    op.create_index("ix_settlement_batches_updated_at", "settlement_batches", ["updated_at"])

    op.create_table(
        "settlement_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("settlement_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checkpoint_name", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("batch_id", "checkpoint_name", name="uq_settlement_checkpoint_batch_name"),
    )
    op.create_index("ix_settlement_checkpoints_batch_id", "settlement_checkpoints", ["batch_id"])
    op.create_index("ix_settlement_checkpoints_created_at", "settlement_checkpoints", ["created_at"])

    with op.batch_alter_table("settlements", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("batch_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("mode", sa.String(length=16), nullable=False, server_default="daily"))
        batch_op.add_column(sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"))
        batch_op.add_column(sa.Column("replay_of_settlement_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("rollback_of_settlement_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("verification_json", sa.Text(), nullable=False, server_default="{}"))
        batch_op.create_foreign_key("fk_settlements_batch_id", "settlement_batches", ["batch_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_settlements_replay_of_settlement_id", "settlements", ["replay_of_settlement_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_settlements_rollback_of_settlement_id", "settlements", ["rollback_of_settlement_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_settlements_batch_id", ["batch_id"], unique=True)
        batch_op.create_index("ix_settlements_mode", ["mode"])
        batch_op.create_index("ix_settlements_status", ["status"])
        batch_op.create_index("ix_settlements_replay_of_settlement_id", ["replay_of_settlement_id"])
        batch_op.create_index("ix_settlements_rollback_of_settlement_id", ["rollback_of_settlement_id"])

    op.create_table(
        "settlement_reconciliations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("settlement_id", sa.Integer(), sa.ForeignKey("settlements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pnl_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("balance_before_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("balance_after_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("previous_settlement_price_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("new_settlement_price_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="completed"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_settlement_reconciliations_settlement_id", "settlement_reconciliations", ["settlement_id"])
    op.create_index("ix_settlement_reconciliations_user_id", "settlement_reconciliations", ["user_id"])
    op.create_index("ix_settlement_reconciliations_status", "settlement_reconciliations", ["status"])
    op.create_index("ix_settlement_reconciliations_created_at", "settlement_reconciliations", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_settlement_reconciliations_created_at", table_name="settlement_reconciliations")
    op.drop_index("ix_settlement_reconciliations_status", table_name="settlement_reconciliations")
    op.drop_index("ix_settlement_reconciliations_user_id", table_name="settlement_reconciliations")
    op.drop_index("ix_settlement_reconciliations_settlement_id", table_name="settlement_reconciliations")
    op.drop_table("settlement_reconciliations")

    with op.batch_alter_table("settlements", recreate="always") as batch_op:
        batch_op.drop_index("ix_settlements_rollback_of_settlement_id")
        batch_op.drop_index("ix_settlements_replay_of_settlement_id")
        batch_op.drop_index("ix_settlements_status")
        batch_op.drop_index("ix_settlements_mode")
        batch_op.drop_index("ix_settlements_batch_id")
        batch_op.drop_constraint("fk_settlements_rollback_of_settlement_id", type_="foreignkey")
        batch_op.drop_constraint("fk_settlements_replay_of_settlement_id", type_="foreignkey")
        batch_op.drop_constraint("fk_settlements_batch_id", type_="foreignkey")
        batch_op.drop_column("verification_json")
        batch_op.drop_column("rollback_of_settlement_id")
        batch_op.drop_column("replay_of_settlement_id")
        batch_op.drop_column("status")
        batch_op.drop_column("mode")
        batch_op.drop_column("batch_id")

    op.drop_index("ix_settlement_checkpoints_created_at", table_name="settlement_checkpoints")
    op.drop_index("ix_settlement_checkpoints_batch_id", table_name="settlement_checkpoints")
    op.drop_table("settlement_checkpoints")

    op.drop_index("ix_settlement_batches_updated_at", table_name="settlement_batches")
    op.drop_index("ix_settlement_batches_created_at", table_name="settlement_batches")
    op.drop_index("ix_settlement_batches_actor_user_id", table_name="settlement_batches")
    op.drop_index("ix_settlement_batches_target_date", table_name="settlement_batches")
    op.drop_index("ix_settlement_batches_status", table_name="settlement_batches")
    op.drop_index("ix_settlement_batches_mode", table_name="settlement_batches")
    op.drop_index("ix_settlement_batches_idempotency_key", table_name="settlement_batches")
    op.drop_index("ix_settlement_batches_batch_key", table_name="settlement_batches")
    op.drop_table("settlement_batches")
