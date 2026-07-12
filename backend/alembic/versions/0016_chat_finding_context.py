"""M8 chat finding drill-down context.

chat_messages gains a live finding pointer (SET NULL on deletion — the
conversation must never block finding/assessment deletion) plus the
IMMUTABLE finding_context_snapshot captured at ask time: what the copilot
was shown, replayable after deletion or re-review, without depending on
chat_llm_calls request-payload provenance.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column(
            "finding_id",
            sa.String(36),
            sa.ForeignKey("findings.id", ondelete="SET NULL", name="fk_chat_messages_finding"),
            nullable=True,
        ),
    )
    op.add_column(
        "chat_messages", sa.Column("finding_context_snapshot", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_constraint("fk_chat_messages_finding", "chat_messages", type_="foreignkey")
    op.drop_column("chat_messages", "finding_context_snapshot")
    op.drop_column("chat_messages", "finding_id")
