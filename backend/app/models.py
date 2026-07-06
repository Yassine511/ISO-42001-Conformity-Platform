import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PARSED = "parsed"
    FAILED = "failed"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    documents: Mapped[list["Document"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default=DocumentStatus.UPLOADED.value)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    # Provenance/lifecycle anchors for M2 indexing: detect re-uploads of the
    # same content and parses produced by an outdated extractor. checksum is
    # NULL only for legacy pre-M2 rows; uniqueness per org is DB-enforced so
    # concurrent identical uploads cannot both pass the API pre-check.
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parser_version: Mapped[str] = mapped_column(String(20), default="")

    __table_args__ = (UniqueConstraint("organization_id", "checksum", name="uq_documents_org_checksum"),)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    organization: Mapped[Organization] = relationship(back_populates="documents")
    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentPage.page_number"
    )


class DocumentPage(Base):
    """Parsed text, one row per page (PDF) or per document (DOCX/TXT).

    This is the provenance anchor: chunks (M2) and citations (M3+) will
    reference document_id + page_number + character offsets into `text`.
    """

    __tablename__ = "document_pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    document: Mapped[Document] = relationship(back_populates="pages")


class Chunk(Base):
    """Retrieval unit over a document page span.

    id is content-addressed over (document_id, parser_version, chunker_version,
    page, offsets) — reindexing is idempotent, and ids can never collide across
    documents or organizations. char_start/char_end slice DocumentPage.text
    exactly: text == page_text[char_start:char_end].
    """

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    document: Mapped[Document] = relationship()


