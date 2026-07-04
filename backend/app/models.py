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
    Integer,
    String,
    Text,
    UniqueConstraint,
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
    final_model: Mapped[str | None] = mapped_column(String(100), nullable=True)  # NULL on llm_error
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
    requested_model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    reported_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_messages: Mapped[list] = mapped_column(JSON, default=list)
    response_format: Mapped[dict] = mapped_column(JSON, default=dict)
    temperature: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attempt: Mapped[AssessmentAttempt] = relationship(back_populates="llm_calls")
