"""M4 chat logging: conversations, chat_messages, chat_llm_calls.

chat_llm_calls mirrors llm_calls instead of making llm_calls.assessment_attempt_id
nullable: altering populated provenance schema already cost a repair revision
(0006); a parallel table is zero-risk to existing rows and keeps each table's
constraints exact.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conversations_organization_id", "conversations", ["organization_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("abstain_reason", sa.String(50), nullable=True),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("evidence_scope", sa.String(10), nullable=True),
        sa.Column("claims", sa.JSON(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("stripped_citations", sa.JSON(), nullable=False),
        sa.Column("retrieval_notes", sa.JSON(), nullable=True),
        sa.Column("retrieved_policy", sa.JSON(), nullable=False),
        sa.Column("retrieved_kb", sa.JSON(), nullable=False),
        sa.Column("raw_draft", sa.Text(), nullable=True),
        sa.Column("attempts", sa.JSON(), nullable=False),
        sa.Column("draft_attempts", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("corpus_version", sa.String(20), nullable=False),
        sa.Column("final_model", sa.Text(), nullable=True),
        sa.Column("final_provider", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('ANSWERED', 'ABSTAINED')", name="ck_chat_messages_status"
        ),
        sa.CheckConstraint(
            "abstain_reason IS NULL OR abstain_reason IN "
            "('model_abstained', 'verification_failed', 'fuzzy_citation', "
            "'low_confidence', 'llm_error', 'rate_limited')",
            name="ck_chat_messages_abstain_reason",
        ),
        sa.CheckConstraint(
            "evidence_scope IS NULL OR evidence_scope IN ('policy', 'kb_only', 'mixed')",
            name="ck_chat_messages_evidence_scope",
        ),
        sa.CheckConstraint(
            "(status = 'ANSWERED' AND abstain_reason IS NULL AND evidence_scope IS NOT NULL) "
            "OR (status = 'ABSTAINED' AND abstain_reason IS NOT NULL AND evidence_scope IS NULL)",
            name="ck_chat_messages_status_coherence",
        ),
        sa.CheckConstraint(
            "draft_attempts >= 0 AND draft_attempts <= 2", name="ck_chat_messages_attempts"
        ),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])

    op.create_table(
        "chat_llm_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "chat_message_id",
            sa.String(36),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("call_number", sa.Integer(), nullable=False),
        sa.Column("draft_attempt_number", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("requested_model", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reported_model", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("request_messages", sa.JSON(), nullable=False),
        sa.Column("response_format", sa.JSON(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("chat_message_id", "call_number", name="uq_chat_llm_calls_key"),
        sa.CheckConstraint(
            "status IN ('SUCCESS', 'HTTP_ERROR', 'NETWORK_ERROR', 'BAD_RESPONSE', "
            "'SKIPPED_NO_KEY')",
            name="ck_chat_llm_calls_status",
        ),
    )
    op.create_index("ix_chat_llm_calls_chat_message_id", "chat_llm_calls", ["chat_message_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_llm_calls_chat_message_id", table_name="chat_llm_calls")
    op.drop_table("chat_llm_calls")
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_conversations_organization_id", table_name="conversations")
    op.drop_table("conversations")
