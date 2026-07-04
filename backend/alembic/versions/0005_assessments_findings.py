"""M3 pipeline provenance: assessments, findings, assessment_attempts, llm_calls.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("corpus_version", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'FAILED')", name="ck_assessments_status"
        ),
    )
    op.create_index("ix_assessments_organization_id", "assessments", ["organization_id"])

    op.create_table(
        "findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.String(36),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requirement_id", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("verdict", sa.String(20), nullable=True),
        sa.Column("policy_quote", sa.Text(), nullable=True),
        sa.Column("clause_ref", sa.String(20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("matched_chunk_id", sa.String(64), nullable=True),
        sa.Column("match_start", sa.Integer(), nullable=True),
        sa.Column("match_end", sa.Integer(), nullable=True),
        sa.Column("match_method", sa.String(10), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("abstain_reason", sa.String(50), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("final_model", sa.String(100), nullable=True),
        sa.Column("final_provider", sa.String(20), nullable=True),
        sa.Column("retrieved", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("assessment_id", "requirement_id", name="uq_findings_assessment_req"),
        sa.CheckConstraint("status IN ('VERIFIED', 'ABSTAINED')", name="ck_findings_status"),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN ('compliant', 'partial', 'non_compliant', 'missing')",
            name="ck_findings_verdict",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_findings_confidence",
        ),
        sa.CheckConstraint(
            "abstain_reason IS NULL OR abstain_reason IN "
            "('model_abstained', 'verification_failed', 'low_confidence', 'llm_error')",
            name="ck_findings_abstain_reason",
        ),
        sa.CheckConstraint(
            "match_method IS NULL OR match_method IN ('exact', 'fuzzy')",
            name="ck_findings_match_method",
        ),
        sa.CheckConstraint("attempts >= 0 AND attempts <= 2", name="ck_findings_attempts"),
    )
    op.create_index("ix_findings_assessment_id", "findings", ["assessment_id"])

    op.create_table(
        "assessment_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.String(36),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requirement_id", sa.String(20), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("parsed_ok", sa.Boolean(), nullable=False),
        sa.Column("verifier_errors", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "assessment_id", "requirement_id", "attempt_number", name="uq_attempts_key"
        ),
    )
    op.create_index(
        "ix_assessment_attempts_assessment_id", "assessment_attempts", ["assessment_id"]
    )

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assessment_attempt_id",
            sa.String(36),
            sa.ForeignKey("assessment_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("call_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("requested_model", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reported_model", sa.String(100), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("request_messages", sa.JSON(), nullable=False),
        sa.Column("response_format", sa.JSON(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("assessment_attempt_id", "call_number", name="uq_llm_calls_key"),
        sa.CheckConstraint(
            "status IN ('SUCCESS', 'HTTP_ERROR', 'NETWORK_ERROR', 'SKIPPED_NO_KEY')",
            name="ck_llm_calls_status",
        ),
    )
    op.create_index(
        "ix_llm_calls_assessment_attempt_id", "llm_calls", ["assessment_attempt_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_llm_calls_assessment_attempt_id", table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index("ix_assessment_attempts_assessment_id", table_name="assessment_attempts")
    op.drop_table("assessment_attempts")
    op.drop_index("ix_findings_assessment_id", table_name="findings")
    op.drop_table("findings")
    op.drop_index("ix_assessments_organization_id", table_name="assessments")
    op.drop_table("assessments")
