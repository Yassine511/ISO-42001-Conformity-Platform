from app.models._shared import *  # noqa: F401,F403
from app.models._shared import _now, _uuid  # noqa: F401

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
    # M8 finding drill-down: live pointer (SET NULL on finding deletion) +
    # IMMUTABLE context snapshot captured at ask time — the API/UI reads the
    # snapshot, so the chip survives deletion and later re-reviews and never
    # depends on ChatLlmCall request-payload provenance.
    finding_id: Mapped[str | None] = mapped_column(
        ForeignKey("findings.id", ondelete="SET NULL"), nullable=True
    )
    finding_context_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
