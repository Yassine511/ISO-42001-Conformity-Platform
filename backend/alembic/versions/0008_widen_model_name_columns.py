"""Widen provider model-name columns to Text.

reported_model (provider-controlled) and requested_model (config-controlled)
were VARCHAR(100); a value longer than that raised DataError and left the
assessment RUNNING with no finding. Text removes the bound. findings.final_model
is derived from reported_model, so it is widened too.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("llm_calls", "requested_model", type_=sa.Text(), existing_nullable=False)
    op.alter_column("llm_calls", "reported_model", type_=sa.Text(), existing_nullable=True)
    op.alter_column("findings", "final_model", type_=sa.Text(), existing_nullable=True)


def downgrade() -> None:
    # Truncate on the way back so a value that exceeded the old bound (now
    # legal) cannot fail the narrowing.
    op.alter_column(
        "llm_calls", "requested_model", type_=sa.String(100), existing_nullable=False,
        postgresql_using="substr(requested_model, 1, 100)",
    )
    op.alter_column(
        "llm_calls", "reported_model", type_=sa.String(100), existing_nullable=True,
        postgresql_using="substr(reported_model, 1, 100)",
    )
    op.alter_column(
        "findings", "final_model", type_=sa.String(100), existing_nullable=True,
        postgresql_using="substr(final_model, 1, 100)",
    )
