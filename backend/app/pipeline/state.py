"""Typed state and schemas for the M3 assessment pipeline.

GovernanceState is the LangGraph shared state. It carries only
msgpack-serializable values (str/int/float/bool/None/list/dict): Pydantic
payloads are dumped to dicts at node boundaries so any checkpointer can
persist the state without pickle.

Semantics note (audit-defensible wording): a finding tagged VERIFIED is
*citation/schema-verified* — the quote exists near-verbatim in retrieved
source text, the clause reference equals the assessed requirement, the schema
is valid and confidence clears a documented, uncalibrated policy threshold.
VERIFIED does NOT assert the verdict itself is correct; verdict accuracy is
measured in M6 and human review (M5) produces CONFIRMED.
"""

import operator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Annotated, TypedDict

from pydantic import BaseModel, ConfigDict, Field

# Bounded repair: the judge is called at most twice per requirement
# (initial attempt + one repair retry), then the pipeline abstains.
MAX_JUDGE_ATTEMPTS = 2


class Verdict(str, Enum):
    COMPLIANT = "compliant"
    PARTIAL = "partial"
    NON_COMPLIANT = "non_compliant"
    MISSING = "missing"  # no evidence found -> the system abstains


class FindingStatus(str, Enum):
    VERIFIED = "VERIFIED"    # citation/schema-verified (see module docstring)
    ABSTAINED = "ABSTAINED"
    # M5 adds CONFIRMED (human review)


class AbstainReason(str, Enum):
    MODEL_ABSTAINED = "model_abstained"          # valid `missing` verdict
    VERIFICATION_FAILED = "verification_failed"  # retry exhausted
    FUZZY_CITATION = "fuzzy_citation"            # near-match only: human review
    LOW_CONFIDENCE = "low_confidence"            # policy threshold, no retry
    LLM_ERROR = "llm_error"                      # all providers failed
    RATE_LIMITED = "rate_limited"                # throttled (429) — infra, not evidence


# Abstentions caused by provider infrastructure (outage, throttling), not by
# an evidentiary judgment. Kept next to the enum so every consumer (CLI, M4
# API) classifies identically.
INFRASTRUCTURE_ABSTAIN_REASONS = frozenset(
    {AbstainReason.LLM_ERROR.value, AbstainReason.RATE_LIMITED.value}
)


def is_infrastructure_failure(abstain_reason: str | None) -> bool:
    """True when an abstention reflects provider failure, not evidence."""
    return abstain_reason in INFRASTRUCTURE_ABSTAIN_REASONS


class AssessmentStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DraftFinding(BaseModel):
    """The judge's grounding contract: 5 fields, strictly validated.

    strict=True + extra="forbid" make Pydantic the real output gate — the
    provider's JSON mode only shapes the response, it does not validate it.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    # strict=False on this field only: strict mode rejects the JSON string
    # "compliant" for an Enum; membership is still fully validated.
    verdict: Verdict = Field(strict=False)
    policy_quote: str | None = Field(default=None, max_length=300)
    clause_ref: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


@dataclass
class QuoteMatch:
    """Where a claimed quote was found in the retrieved source."""

    chunk_id: str
    match_start: int  # page-relative raw offsets (chunk.char_start + local)
    match_end: int
    method: str       # "exact" | "fuzzy"
    score: float      # 100.0 for exact, partial_ratio for fuzzy


@dataclass
class VerificationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)        # all applicable errors
    repair_errors: list[str] = field(default_factory=list)  # errors fed to the retry
    match: QuoteMatch | None = None
    low_confidence: bool = False  # threshold miss — abstain without retry


@dataclass
class AssessmentResult:
    """CLI/API-facing outcome of one requirement run (not an ORM object)."""

    finding_id: str
    assessment_id: str
    requirement_id: str
    status: str
    verdict: str | None
    abstain_reason: str | None
    policy_quote: str | None
    clause_ref: str | None
    confidence: float | None
    rationale: str | None
    match: QuoteMatch | None
    attempts: int
    final_model: str | None
    final_provider: str | None
    retrieved: list[dict]
    attempt_history: list[dict]
    audit_log: list[dict]


class GovernanceState(TypedDict, total=False):
    # inputs
    assessment_id: str    # persistence key — never derived by parsing thread_id
    organization_id: str
    requirement_id: str
    requirement_text: str
    corpus_version: str
    retrieval_k: int
    # node outputs
    retrieved: list[dict]              # serialized RetrievedItem provenance
    draft: dict | None                 # last raw draft payload (parsed or None)
    raw_response: str | None           # last raw model output
    judge_attempts: int                # counts judge attempts, not provider calls
    llm_failed: bool                   # all providers failed on the last attempt
    llm_failed_reason: str | None      # "rate_limited" | "llm_error" (from calls)
    fuzzy_candidate: dict | None       # last fuzzy QuoteMatch, kept across retries
    verification_errors: list[str]     # repair feedback for the next judge attempt
    finding: dict | None               # terminal finding payload
    final_model: str | None
    final_provider: str | None
    # append-only provenance (reducer-backed: retries never clobber history)
    audit_log: Annotated[list[dict], operator.add]
    attempt_history: Annotated[list[dict], operator.add]


def utcnow_iso() -> str:
    from datetime import timezone

    return datetime.now(timezone.utc).isoformat()
