"""Enforce per-org content uniqueness: NULL legacy checksums, unique constraint.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy pre-M2 rows carry '' — NULL them so the unique constraint
    # (which ignores NULLs) cannot be violated by multiple legacy docs.
    op.execute("UPDATE documents SET checksum = NULL WHERE checksum = ''")
    op.alter_column("documents", "checksum", existing_type=sa.String(64), nullable=True)
    op.create_unique_constraint(
        "uq_documents_org_checksum", "documents", ["organization_id", "checksum"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_documents_org_checksum", "documents", type_="unique")
    op.execute("UPDATE documents SET checksum = '' WHERE checksum IS NULL")
    op.alter_column("documents", "checksum", existing_type=sa.String(64), nullable=False)
