"""Explicit, opt-in retention pruning of persisted LLM request prompts.

Retention decision (documented here, applied only by
scripts/prune_llm_payloads.py — never automatically):

- KEPT FOREVER: every call's metadata (provider, requested/reported model,
  status, http_status, error, timings, prompt_version), `raw_response` (the
  model's actual output — the audit of what the AI produced), and every
  attempt / finding / plan / message row. The trust chain is untouched.
- PRUNABLE: `request_messages` — the full prompt body of every provider call,
  including 429 retries that repeat it verbatim. It duplicates policy-page
  text already persisted durably elsewhere (document versions, `retrieved`
  snapshots) and NO read path serves it (verified: only writers reference the
  column). It is the one payload that grows without bound.

Pruning is never a silent delete: the column is replaced by an explicit
marker recording when and under which policy it was pruned, and the operation
runs only through the dedicated script with --apply — mirroring the project
doctrine that erasure is a separate, explicitly audited workflow, never a
cascade or a background job.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatLlmCall, LlmCall, RemediationLlmCall

RETENTION_POLICY = "llm-request-retention-v1"

# (model, table name) — every table persisting provider-call prompt bodies.
CALL_TABLES = (
    (LlmCall, "llm_calls"),
    (ChatLlmCall, "chat_llm_calls"),
    (RemediationLlmCall, "remediation_llm_calls"),
)


def pruned_marker(now: datetime) -> list[dict]:
    """The explicit replacement payload — same JSON list shape as the column."""
    return [{"pruned": True, "pruned_at": now.isoformat(), "policy": RETENTION_POLICY}]


def is_pruned(request_messages: object) -> bool:
    return (
        isinstance(request_messages, list)
        and len(request_messages) == 1
        and isinstance(request_messages[0], dict)
        and request_messages[0].get("pruned") is True
    )


def prune_request_messages(
    db: Session, *, older_than_days: int, apply: bool = False
) -> dict:
    """Replace `request_messages` of calls started before the cutoff with the
    explicit marker. Dry-run by default (nothing written unless apply=True).
    Returns a per-table report: {"candidates": rows past the cutoff not yet
    pruned, "pruned": rows rewritten this run (0 on dry-run)}."""
    if older_than_days < 1:
        raise ValueError("older_than_days must be >= 1")
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=older_than_days)
    marker = pruned_marker(now)
    report: dict = {
        "cutoff": cutoff.isoformat(),
        "apply": apply,
        "policy": RETENTION_POLICY,
        "tables": {},
    }
    for model, name in CALL_TABLES:
        candidates = 0
        pruned = 0
        for row in db.scalars(
            select(model)
            .where(model.started_at < cutoff)
            .execution_options(yield_per=500)
        ):
            if is_pruned(row.request_messages):
                continue
            candidates += 1
            if apply:
                row.request_messages = marker
                pruned += 1
        report["tables"][name] = {"candidates": candidates, "pruned": pruned}
    if apply:
        db.commit()
    else:
        db.rollback()
    return report
