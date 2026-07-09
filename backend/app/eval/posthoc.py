"""Verification-gate diagnostic: post-hoc re-verification of attempt-1 drafts.

This is NOT an ablation ("pipeline without verifier"): a final VERIFIED
finding structurally requires the same exact-match verifier, so the post-gate
unsupported rate is an invariant check, not an empirical result. What this
module measures is first-draft citation integrity — how often the judge's
FIRST draft cited text that the deterministic verifier cannot locate exactly
in the retrieved sources — together with the gate outcomes (repaired /
abstained / verified). The report may say the gate blocked N unsupported
draft citations from being displayed; it must never claim a measured
"hallucination reduction" (frozen rules §4).

Recovery path: attempt row #1 -> last SUCCESS llm_call.raw_response (for
SUCCESS calls this IS the message content — the same value nodes'
crash-recovery reuses) -> the same parse as nodes._parse_draft -> the same
verifier.find_quote_in_retrieved over the finding's persisted `retrieved`
provenance (retrieve runs once per requirement, so attempt 1 saw exactly it).
"""

from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AssessmentAttempt
from app.pipeline import llm as llm_service
from app.pipeline.nodes import _parse_draft
from app.pipeline.state import Verdict
from app.pipeline.verifier import (
    MAX_QUOTE_LEN,
    MIN_QUOTE_LEN,
    find_quote_in_retrieved,
    normalize,
)

# Outcome kinds for attempt 1 (frozen rules §4)
KIND_ASSERTED = "asserted"            # parsed draft with verdict != missing
KIND_MISSING_DRAFT = "missing_draft"  # parsed draft, verdict == missing
KIND_UNPARSEABLE = "unparseable"      # SUCCESS call, content failed parse/schema
KIND_NO_SUCCESS_CALL = "no_success_call"  # no successful provider call at attempt 1

# Failure modes for an asserted draft's citation
FAIL_NOT_FOUND = "not_found"
FAIL_FUZZY_ONLY = "fuzzy_only"
FAIL_NULL_QUOTE = "null_quote"
FAIL_BAD_LENGTH = "bad_length"


@dataclass
class Attempt1Outcome:
    requirement_id: str
    kind: str
    provider: str | None
    model: str | None
    # only meaningful when kind == "asserted":
    unsupported: bool | None = None
    failure_mode: str | None = None
    match_method: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def recover_attempt1_content(
    db: Session, assessment_id: str, requirement_id: str
) -> tuple[str | None, str | None, str | None]:
    """(content, provider, model) of attempt 1's last SUCCESS call, or Nones.

    Provenance comes from the llm_calls rows of the attempt actually used —
    Finding.final_model describes the FINAL attempt and must never be used
    for attempt-1 provenance (frozen rules §4).
    """
    attempt = db.scalars(
        select(AssessmentAttempt).where(
            AssessmentAttempt.assessment_id == assessment_id,
            AssessmentAttempt.requirement_id == requirement_id,
            AssessmentAttempt.attempt_number == 1,
        )
    ).first()
    if attempt is None:
        return None, None, None
    for call in sorted(attempt.llm_calls, key=lambda c: c.call_number, reverse=True):
        if call.status == llm_service.CALL_SUCCESS and call.raw_response:
            return (
                call.raw_response,
                call.provider,
                call.reported_model or call.requested_model,
            )
    return None, None, None


def classify_attempt1(
    requirement_id: str,
    content: str | None,
    retrieved: list[dict],
    *,
    provider: str | None = None,
    model: str | None = None,
) -> Attempt1Outcome:
    """Classify one attempt-1 draft using the SAME verifier the gate uses."""
    outcome = Attempt1Outcome(
        requirement_id=requirement_id, kind=KIND_NO_SUCCESS_CALL,
        provider=provider, model=model,
    )
    if content is None:
        return outcome

    draft, parse_errors = _parse_draft(content)
    if draft is None:
        outcome.kind = KIND_UNPARSEABLE
        return outcome

    if draft.get("verdict") == Verdict.MISSING.value:
        outcome.kind = KIND_MISSING_DRAFT
        return outcome

    outcome.kind = KIND_ASSERTED
    quote = (draft.get("policy_quote") or "").strip()
    if not quote:
        outcome.unsupported = True
        outcome.failure_mode = FAIL_NULL_QUOTE
        return outcome

    nq = normalize(quote)
    if len(nq.text) < MIN_QUOTE_LEN or len(quote) > MAX_QUOTE_LEN:
        outcome.unsupported = True
        outcome.failure_mode = FAIL_BAD_LENGTH
        return outcome

    match = find_quote_in_retrieved(nq, retrieved)
    if match is None:
        outcome.unsupported = True
        outcome.failure_mode = FAIL_NOT_FOUND
    elif match.method != "exact":
        # a fuzzy near-match is never displayable by the gate — counted as
        # unsupported but broken out separately in the aggregate
        outcome.unsupported = True
        outcome.failure_mode = FAIL_FUZZY_ONLY
        outcome.match_method = match.method
    else:
        outcome.unsupported = False
        outcome.match_method = match.method
    return outcome


def gate_diagnostic(outcomes: list[Attempt1Outcome], findings: dict[str, dict]) -> dict:
    """Aggregate the verification-gate diagnostic (frozen rules §4).

    `findings` maps requirement_id -> final finding dict (status/verdict/
    abstain_reason/attempts) for the SAME population as `outcomes`.
    """
    from .stats import Metric  # local import: avoid cycle at module load

    n = len(outcomes)
    by_kind = {k: 0 for k in (KIND_ASSERTED, KIND_MISSING_DRAFT, KIND_UNPARSEABLE, KIND_NO_SUCCESS_CALL)}
    failure_modes: dict[str, int] = {}
    unsupported = 0
    asserted = 0
    for o in outcomes:
        by_kind[o.kind] += 1
        if o.kind == KIND_ASSERTED:
            asserted += 1
            if o.unsupported:
                unsupported += 1
                failure_modes[o.failure_mode or "?"] = (
                    failure_modes.get(o.failure_mode or "?", 0) + 1
                )

    verified = sum(1 for f in findings.values() if f.get("status") == "VERIFIED")
    abstained = sum(1 for f in findings.values() if f.get("status") == "ABSTAINED")
    repaired = sum(
        1
        for f in findings.values()
        if f.get("status") == "VERIFIED" and (f.get("attempts") or 1) >= 2
    )
    return {
        "n": n,
        "attempt1_kinds": by_kind,
        "attempt1_unsupported_over_asserted": (
            Metric.of(unsupported, asserted).to_dict() if asserted else None
        ),
        "attempt1_unsupported_over_all": Metric.of(unsupported, n).to_dict() if n else None,
        "attempt1_failure_modes": failure_modes,
        "gate_outcomes": {
            "verified": verified,
            "repaired": repaired,
            "abstained": abstained,
        },
    }


def reverify_final(finding_row) -> bool:
    """Invariant check on a final VERIFIED finding: its displayed quote must
    still locate EXACTLY in its own persisted retrieval snapshot. Returns True
    when the invariant holds. Any False across a run is a verifier bug and
    blocks the report (frozen rules §4)."""
    if finding_row.status != "VERIFIED":
        raise ValueError("reverify_final ne s'applique qu'aux constats VERIFIED")
    if finding_row.verdict == Verdict.MISSING.value:
        # structurally impossible: a missing verdict never verifies
        return False
    quote = (finding_row.policy_quote or "").strip()
    if not quote:
        return False
    match = find_quote_in_retrieved(quote, finding_row.retrieved or [])
    return match is not None and match.method == "exact"
