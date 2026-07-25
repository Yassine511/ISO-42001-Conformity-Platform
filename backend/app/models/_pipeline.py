from app.models._shared import *  # noqa: F401,F403
from app.models._shared import _now, _uuid  # noqa: F401

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
    are valid — NOT that the verdict is correct (M6 measures that; human
    review produces review_status=CONFIRMED).

    Write-once invariant (the trust layer's audit story): every AI-produced
    column (status, verdict, rationale, policy_quote, match_*, retrieved,
    audit_log, ...) is written only by the pipeline and never modified
    afterwards. The human decision lives exclusively in the review_* columns
    (current-state projection) and the immutable finding_reviews history —
    a CONFIRMED finding always shows the untouched AI draft next to the
    human decision. The effective verdict of a CONFIRMED finding is
    human_verdict (approve snapshots the AI verdict into it)."""

    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("assessment_id", "requirement_id", name="uq_findings_assessment_req"),
        CheckConstraint("status IN ('VERIFIED', 'ABSTAINED')", name="ck_findings_status"),
        CheckConstraint(
            "review_status IN ('PENDING', 'CONFIRMED')", name="ck_findings_review_status"
        ),
        CheckConstraint(
            "review_action IS NULL OR review_action IN ('approve', 'edit', 'override')",
            name="ck_findings_review_action",
        ),
        CheckConstraint(
            "human_verdict IS NULL OR human_verdict IN "
            "('compliant', 'partial', 'non_compliant', 'missing')",
            name="ck_findings_human_verdict",
        ),
        CheckConstraint(
            "(review_status = 'PENDING' AND review_action IS NULL "
            "AND human_verdict IS NULL AND reviewed_at IS NULL) "
            "OR (review_status = 'CONFIRMED' AND review_action IS NOT NULL "
            "AND human_verdict IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_findings_review_coherence",
        ),
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
    # Requirement snapshot at assessment time (M5 review must not depend on
    # the live KB); NULL for findings persisted before revision 0012 — the
    # detail endpoint then falls back to the live KB only when corpus_version
    # still matches, flagging corpus_mismatch otherwise.
    requirement_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Human review projection (CURRENT decision; full history in
    # finding_reviews). Written only by the review endpoint, never the
    # pipeline; AI columns above are never written by review.
    review_status: Mapped[str] = mapped_column(
        String(20), default="PENDING", server_default=text("'PENDING'")
    )
    review_action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    human_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    human_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
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
    reviews: Mapped[list["FindingReview"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", order_by="FindingReview.sequence"
    )


class FindingReview(Base):
    """One human review decision — immutable, append-only (rows are never
    updated or deleted; a re-review appends the next sequence). reviewer_label
    is a free-text, EXPLICITLY UNVERIFIED attribution: the project has no
    identity layer by design."""

    __tablename__ = "finding_reviews"
    __table_args__ = (
        UniqueConstraint("finding_id", "sequence", name="uq_finding_reviews_sequence"),
        CheckConstraint(
            "action IN ('approve', 'edit', 'override')", name="ck_finding_reviews_action"
        ),
        CheckConstraint(
            "human_verdict IN ('compliant', 'partial', 'non_compliant', 'missing')",
            name="ck_finding_reviews_verdict",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    finding_id: Mapped[str] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)  # 1-based
    action: Mapped[str] = mapped_column(String(20))
    human_verdict: Mapped[str] = mapped_column(String(20))
    human_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    finding: Mapped[Finding] = relationship(back_populates="reviews")


class AssessmentAttempt(Base):
    """One semantic judge attempt (LLM draft + verification)."""

    __tablename__ = "assessment_attempts"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "requirement_id", "attempt_number", name="uq_attempts_key"
        ),
        # M8 typed telemetry: legacy_unclassified is a first-class value (a
        # pre-0015 parsed_ok=False row cannot distinguish schema_invalid from
        # provider_failure and is NEVER reclassified by string matching)
        CheckConstraint(
            "attempt_outcome IN ('parsed', 'schema_invalid', 'provider_failure', "
            "'legacy_unclassified')",
            name="ck_assessment_attempts_outcome",
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
    # M8 typed outcome, written by the judge (parsed | schema_invalid |
    # provider_failure); 'legacy_unclassified' only via the 0015 backfill.
    attempt_outcome: Mapped[str] = mapped_column(
        String(20), default="legacy_unclassified",
        server_default=text("'legacy_unclassified'"),
    )
    # written by the VERIFY node (errors don't exist when the judge writes)
    verifier_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # M8 typed codes, parallel authority to verifier_errors: [] = verified
    # attempt with no error; NULL = legacy row (codes unavailable) or the
    # verify node has not completed this attempt.
    verifier_error_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
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
