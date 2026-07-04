"""LangGraph nodes ① Retrieve ② Judge ③ Verify (M3).

Node factories take a session FACTORY, not a session: a durable graph must
not capture a request-scoped SQLAlchemy session (M5 resume would reuse a
closed one). Each node opens a short-lived session for its own DB work.

The verify node is the single routing authority — every judge outcome
(valid draft, malformed output, `missing` verdict, total LLM failure) flows
through it. Routing precedence lives in route_after_verify().
"""

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AssessmentAttempt, Finding, LlmCall
from app.pipeline import llm as llm_service
from app.pipeline.prompts import PROMPT_VERSION, build_judge_messages, build_repair_messages
from app.pipeline.state import (
    MAX_JUDGE_ATTEMPTS,
    AbstainReason,
    DraftFinding,
    FindingStatus,
    GovernanceState,
    Verdict,
    utcnow_iso,
)
from app.pipeline.verifier import verify
from app.services.retrieval import hybrid_search

SessionFactory = Callable[[], Session]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(node: str, event: str, **details) -> dict:
    return {"node": node, "event": event, "at": utcnow_iso(), **details}


# ---------------------------------------------------------------- retrieve


def make_retrieve_node(session_factory: SessionFactory):
    def retrieve_node(state: GovernanceState) -> dict:
        db = session_factory()
        try:
            items = hybrid_search(
                db,
                state["organization_id"],
                state["requirement_text"],
                k=state["retrieval_k"],
                scope="policy",
            )
        finally:
            db.close()
        retrieved = [asdict(item) for item in items]
        return {
            "retrieved": retrieved,
            "audit_log": [
                _audit(
                    "retrieve",
                    "evidence_retrieved",
                    count=len(retrieved),
                    result_ids=[r["result_id"] for r in retrieved],
                )
            ],
        }

    return retrieve_node


# ---------------------------------------------------------------- judge