# --------------------------------------------------------------- M3 pipeline
# Provenance trail of the assessment pipeline. One assessment groups many
# findings (one per requirement); each finding is backed by judge attempts
# (assessment_attempts) which are backed by provider calls (llm_calls) — one
# judge attempt may span Mistral 429 -> Groq success, hence the child table.


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'FAILED')", name="ck_assessments_status"
        ),
        CheckConstraint(
            "retrieval_k >= 1 AND retrieval_k <= 20", name="ck_assessments_retrieval_k"
        ),
        # DB-enforced single-RUNNING-per-org invariant: the API pre-check under
        # the org row lock gives the friendly 409, this partial unique index is
        # the guarantee under concurrency (IntegrityError -> same 409).
        Index(
            "uq_assessments_one_running",
            "organization_id",
            unique=True,
            postgresql_where=text("status = 'RUNNING'"),
            sqlite_where=text("status = 'RUNNING'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    corpus_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    # Run manifest: the requirement ids this assessment was created to cover.
    # Resume validates against it so a crashed A.9.2 run cannot be "resumed"
    # with A.4.5 and finalized COMPLETED while A.9.2 stays unfinished.
    requirement_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Frozen run contract (reproducibility): retrieval depth and the exact
    # document set (ids, checksums, parser/chunker versions, chunk count) as
    # indexed at creation. NULL document_manifest = legacy pre-0011 row; the
    # API exposes manifest_complete and refuses to resume such rows.
    retrieval_k: Mapped[int] = mapped_column(Integer, default=6, server_default=text("6"))
    document_manifest: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Cooperative cancellation: the runner re-reads this between requirements
    # and finalizes FAILED («Annulée par l'utilisateur.») when set.
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    findings: Mapped[list["Finding"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class Finding(Base):
    """Terminal, citation/schema-verified (or abstained) outcome for one
    requirement. VERIFIED asserts the citation exists and the schema/clause
    are valid — NOT that the verdict is correct (M6 measures that; M5 human
    review produces CONFIRMED)."""

    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("assessment_id", "requirement_id", name="uq_findings_assessment_req"),
        CheckConstraint("status IN ('VERIFIED', 'ABSTAINED')", name="ck_findings_status"),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('compliant', 'partial', 'non_compliant', 'missing')",
            name="ck_findings_verdict",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_findings_confidence",
        ),
        CheckConstraint(
            "abstain_reason IS NULL OR abstain_reason IN "
            "('model_abstained', 'verification_failed', 'fuzzy_citation', "
            "'low_confidence', 'llm_error', 'rate_limited')",
            name="ck_findings_abstain_reason",
        ),
        CheckConstraint(
            "match_method IS NULL OR match_method IN ('exact', 'fuzzy')",
            name="ck_findings_match_method",
        ),
        CheckConstraint("attempts >= 0 AND attempts <= 2", name="ck_findings_attempts"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    policy_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    clause_ref: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    # citation match provenance (page-relative raw offsets, M5 highlighting)
    matched_chunk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    abstain_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer)  # judge attempts, not provider calls
    # Text, not VARCHAR: derived from the provider-reported model name, which is
    # provider-controlled — a >100-char value must never DataError the finding
    # write. NULL on llm_error.
    final_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    retrieved: Mapped[list] = mapped_column(JSON, default=list)
    # terminal per-node audit trail (retrieve->judge->verify events); NULL for
    # findings persisted before revision 0007
    audit_log: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    assessment: Mapped[Assessment] = relationship(back_populates="findings")


class AssessmentAttempt(Base):
    """One semantic judge attempt (LLM draft + verification)."""

    __tablename__ = "assessment_attempts"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "requirement_id", "attempt_number", name="uq_attempts_key"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[str] = mapped_column(String(20))
    attempt_number: Mapped[int] = mapped_column(Integer)  # 1-based
    prompt_version: Mapped[str] = mapped_column(String(20))
    parsed_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    # written by the VERIFY node (errors don't exist when the judge writes)
    verifier_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    llm_calls: Mapped[list["LlmCall"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan", order_by="LlmCall.call_number"
    )


class LlmCall(Base):
    """One HTTP attempt against one provider within a judge attempt.
    Request-side fields make old results reproducible after prompt changes."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        UniqueConstraint("assessment_attempt_id", "call_number", name="uq_llm_calls_key"),
        CheckConstraint(
            "status IN ('SUCCESS', 'HTTP_ERROR', 'NETWORK_ERROR', 'BAD_RESPONSE', "
            "'SKIPPED_NO_KEY')",
            name="ck_llm_calls_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    assessment_attempt_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_attempts.id", ondelete="CASCADE"), index=True
    )
    call_number: Mapped[int] = mapped_column(Integer)  # 1-based
    # per-call prompt version: one attempt can mix a failed residue call
    # (older prompt) with a fresh call after crash recovery
    prompt_version: Mapped[str] = mapped_column(String(20), default="")
    provider: Mapped[str] = mapped_column(String(20))
    # Text, not VARCHAR: requested_model is config-controlled and reported_model
    # is provider-controlled — neither may DataError the call/finding write.
    requested_model: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    reported_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_messages: Mapped[list] = mapped_column(JSON, default=list)
    response_format: Mapped[dict] = mapped_column(JSON, default=dict)
    temperature: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attempt: Mapped[AssessmentAttempt] = relationship(back_populates="llm_calls")


# --------------------------------------------------------------- M4 chat
# Conversation log of the grounded chat copilot. One chat_messages row is one
# Q&A exchange (question + its verified answer or abstention) — the audit unit.
# Single-shot semantics: no history is fed to the LLM; conversations only group
# exchanges for the audit trail (multi-turn later = more rows, no new columns).
# chat_llm_calls deliberately mirrors llm_calls instead of generalizing it:
# amending populated provenance schema already cost a repair revision (0006).


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # display only: first question, truncated
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    """One Q&A exchange with full trust-layer provenance.

    `answer` is the persisted user-visible text (assembled verified answer or
    the final abstention text) — GET replay never re-renders from templates or
    the KB. Citations snapshot quote text/filename/page/offsets, so provenance
    survives document deletion (see api/documents.py deletion guard comment)."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("status IN ('ANSWERED', 'ABSTAINED')", name="ck_chat_messages_status"),
        CheckConstraint(
            "abstain_reason IS NULL OR abstain_reason IN "
            "('model_abstained', 'verification_failed', 'fuzzy_citation', "
            "'low_confidence', 'llm_error', 'rate_limited')",
            name="ck_chat_messages_abstain_reason",
        ),
        CheckConstraint(
            "evidence_scope IS NULL OR evidence_scope IN ('policy', 'kb_only', 'mixed')",
            name="ck_chat_messages_evidence_scope",
        ),
        # status semantics are DB-enforced: an ANSWERED row always has a scope
        # and no abstain reason; an ABSTAINED row always has a reason, no scope.
        CheckConstraint(
            "(status = 'ANSWERED' AND abstain_reason IS NULL AND evidence_scope IS NOT NULL) "
            "OR (status = 'ABSTAINED' AND abstain_reason IS NOT NULL AND evidence_scope IS NULL)",
            name="ck_chat_messages_status_coherence",
        ),
        CheckConstraint(
            "draft_attempts >= 0 AND draft_attempts <= 2", name="ck_chat_messages_attempts"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    abstain_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    answer: Mapped[str] = mapped_column(Text)
    evidence_scope: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # surviving claims (text, kind, citation ids) + dropped claims with the
    # citation ids that failed them
    claims: Mapped[list] = mapped_column(JSON, default=list)
    # verified citations with full QuoteMatch / KB hydration provenance
    citations: Mapped[list] = mapped_column(JSON, default=list)
    # stripped CitationOutcomes incl. fuzzy candidates and French errors
    stripped_citations: Mapped[list] = mapped_column(JSON, default=list)
    # model-authored per-passage reasons on the no_evidence path (UNVERIFIED)
    retrieval_notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    retrieved_policy: Mapped[list] = mapped_column(JSON, default=list)
    retrieved_kb: Mapped[list] = mapped_column(JSON, default=list)
    raw_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    # per semantic attempt: {attempt_number, parsed_ok, validation_errors}
    attempts: Mapped[list] = mapped_column(JSON, default=list)
    draft_attempts: Mapped[int] = mapped_column(Integer)
    prompt_version: Mapped[str] = mapped_column(String(20))
    corpus_version: Mapped[str] = mapped_column(String(20))
    # Text, not VARCHAR: provider-controlled (0008 rationale)
    final_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    llm_calls: Mapped[list["ChatLlmCall"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", order_by="ChatLlmCall.call_number"
    )


class ChatLlmCall(Base):
    """One HTTP attempt against one provider within a chat exchange. Mirrors
    llm_calls; draft_attempt_number marks the semantic attempt boundary
    (variable 429 retries make call_number alone insufficient)."""

    __tablename__ = "chat_llm_calls"
    __table_args__ = (
        UniqueConstraint("chat_message_id", "call_number", name="uq_chat_llm_calls_key"),
        CheckConstraint(
            "status IN ('SUCCESS', 'HTTP_ERROR', 'NETWORK_ERROR', 'BAD_RESPONSE', "
            "'SKIPPED_NO_KEY')",
            name="ck_chat_llm_calls_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    chat_message_id: Mapped[str] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    call_number: Mapped[int] = mapped_column(Integer)  # 1-based, continues across retry
    draft_attempt_number: Mapped[int] = mapped_column(Integer)  # 1 or 2
    prompt_version: Mapped[str] = mapped_column(String(20), default="")
    provider: Mapped[str] = mapped_column(String(20))
    requested_model: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    reported_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_messages: Mapped[list] = mapped_column(JSON, default=list)
    response_format: Mapped[dict] = mapped_column(JSON, default=dict)
    temperature: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    message: Mapped[ChatMessage] = relationship(back_populates="llm_calls")
