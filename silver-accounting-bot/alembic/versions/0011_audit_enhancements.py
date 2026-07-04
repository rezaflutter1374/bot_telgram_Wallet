from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011_audit_enhancements"
down_revision = "0010_enterprise_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("previous_hash", sa.String(64), nullable=True))
    op.add_column("audit_events", sa.Column("hash", sa.String(64), nullable=True, index=True))
    op.add_column("audit_events", sa.Column("correlation_id", sa.String(128), nullable=True, index=True))
    op.add_column("audit_events", sa.Column("causation_id", sa.String(128), nullable=True))
    op.add_column("audit_events", sa.Column("ip_address", sa.String(45), nullable=True))
    op.add_column("audit_events", sa.Column("before_json", sa.Text(), nullable=True))
    op.add_column("audit_events", sa.Column("after_json", sa.Text(), nullable=True))
    op.create_index("ix_audit_events_hash", "audit_events", ["hash"])
    op.create_index("ix_audit_events_correlation_id", "audit_events", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_correlation_id", table_name="audit_events")
    op.drop_index("ix_audit_events_hash", table_name="audit_events")
    op.drop_column("audit_events", "after_json")
    op.drop_column("audit_events", "before_json")
    op.drop_column("audit_events", "ip_address")
    op.drop_column("audit_events", "causation_id")
    op.drop_column("audit_events", "correlation_id")
    op.drop_column("audit_events", "hash")
    op.drop_column("audit_events", "previous_hash")
