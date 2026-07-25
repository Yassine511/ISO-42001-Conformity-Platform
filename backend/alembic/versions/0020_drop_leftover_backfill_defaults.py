"""Drop three leftover backfill server defaults.

Found by the new migration<->model cross-check (tests/test_migrations.py::
test_migration_head_matches_the_models), not by inspection.

`server_default=""` is a BACKFILL MECHANISM: it exists so `op.add_column` can
make a column NOT NULL on a table that already has rows. Once the column is
populated the default has done its job, and leaving it behind changes runtime
semantics — an INSERT that omits the column silently receives `''` instead of
failing. Migration 0006 already made exactly this correction for
`llm_calls.prompt_version` (and tests/test_migrations.py asserts no default
survives there); these three were missed:

- documents.parser_version  (added by 0002)
- documents.checksum        (added by 0002; 0014 later made it nullable, so the
                             '' default also let a row bypass the M7b invariant
                             `checksum == current_version.source_checksum`,
                             which is written only after a successful parse)
- remediation_llm_calls.prompt_version (added by 0013)

Existing rows are untouched: dropping a default only affects future INSERTs
that omit the column. The ORM always supplies all three (Document.parser_version
keeps a PYTHON-side default), so no application path changes behaviour — what
changes is that a raw SQL insert can no longer get a meaningless placeholder.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


# (table, column, type, nullable) — type/nullable restated because ALTER COLUMN
# in Alembic needs the existing type to render on some backends.
_LEFTOVERS = (
    ("documents", "parser_version", sa.String(20), False),
    ("documents", "checksum", sa.String(64), True),
    ("remediation_llm_calls", "prompt_version", sa.String(20), False),
)


def upgrade() -> None:
    for table, column, type_, nullable in _LEFTOVERS:
        op.alter_column(
            table,
            column,
            existing_type=type_,
            existing_nullable=nullable,
            server_default=None,
        )


def downgrade() -> None:
    for table, column, type_, nullable in _LEFTOVERS:
        op.alter_column(
            table,
            column,
            existing_type=type_,
            existing_nullable=nullable,
            server_default=sa.text("''"),
        )