def _parse_draft(content: str) -> tuple[dict | None, list[str]]:
    """Parse + strictly validate model output. Errors become retry feedback."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        return None, [f"JSON invalide : {exc}. Rends un objet JSON valide et complet."]
    try:
        draft = DraftFinding.model_validate(payload)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return None, [f"schéma invalide : {details}. Respecte exactement le schéma demandé."]
    return draft.model_dump(mode="json"), []


def make_judge_node(session_factory: SessionFactory):
    def judge_node(state: GovernanceState) -> dict:
        attempt_number = state.get("judge_attempts", 0) + 1
        started = _now()

        base_messages = build_judge_messages(
            state["requirement_id"], state["requirement_text"], state["retrieved"]
        )
        prior_errors = state.get("verification_errors") or []
        if attempt_number > 1 and prior_errors:
            messages = build_repair_messages(base_messages, state.get("raw_response"), prior_errors)
        else:
            messages = base_messages

        outcome = llm_service.complete_json(
            messages, json_schema=DraftFinding.model_json_schema()
        )

        if outcome.content is None:
            draft, parse_errors = None, []
        else:
            draft, parse_errors = _parse_draft(outcome.content)

        final_call = outcome.final_call
        # persist the semantic attempt + every provider call
        db = session_factory()
        try:
            attempt = AssessmentAttempt(
                assessment_id=state["assessment_id"],
                requirement_id=state["requirement_id"],
                attempt_number=attempt_number,
                prompt_version=PROMPT_VERSION,
                parsed_ok=draft is not None,
                started_at=started,
            )
            db.add(attempt)
            db.flush()
            for i, call in enumerate(outcome.calls, start=1):
                db.add(
                    LlmCall(
                        assessment_attempt_id=attempt.id,
                        call_number=i,
                        provider=call.provider,
                        requested_model=call.requested_model,
                        status=call.status,
                        reported_model=call.reported_model,
                        http_status=call.http_status,
                        error=call.error,
                        raw_response=call.raw_response,
                        request_messages=call.request_messages,
                        response_format=call.response_format,
                        temperature=call.temperature,
                        started_at=datetime.fromisoformat(call.started_at),
                        finished_at=datetime.fromisoformat(call.finished_at)
                        if call.finished_at
                        else None,
                    )
                )
            db.commit()
        finally:
            db.close()

        # A new attempt starts clean: stale draft/errors must never leak into
        # the next verify pass (parse errors, if any, are this attempt's own).
        return {
            "draft": draft,
            "raw_response": outcome.content,
            "judge_attempts": attempt_number,
            "llm_failed": outcome.content is None,
            "verification_errors": parse_errors,
            "final_model": final_call.reported_model or final_call.requested_model
            if final_call
            else None,
            "final_provider": final_call.provider if final_call else None,
            "attempt_history": [
                {
                    "attempt": attempt_number,
                    "prompt_version": PROMPT_VERSION,
                    "parsed_ok": draft is not None,
                    "llm_error": outcome.error,
                    "calls": [
                        {
                            "provider": c.provider,
                            "requested_model": c.requested_model,
                            "reported_model": c.reported_model,
                            "status": c.status,
                            "http_status": c.http_status,
                        }
                        for c in outcome.calls
                    ],
                    "raw_response": outcome.content,
                }
            ],
            "audit_log": [
                _audit(
                    "judge",
                    "draft_produced" if draft is not None else "draft_failed",
                    attempt=attempt_number,
                    provider=final_call.provider if final_call else None,
                )
            ],
        }

    return judge_node


# ---------------------------------------------------------------- verify


def _terminal_finding(state: GovernanceState, *, status: str, abstain_reason: str | None,
                      errors: list[str], match=None) -> dict:
    draft = state.get("draft") or {}
    return {
        "requirement_id": state["requirement_id"],
        "status": status,
        "verdict": draft.get("verdict"),
        "policy_quote": draft.get("policy_quote"),
        "clause_ref": draft.get("clause_ref"),
        "confidence": draft.get("confidence"),
        "rationale": draft.get("rationale"),
        "abstain_reason": abstain_reason,
        "errors": errors,
        "match": asdict(match) if match is not None else None,
        "attempts": state.get("judge_attempts", 0),
    }


def _record_verifier_errors(
    session_factory: SessionFactory, state: GovernanceState, errors: list[str]
) -> None:
    """The verify node completes the attempt row the judge opened."""
    db = session_factory()
    try:
        attempt = db.scalars(
            select(AssessmentAttempt).where(
                AssessmentAttempt.assessment_id == state["assessment_id"],
                AssessmentAttempt.requirement_id == state["requirement_id"],
                AssessmentAttempt.attempt_number == state.get("judge_attempts", 0),
            )
        ).first()
        if attempt is not None:
            attempt.verifier_errors = errors
            attempt.finished_at = _now()
            db.commit()
    finally:
        db.close()


def _persist_finding(session_factory: SessionFactory, state: GovernanceState, finding: dict) -> str:
    """Idempotent terminal upsert keyed on (assessment_id, requirement_id):
    checkpoint re-execution must not duplicate findings."""
    match = finding.get("match") or {}
    db = session_factory()
    try:
        row = db.scalars(
            select(Finding).where(
                Finding.assessment_id == state["assessment_id"],
                Finding.requirement_id == state["requirement_id"],
            )
        ).first()
        if row is None:
            row = Finding(
                assessment_id=state["assessment_id"],
                requirement_id=state["requirement_id"],
                status=finding["status"],
                attempts=finding["attempts"],
                retrieved=state.get("retrieved") or [],
            )
            db.add(row)
        row.status = finding["status"]
        row.verdict = finding.get("verdict")
        row.policy_quote = finding.get("policy_quote")
        row.clause_ref = finding.get("clause_ref")
        row.confidence = finding.get("confidence")
        row.rationale = finding.get("rationale")
        row.matched_chunk_id = match.get("chunk_id")
        row.match_start = match.get("match_start")
        row.match_end = match.get("match_end")
        row.match_method = match.get("method")
        row.match_score = match.get("score")
        row.abstain_reason = finding.get("abstain_reason")
        row.attempts = finding["attempts"]
        row.final_model = state.get("final_model")
        row.final_provider = state.get("final_provider")
        row.retrieved = state.get("retrieved") or []
        db.commit()
        return row.id
    finally:
        db.close()


def make_verify_node(session_factory: SessionFactory):
    def verify_node(state: GovernanceState) -> dict:
        # Precedence 1: total LLM failure — nothing to verify, nothing to retry.
        if state.get("llm_failed"):
            finding = _terminal_finding(
                state,
                status=FindingStatus.ABSTAINED.value,
                abstain_reason=AbstainReason.LLM_ERROR.value,
                errors=["tous les fournisseurs LLM ont échoué"],
            )
            _record_verifier_errors(session_factory, state, finding["errors"])
            fid = _persist_finding(session_factory, state, finding)
            finding["finding_id"] = fid
            return {
                "finding": finding,
                "audit_log": [_audit("verify", "abstained", reason="llm_error")],
            }

        draft_payload = state.get("draft")
        if draft_payload is None:
            # parse/schema failure — the judge pre-populated the errors
            errors = state.get("verification_errors") or ["réponse du modèle invalide"]
            return _route_failure(session_factory, state, errors, repair_errors=errors)

        draft = DraftFinding.model_validate(draft_payload)
        result = verify(draft, state.get("retrieved") or [], state["requirement_id"])
        _record_verifier_errors(session_factory, state, result.errors)

        # Precedence 2: fully valid `missing` — the model abstaining is a
        # valid outcome, not an error. (An invalid `missing` — wrong clause —
        # has repair_errors and falls through to the retry path.)
        if draft.verdict == Verdict.MISSING and not result.repair_errors:
            finding = _terminal_finding(
                state,
                status=FindingStatus.ABSTAINED.value,
                abstain_reason=AbstainReason.MODEL_ABSTAINED.value,
                errors=result.errors,
            )
            fid = _persist_finding(session_factory, state, finding)
            finding["finding_id"] = fid
            return {
                "finding": finding,
                "audit_log": [_audit("verify", "abstained", reason="model_abstained")],
            }

        # Precedence 3: low confidence as the ONLY failure — abstain without
        # retry (repair feedback would only teach confidence inflation).
        if result.low_confidence and not result.repair_errors:
            finding = _terminal_finding(
                state,
                status=FindingStatus.ABSTAINED.value,
                abstain_reason=AbstainReason.LOW_CONFIDENCE.value,
                errors=result.errors,
                match=result.match,
            )
            fid = _persist_finding(session_factory, state, finding)
            finding["finding_id"] = fid
            return {
                "finding": finding,
                "audit_log": [_audit("verify", "abstained", reason="low_confidence")],
            }

        # Precedence 4: all checks pass — citation/schema-verified.
        if result.ok:
            finding = _terminal_finding(
                state,
                status=FindingStatus.VERIFIED.value,
                abstain_reason=None,
                errors=[],
                match=result.match,
            )
            fid = _persist_finding(session_factory, state, finding)
            finding["finding_id"] = fid
            return {
                "finding": finding,
                "audit_log": [_audit("verify", "verified", method=result.match.method if result.match else None)],
            }

        # Precedence 5/6: retryable failure or exhausted retries.
        return _route_failure(session_factory, state, result.errors, result.repair_errors)

    def _route_failure(
        session_factory: SessionFactory,
        state: GovernanceState,
        errors: list[str],
        repair_errors: list[str],
    ) -> dict:
        _record_verifier_errors(session_factory, state, errors)
        if state.get("judge_attempts", 0) < MAX_JUDGE_ATTEMPTS:
            return {
                "verification_errors": repair_errors,
                "audit_log": [
                    _audit("verify", "retry_requested", errors=errors)
                ],
            }
        finding = _terminal_finding(
            state,
            status=FindingStatus.ABSTAINED.value,
            abstain_reason=AbstainReason.VERIFICATION_FAILED.value,
            errors=errors,
        )
        fid = _persist_finding(session_factory, state, finding)
        finding["finding_id"] = fid
        return {
            "finding": finding,
            "audit_log": [_audit("verify", "abstained", reason="verification_failed")],
        }

    return verify_node


def route_after_verify(state: GovernanceState) -> str:
    """Conditional edge: terminal finding -> END, otherwise back to judge."""
    return "end" if state.get("finding") is not None else "judge"
