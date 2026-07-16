"""Shared helpers for the remediation draft flows (triage / planner / patcher).

The three flows persist identical provenance pairs (RemediationAttempt +
RemediationLlmCall) and share the same timestamp handling; keeping one
implementation here prevents the flows from drifting apart.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import RemediationAttempt, RemediationLlmCall
from app.pipeline.llm import LLMCall, parse_call_ts


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; lease arithmetic needs aware ones."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def persist_attempt_calls(
    db: Session,
    *,
    case_id: str,
    stage: str,
    attempts_meta: list[dict],
    calls: list[tuple[int, LLMCall]],
    prompt_version: str,
    triage_draft_id: str | None = None,
    plan_id: str | None = None,
    patch_proposal_id: str | None = None,
    remediation_artifact_id: str | None = None,
) -> None:
    """Persist the RemediationAttempt/RemediationLlmCall provenance pair for
    one draft flow. `calls` pairs each LLMCall with its attempt number;
    call_number continues across attempts (pipeline convention). Stages new
    rows in the caller's transaction; the caller commits."""
    call_number = 0
    for meta in attempts_meta:
        attempt = RemediationAttempt(
            case_id=case_id,
            stage=stage,
            triage_draft_id=triage_draft_id,
            plan_id=plan_id,
            patch_proposal_id=patch_proposal_id,
            remediation_artifact_id=remediation_artifact_id,
            attempt_number=meta["attempt_number"],
            prompt_version=prompt_version,
            parsed_ok=meta["parsed_ok"],
            verifier_errors=meta["validation_errors"] or None,
            finished_at=now(),
        )
        db.add(attempt)
        db.flush()
        for attempt_number, call in calls:
            if attempt_number != meta["attempt_number"]:
                continue
            call_number += 1
            db.add(
                RemediationLlmCall(
                    remediation_attempt_id=attempt.id,
                    call_number=call_number,
                    prompt_version=prompt_version,
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
                    started_at=parse_call_ts(call.started_at) or now(),
                    finished_at=parse_call_ts(call.finished_at),
                )
            )
