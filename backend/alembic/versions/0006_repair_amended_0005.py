"""Repair for the amended (already-published) revision 0005.

Revision 0005 was pushed in c25df1c, then a later commit amended it in place
to add llm_calls.prompt_version and the 'rate_limited' abstain reason. A
database stamped 0005 under the published form never receives those changes,
so the application fails on insert. This revision applies the delta properly:

- adds llm_calls.prompt_version, backfills it from the parent
  assessment_attempts.prompt_version (the per-attempt version those calls were
  actually made under), then makes it NOT NULL — no server default is left
  behind (the column is added nullable, backfilled, then tightened);
- recreates ck_findings_abstain_reason with 'rate_limited'.

Databases created AFTER the amendment already have both changes while being
stamped 0005, so the column step is guarded by inspection.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_ABSTAIN_REASONS_OLD = (
    "abstain_reason IS NULL OR abstain_reason IN "
    "('model_abstained', 'verification_failed', 'fuzzy_citation', "
    "'low_confidence', 'llm_error')"
)
_ABSTAIN_REASONS_NEW = (
    "abstain_reason IS NULL OR abstain_reason IN "
    "('model_abstained', 'verification_failed', 'fuzzy_citation', "
    "'low_confidence', 'llm_error', 'rate_limited')"
)

_BACKFILL = """
UPDATE llm_calls SET prompt_version = COALESCE(
    (SELECT aa.prompt_version FROM assessment_attempts aa
     WHERE aa.id = llm_calls.assessment_attempt_id),
    ''
)
"""


def _llm_calls_has_prompt_version() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == "prompt_version" for c in inspector.get_columns("llm_calls"))


def upgrade() -> None:
    if not _llm_calls_has_prompt_version():
        op.add_column("llm_calls", sa.Column("prompt_version", sa.String(20), nullable=True))
        op.execute(sa.text(_BACKFILL))
        with op.batch_alter_table("llm_calls") as batch:
            batch.alter_column(
                "prompt_version", existing_type=sa.String(20), nullable=False
            )

    # Recreate the CHECK unconditionally: on an amended-0005 database this is
    # a no-op rewrite of the same definition; on a published-0005 database it
    # adds 'rate_limited'.
    with op.batch_alter_table("findings") as batch:
        batch.drop_constraint("ck_findings_abstain_reason", type_="check")
        batch.create_check_constraint("ck_findings_abstain_reason", _ABSTAIN_REASONS_NEW)


def downgrade() -> None:
    # rate_limited is a refinement of llm_error (throttling is one way all
    # providers can fail): narrow it back before restoring the old CHECK.
    op.execute(
        sa.text(
            "UPDATE findings SET abstain_reason = 'llm_error' "
            "WHERE abstain_reason = 'rate_limited'"
        )
    )
    with op.batch_alter_table("findings") as batch:
        batch.drop_constraint("ck_findings_abstain_reason", type_="check")
        batch.create_check_constraint("ck_findings_abstain_reason", _ABSTAIN_REASONS_OLD)
    if _llm_calls_has_prompt_version():
        with op.batch_alter_table("llm_calls") as batch:
            batch.drop_column("prompt_version")
