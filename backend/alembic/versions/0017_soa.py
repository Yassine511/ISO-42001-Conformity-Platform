"""M8 Statement of Applicability — per Annex A CONTROL (A.2.2 … A.10.4).

Append-only soa_decisions (finding_reviews pattern: immutable history,
sequence per (org, control) allocated under the organization row lock) +
the soa_controls current-state projection. No default rows are seeded:
absence of a projection row means the default (applicable, no recorded
justification). Applicability annotates the SoA only — it never filters
conformity or risk outputs.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soa_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("control_id", sa.String(20), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("applicable", sa.Boolean(), nullable=False),
        sa.Column("justification_fr", sa.Text(), nullable=False),
        sa.Column("editor_label", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "control_id", "sequence", name="uq_soa_decisions_sequence"
        ),
    )
    op.create_table(
        "soa_controls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("control_id", sa.String(20), nullable=False),
        sa.Column("applicable", sa.Boolean(), nullable=False),
        sa.Column("justification_fr", sa.Text(), nullable=False),
        sa.Column("editor_label", sa.String(200), nullable=True),
        sa.Column(
            "decision_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "control_id", name="uq_soa_controls_pair"),
    )


def downgrade() -> None:
    op.drop_table("soa_controls")
    op.drop_table("soa_decisions")
