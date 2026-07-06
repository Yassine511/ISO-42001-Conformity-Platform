"""Reproducible assessment runs (M5).

Adds the frozen run contract to assessments: retrieval_k (resume can never
silently change depth), document_manifest (the exact document set indexed at
creation), cancel_requested (cooperative cancellation), and a partial unique
index enforcing at most one RUNNING assessment per organization.

Preflight: databases that already hold several RUNNING assessments for one
organization (possible before this invariant existed) would make the unique
index creation fail — all but the newest RUNNING row per organization are
finalized FAILED first, with error and finished_at set.

Legacy rows keep document_manifest NULL (an explicit "created before M5"
sentinel — nothing truthful can be backfilled); the API exposes this as
manifest_complete=false and refuses to resume such rows.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assessments",
        sa.Column("retrieval_k", sa.Integer(), nullable=False, server_default=sa.text("6")),
    )
    op.add_column("assessments", sa.Column("document_manifest", sa.JSON(), nullable=True))
    op.add_column(
        "assessments",
        sa.Column(
            "cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.create_check_constraint(
        "ck_assessments_retrieval_k", "assessments", "retrieval_k >= 1 AND retrieval_k <= 20"
    )

    # Preflight: demote duplicate RUNNING rows (keep the newest per org) so the
    # partial unique index below can be created on any existing database.
    op.execute(
        sa.text(
            """
            UPDATE assessments SET
                status = 'FAILED',
                error = 'clôturée par la migration 0011 : évaluations RUNNING multiples',
                finished_at = NOW()
            WHERE status = 'RUNNING'
              AND id NOT IN (
                  SELECT keep_id FROM (
                      SELECT DISTINCT ON (organization_id) id AS keep_id
                      FROM assessments
                      WHERE status = 'RUNNING'
                      ORDER BY organization_id, started_at DESC
                  ) newest
              )
            """
        )
    )

    op.create_index(
        "uq_assessments_one_running",
        "assessments",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("status = 'RUNNING'"),
    )


def downgrade() -> None:
    op.drop_index("uq_assessments_one_running", table_name="assessments")
    with op.batch_alter_table("assessments") as batch:
        batch.drop_constraint("ck_assessments_retrieval_k", type_="check")
        batch.drop_column("cancel_requested")
        batch.drop_column("document_manifest")
        batch.drop_column("retrieval_k")
