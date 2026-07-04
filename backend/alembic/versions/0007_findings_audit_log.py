"""Persist the per-node audit trail on findings.

The pipeline accumulates an append-only audit_log in graph state
(retrieve -> judge -> verify events), but it previously lived only in the
LangGraph checkpoint: any resumed or re-fetched finding came back with an
empty trail. The terminal audit log is now persisted with the finding so the
decision trace survives resume (NULL for pre-0007 findings).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("audit_log", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("findings") as batch:
        batch.drop_column("audit_log")
