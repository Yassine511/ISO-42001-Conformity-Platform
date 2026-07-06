"""Finding requirement snapshots + human review (M5 HITL).

- requirement_fr/domain: the requirement text as assessed, snapshotted by the
  pipeline at persist time. NO backfill here: nothing truthful exists for
  legacy rows (and an Alembic backfill would couple the migration to the
  external KB file); they stay NULL and the API falls back to the live KB
  only when corpus_version still matches.
- review_* projection columns on findings (current decision) + the immutable
  finding_reviews history table. AI columns stay write-once by the pipeline;
  the ck_findings_status CHECK is untouched — CONFIRMED is review_status,
  never a third finding status.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("requirement_fr", sa.Text(), nullable=True))
    op.add_column("findings", sa.Column("domain", sa.String(100), nullable=True))
    op.add_column(
        "findings",
        sa.Column(
            "review_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
    )
    op.add_column("findings", sa.Column("review_action", sa.String(20), nullable=True))
    op.add_column("findings", sa.Column("human_verdict", sa.String(20), nullable=True))
    op.add_column("findings", sa.Column("human_rationale", sa.Text(), nullable=True))
    op.add_column("findings", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column(
        "findings", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "findings",
        sa.Column("review_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_check_constraint(
        "ck_findings_review_status", "findings", "review_status IN ('PENDING', 'CONFIRMED')"
    )
    op.create_check_constraint(
        "ck_findings_review_action",
        "findings",
        "review_action IS NULL OR review_action IN ('approve', 'edit', 'override')",
    )
    op.create_check_constraint(
        "ck_findings_human_verdict",
        "findings",
        "human_verdict IS NULL OR human_verdict IN "
        "('compliant', 'partial', 'non_compliant', 'missing')",
    )
    op.create_check_constraint(
        "ck_findings_review_coherence",
        "findings",
        "(review_status = 'PENDING' AND review_action IS NULL "
        "AND human_verdict IS NULL AND reviewed_at IS NULL) "
        "OR (review_status = 'CONFIRMED' AND review_action IS NOT NULL "
        "AND human_verdict IS NOT NULL AND reviewed_at IS NOT NULL)",
    )

    op.create_table(
        "finding_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "finding_id",
            sa.String(36),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("human_verdict", sa.String(20), nullable=False),
        sa.Column("human_rationale", sa.Text(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewer_label", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("finding_id", "sequence", name="uq_finding_reviews_sequence"),
        sa.CheckConstraint(
            "action IN ('approve', 'edit', 'override')", name="ck_finding_reviews_action"
        ),
        sa.CheckConstraint(
            "human_verdict IN ('compliant', 'partial', 'non_compliant', 'missing')",
            name="ck_finding_reviews_verdict",
        ),
    )


def downgrade() -> None:
    op.drop_table("finding_reviews")
    with op.batch_alter_table("findings") as batch:
        batch.drop_constraint("ck_findings_review_coherence", type_="check")
        batch.drop_constraint("ck_findings_human_verdict", type_="check")
        batch.drop_constraint("ck_findings_review_action", type_="check")
        batch.drop_constraint("ck_findings_review_status", type_="check")
        batch.drop_column("review_count")
        batch.drop_column("reviewed_at")
        batch.drop_column("review_note")
        batch.drop_column("human_rationale")
        batch.drop_column("human_verdict")
        batch.drop_column("review_action")
        batch.drop_column("review_status")
        batch.drop_column("domain")
        batch.drop_column("requirement_fr")
