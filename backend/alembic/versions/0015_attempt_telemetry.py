"""M8 typed attempt telemetry.

parsed_ok + free-form French verifier_errors cannot support typed trust-panel
counts: parsed_ok=False conflates a malformed schema with a total provider
failure, and classifying legacy French strings would be fragile. So:

- attempt_outcome: parsed | schema_invalid | provider_failure, written by the
  judge node at the only site that can tell the kinds apart. Backfill is
  best-effort where unambiguous (parsed_ok=True -> 'parsed'); every other
  legacy row becomes the first-class value 'legacy_unclassified' — NEVER
  reclassified by string matching.
- verifier_error_codes: typed mirror of verifier_errors, written by the
  verify node. [] = attempt completed with no verifier error; NULL = legacy
  row (codes unavailable) or attempt not yet completed by the verify node.
  No backfill (nothing truthful exists for legacy rows).

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assessment_attempts",
        sa.Column(
            "attempt_outcome",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'legacy_unclassified'"),
        ),
    )
    op.add_column(
        "assessment_attempts",
        sa.Column("verifier_error_codes", sa.JSON(), nullable=True),
    )
    op.create_check_constraint(
        "ck_assessment_attempts_outcome",
        "assessment_attempts",
        "attempt_outcome IN ('parsed', 'schema_invalid', 'provider_failure', "
        "'legacy_unclassified')",
    )
    # unambiguous backfill only: a parsed_ok row really did parse
    op.execute(
        "UPDATE assessment_attempts SET attempt_outcome = 'parsed' WHERE parsed_ok"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_assessment_attempts_outcome", "assessment_attempts", type_="check"
    )
    op.drop_column("assessment_attempts", "verifier_error_codes")
    op.drop_column("assessment_attempts", "attempt_outcome")
