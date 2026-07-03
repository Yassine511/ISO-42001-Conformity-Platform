"""Add provenance columns to documents: checksum, parser_version.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("checksum", sa.String(64), nullable=False, server_default=""))
    op.add_column("documents", sa.Column("parser_version", sa.String(20), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("documents", "parser_version")
    op.drop_column("documents", "checksum")
