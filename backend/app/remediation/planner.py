"""Corrective-action plan drafter (M7a) — the milestone core.

Flow (chat/service.py loop shape, plus the PLANNING lease):
0. under the case lock: recover a stale PLANNING lease if present, validate
   the state machine, snapshot every input (finding links, approved triage,
   previous active plan), set the lease (token + heartbeat) and commit —
   status becomes PLANNING;
1. gather evidence in short read transactions (hybrid retrieval per linked
   finding + KB scope); a Qdrant failure is an OPERATIONAL ABORT
   (retrieval_error): an ABSTAINED audit row is persisted but never
   activated, and the previous state is restored;
2. ≤2 LLM attempts with one repair; the on_call_finished callback renews the
   lease heartbeat between provider calls (a failed renewal marks the lease
   LOST locally — final persistence is then refused even if the token still
   matches);
3. relock, revalidate the token, persist plan + actions + attempts/calls,
   apply activation/supersession, clear the lease.

Deterministic gates (the trust layer — schema validity alone proves nothing):
- REQUIREMENT BINDING: every impacted_requirement_ids ⊆ the server-owned
  allowed_requirement_ids actually offered in the prompt. A KB-valid but
  unoffered id is a verification failure (the KB analogue of a quote from
  the wrong passage).
- QUOTE BINDING: quote_source_id must resolve to exactly one server-supplied
  policy result; the quote is checked against THAT result only and must
  match method == 'exact' (fuzzy ⇒ repair ⇒ ABSTAINED); persisted
  matched_chunk_id equals quote_source_id.

Activation rules (active_plan_id is the sole authority):
- completed outcomes (VERIFIED, schema_invalid, verification_failed,
  llm_error, rate_limited): first plan activates; a VERIFIED replacement
  atomically supersedes the previous active plan; an ABSTAINED replacement
  never displaces an active VERIFIED plan; an active ABSTAINED plan is
  superseded by any completed outcome;
- operational aborts (retrieval_error, draft_interrupted): audit rows only,
  never activated; the previous active plan and status are restored
  (PLAN_READY, or TRIAGE_APPROVED when no plan was ever active).
"""

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    RemediationAction,
    RemediationAttempt,
    RemediationCase,
    RemediationLlmCall,
    RemediationPlan,
)
from app.pipeline import llm as llm_service
from app.pipeline.verifier import find_quote_in_retrieved
from app.remediation.prompts import (
    REMEDIATION_PROMPT_VERSION,
    build_plan_messages,
    build_repair_messages,
)
from app.remediation.schema import PlanDraft
from app.remediation.service import (
    RemediationConflictError,
    append_event,
    finding_snapshot,
    lock_case,
)
from app.services.retrieval import CorpusChangedError, hybrid_search, load_kb

MAX_DRAFT_ATTEMPTS = 2
PLANNING_LEASE_SECONDS = 300  # conservative vs the ≤ ~90s inter-heartbeat gap
# CorpusChangedError joins the tuple: a version activation racing the evidence
# search is the same operational-abort class as Qdrant being down — an
# ABSTAINED(retrieval_error) audit row, never a crash.
QDRANT_ERRORS = (
    ResponseHandlingException,
    UnexpectedResponse,
    ConnectionError,
    CorpusChangedError,
)

COMPLETED_ABSTAIN_REASONS = (
    "schema_invalid",
    "verification_failed",
    "llm_error",
    "rate_limited",
)

DRAFT_IN_PROGRESS_FR = (
    "Une rédaction de plan est déjà en cours pour ce cas ; réessayez lorsque "
    "son verrou aura expiré."
)
LEASE_LOST_FR = (
    "Rédaction interrompue : le renouvellement du verrou a échoué en cours de "
    "route ; le résultat a été écarté. Relancez la rédaction du plan."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; lease arithmetic needs aware ones."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _next_sequence(db: Session, case_id: str) -> int:
    last = db.scalar(
        select(RemediationPlan.sequence)
        .where(RemediationPlan.case_id == case_id)
        .order_by(RemediationPlan.sequence.desc())
        .limit(1)
    )
    return (last or 0) + 1


def _restore_after_abort(db: Session, case: RemediationCase, prev_active: str | None) -> None:
    """Operational abort: never activate; restore the previous authority."""
    case.active_plan_id = prev_active
    case.status = "PLAN_READY" if prev_active is not None else "TRIAGE_APPROVED"
    case.planning_token = None
    case.planning_started_at = None
    case.planning_heartbeat_at = None
    case.updated_at = _now()


def recover_stale_planning(
    db: Session, case: RemediationCase, *, actor_label: str | None = None
) -> RemediationPlan:
    """Recover a case stuck in PLANNING whose lease heartbeat is stale.
    Persists an ABSTAINED draft_interrupted audit row (never activated) and
    restores the previous state. CALLER holds the case lock and has verified
    staleness; commits are the caller's."""
    prev_active = case.active_plan_id
    plan = RemediationPlan(
        case_id=case.id,
        sequence=_next_sequence(db, case.id),
        status="ABSTAINED",
        abstain_reason="draft_interrupted",
        raw_draft=None,
        draft_attempts=0,
        prompt_version=REMEDIATION_PROMPT_VERSION,
        corpus_version=load_kb()["corpus_version"],
        input_finding_links=[finding_snapshot(l) for l in case.finding_links],
        input_triage_snapshot=_triage_snapshot(case),
    )
    db.add(plan)
    db.flush()
    _restore_after_abort(db, case, prev_active)
    append_event(
        db, case.id, "plan_draft_recovered",
        {"plan_id": plan.id, "previous_active_plan_id": prev_active},
        actor_label,
    )
    return plan


def _triage_snapshot(case: RemediationCase) -> dict:
    """The APPROVED human projection (never the AI draft): triage reopen
    clears the case columns, so the plan row must stay self-contained."""
    return {
        "classification": case.classification,
        "correction_note": case.correction_note,
        "scope": case.scope,
        "scope_rationale": case.scope_rationale,
        "triage_approved_at": (
            case.triage_approved_at.isoformat() if case.triage_approved_at else None
        ),
        "triage_reviewer_label": case.triage_reviewer_label,
        "source_draft_id": case.approved_triage_draft_id,
    }


def _gather_evidence(
    db: Session, org_id: str, links: list[dict], scope: str | None
) -> tuple[list[dict], list[str], dict]:
    """Retrieval phase. Returns (policy evidence, allowed_requirement_ids,
    input_kb snapshots). allowed ids = linked finding requirements + KB
    retrieval hits when the approved scope extends beyond local."""
    kb = load_kb()
    evidence: list[dict] = []
    seen: set[str] = set()
    allowed: list[str] = []
    for link in links:
        rid = link["finding_requirement_id"]
        if rid in kb["by_id"] and rid not in allowed:
            allowed.append(rid)
        query = " ".join(
            p
            for p in (
                link.get("finding_requirement_fr") or rid,
                link.get("finding_human_rationale") or "",
            )
            if p
        )
        for item in hybrid_search(db, org_id, query, k=6, scope="policy"):
            d = asdict(item)
            if d["result_id"] in seen:
                continue
            seen.add(d["result_id"])
            evidence.append(d)
        if scope and scope != "local":
            for item in hybrid_search(db, org_id, query, k=8, scope="kb"):
                d = asdict(item)
                rid_kb = d.get("requirement_id")
                if rid_kb and rid_kb in kb["by_id"] and rid_kb not in allowed:
                    allowed.append(rid_kb)
    input_kb = {
        rid: {
            "requirement_fr": kb["by_id"][rid]["requirement_fr"],
            "domain": kb["by_id"][rid].get("domain"),
        }
        for rid in allowed
    }
    return evidence, allowed, input_kb


def _verify_plan(
    parsed: PlanDraft, evidence: list[dict], allowed: list[str]
) -> tuple[list[str], dict[int, dict | None]]:
    """Deterministic gates. Returns (errors, per-action quote provenance).
    Quote provenance i -> asdict(QuoteMatch) for actions with a bound quote."""
    errors: list[str] = []
    matches: dict[int, dict | None] = {}
    allowed_set = set(allowed)
    by_source = {e["result_id"]: e for e in evidence if e.get("source_type") == "policy"}
    for i, action in enumerate(parsed.actions, start=1):
        bad = [r for r in action.impacted_requirement_ids if r not in allowed_set]
        if bad:
            errors.append(
                f"action {i} : impacted_requirement_ids hors liste autorisée "
                f"{bad} — seuls les identifiants fournis dans « Exigences "
                "autorisées » sont acceptés."
            )
        matches[i] = None
        if action.policy_quote is None:
            continue
        source = by_source.get(action.quote_source_id)
        if source is None:
            errors.append(
                f"action {i} : quote_source_id « {action.quote_source_id} » ne "
                "désigne aucun extrait fourni."
            )
            continue
        # binding: the quote is checked against ITS claimed source only
        match = find_quote_in_retrieved(action.policy_quote, [source])
        if match is None:
            errors.append(
                f"action {i} : policy_quote introuvable dans l'extrait "
                f"« {action.quote_source_id} » — la citation doit exister mot "
                "pour mot dans l'extrait désigné."
            )
        elif match.method != "exact":
            errors.append(
                f"action {i} : citation approximative (similarité "
                f"{match.score:.1f}) dans « {action.quote_source_id} » — seule "
                "une citation exacte est acceptée."
            )
        else:
            matches[i] = asdict(match)
    return errors, matches


def draft_plan(
    db: Session,
    session_factory,
    org_id: str,
    case_id: str,
    *,
    actor_label: str | None = None,
    lease_seconds: int = PLANNING_LEASE_SECONDS,
) -> RemediationPlan:
    """Draft a corrective-action plan. Returns the persisted plan row
    (VERIFIED or ABSTAINED — operational aborts included, as audit rows).
    session_factory provides the short heartbeat transactions."""
    # ---- phase 0: lock, recover stale lease, validate, snapshot, lease ----
    case = lock_case(db, org_id, case_id)
    if case.status == "PLANNING":
        heartbeat = _aware(case.planning_heartbeat_at)
        if heartbeat is None or _now() - heartbeat < timedelta(seconds=lease_seconds):
            db.rollback()
            raise RemediationConflictError(DRAFT_IN_PROGRESS_FR)
        recover_stale_planning(db, case, actor_label=actor_label)
        # fall through: the case is now restored; continue with a fresh draft
    if case.status not in ("TRIAGE_APPROVED", "PLAN_READY"):
        db.rollback()
        raise RemediationConflictError(
            f"Rédaction de plan impossible : statut {case.status} "
            "(TRIAGE_APPROVED ou PLAN_READY requis)."
        )
    prev_active_id = case.active_plan_id
    prev_active_status: str | None = None
    if prev_active_id is not None:
        prev_plan = db.get(RemediationPlan, prev_active_id)
        prev_active_status = prev_plan.status
        if prev_plan.status == "VERIFIED" and any(
            a.lifecycle != "PROPOSED" for a in prev_plan.actions
        ):
            db.rollback()
            raise RemediationConflictError(
                "Rédaction impossible : des actions du plan actif ont déjà été "
                "traitées. Clôturez ou annulez ce travail, ou ouvrez un "
                "nouveau cas."
            )
    links = [finding_snapshot(l) for l in case.finding_links]
    triage_snapshot = _triage_snapshot(case)
    scope = case.scope
    token = str(uuid.uuid4())
    case.status = "PLANNING"
    case.planning_token = token
    case.planning_started_at = _now()
    case.planning_heartbeat_at = _now()
    case.updated_at = _now()
    append_event(
        db, case_id, "plan_draft_started",
        {"planning_token": token, "evidence_revision": case.evidence_revision},
        actor_label,
    )
    db.commit()

    # ---- phase 1: evidence gathering (short read transactions) ----
    retrieval_failure: str | None = None
    evidence: list[dict] = []
    allowed: list[str] = []
    input_kb: dict = {}
    try:
        evidence, allowed, input_kb = _gather_evidence(db, org_id, links, scope)
    except QDRANT_ERRORS as exc:
        retrieval_failure = f"recherche indisponible : {exc}"
    finally:
        db.rollback()

    if retrieval_failure is not None:
        case = lock_case(db, org_id, case_id)
        if case.planning_token != token:
            db.rollback()
            raise RemediationConflictError(LEASE_LOST_FR)
        plan = RemediationPlan(
            case_id=case_id,
            sequence=_next_sequence(db, case_id),
            status="ABSTAINED",
            abstain_reason="retrieval_error",
            draft_attempts=0,
            prompt_version=REMEDIATION_PROMPT_VERSION,
            corpus_version=load_kb()["corpus_version"],
            input_finding_links=links,
            input_triage_snapshot=triage_snapshot,
        )
        db.add(plan)
        db.flush()
        _restore_after_abort(db, case, prev_active_id)
        append_event(
            db, case_id, "plan_abstained",
            {
                "plan_id": plan.id,
                "sequence": plan.sequence,
                "abstain_reason": "retrieval_error",
                "activated": False,
            },
            actor_label,
        )
        db.commit()
        return plan

    # ---- phase 2: LLM loop with lease heartbeat ----
    lease_lost = False

    def _heartbeat() -> None:
        nonlocal lease_lost
        if lease_lost:
            return
        hb = None
        try:
            hb = session_factory()
            result = hb.execute(
                update(RemediationCase)
                .where(
                    RemediationCase.id == case_id,
                    RemediationCase.planning_token == token,
                )
                .values(planning_heartbeat_at=_now())
            )
            hb.commit()
            if result.rowcount != 1:  # token gone: someone recovered the lease
                lease_lost = True
        except Exception:
            # renewal failure marks the lease lost locally: final persistence
            # is refused even if the token still happens to match at the end
            lease_lost = True
        finally:
            if hb is not None:
                hb.close()

    prompt_evidence = [
        {
            "source_id": e["result_id"],
            "document": e.get("filename"),
            "page": e.get("page_number"),
            "texte": e["text"],
        }
        for e in evidence
        if e.get("source_type") == "policy"
    ]
    allowed_prompt = [
        {"id": rid, "texte": input_kb[rid]["requirement_fr"], "domaine": input_kb[rid]["domain"]}
        for rid in allowed
    ]
    base_messages = build_plan_messages(links, triage_snapshot, prompt_evidence, allowed_prompt)
    schema = PlanDraft.model_json_schema()
    messages = base_messages

    parsed: PlanDraft | None = None
    verified: PlanDraft | None = None
    quote_matches: dict[int, dict | None] = {}
    raw_draft: str | None = None
    abstain_reason: str | None = None
    final_model: str | None = None
    final_provider: str | None = None
    attempts_meta: list[dict] = []
    calls: list[tuple[int, llm_service.LLMCall]] = []

    for attempt_number in range(1, MAX_DRAFT_ATTEMPTS + 1):
        outcome = llm_service.complete_json(
            messages,
            json_schema=schema,
            schema_name="remediation_plan",
            on_call_finished=_heartbeat,
        )
        calls.extend((attempt_number, c) for c in outcome.calls)
        if outcome.content is None:
            abstain_reason = llm_service.classify_failure(outcome.calls)
            attempts_meta.append(
                {
                    "attempt_number": attempt_number,
                    "parsed_ok": False,
                    "validation_errors": [outcome.error or "tous les fournisseurs ont échoué"],
                }
            )
            break
        raw_draft = outcome.content
        final_call = outcome.final_call
        if final_call is not None:
            final_provider = final_call.provider
            final_model = final_call.reported_model or final_call.requested_model
        errors: list[str]
        try:
            payload = json.loads(raw_draft)
        except json.JSONDecodeError as exc:
            parsed, errors = None, [f"JSON invalide : {exc}."]
        else:
            try:
                parsed = PlanDraft.model_validate(payload)
                errors = []
            except ValidationError as exc:
                parsed = None
                details = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                    for e in exc.errors()
                )
                errors = [f"schéma invalide : {details}."]
        schema_ok = parsed is not None
        if schema_ok:
            gate_errors, quote_matches = _verify_plan(parsed, evidence, allowed)
            errors = gate_errors
        attempts_meta.append(
            {
                "attempt_number": attempt_number,
                "parsed_ok": schema_ok,
                "validation_errors": errors,
            }
        )
        if not errors:
            verified = parsed
            break
        messages = build_repair_messages(base_messages, raw_draft, errors)

    if verified is None and abstain_reason is None:
        # exhausted: schema failure vs deterministic-gate failure
        last_schema_ok = attempts_meta[-1]["parsed_ok"] if attempts_meta else False
        abstain_reason = "verification_failed" if last_schema_ok else "schema_invalid"

    # ---- phase 3: relock, revalidate token + lease, persist ----
    case = lock_case(db, org_id, case_id)
    if case.planning_token != token:
        db.rollback()
        raise RemediationConflictError(LEASE_LOST_FR)
    if lease_lost:
        # heartbeat failed mid-flight: refuse persistence even though the
        # token matches; the stale-lease recovery path owns the case now
        db.rollback()
        raise RemediationConflictError(LEASE_LOST_FR)

    status = "VERIFIED" if verified is not None else "ABSTAINED"
    plan = RemediationPlan(
        case_id=case_id,
        sequence=_next_sequence(db, case_id),
        status=status,
        abstain_reason=abstain_reason,
        gap_restatement=verified.gap_restatement if verified else None,
        root_cause_hypotheses=(
            [h.model_dump() for h in verified.root_cause_hypotheses] if verified else None
        ),
        raw_draft=raw_draft,
        draft_attempts=len(attempts_meta),
        prompt_version=REMEDIATION_PROMPT_VERSION,
        corpus_version=load_kb()["corpus_version"],
        final_model=final_model,
        final_provider=final_provider,
        retrieved=evidence,
        input_finding_links=links,
        input_triage_snapshot=triage_snapshot,
        allowed_requirement_ids=allowed,
        input_kb=input_kb,
    )
    db.add(plan)
    db.flush()
    if verified is not None:
        for i, action in enumerate(verified.actions, start=1):
            match = quote_matches.get(i)
            db.add(
                RemediationAction(
                    plan_id=plan.id,
                    position=i,
                    action_type=action.action_type,
                    ai_description=action.description,
                    ai_rationale=action.rationale,
                    ai_owner_role=action.owner_role,
                    ai_success_criterion=action.success_criterion,
                    ai_impacted_requirement_ids=action.impacted_requirement_ids,
                    policy_quote=action.policy_quote,
                    matched_chunk_id=match["chunk_id"] if match else None,
                    match_start=match["match_start"] if match else None,
                    match_end=match["match_end"] if match else None,
                    match_method=match["method"] if match else None,
                    match_score=match["score"] if match else None,
                )
            )

    # provenance pair
    call_number = 0
    for meta in attempts_meta:
        attempt = RemediationAttempt(
            case_id=case_id,
            stage="plan",
            plan_id=plan.id,
            attempt_number=meta["attempt_number"],
            prompt_version=REMEDIATION_PROMPT_VERSION,
            parsed_ok=meta["parsed_ok"],
            verifier_errors=meta["validation_errors"] or None,
            finished_at=_now(),
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
                    prompt_version=REMEDIATION_PROMPT_VERSION,
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
                    started_at=_parse_ts(call.started_at) or _now(),
                    finished_at=_parse_ts(call.finished_at),
                )
            )

    # ---- activation / supersession (completed outcomes only here) ----
    activated = False
    if status == "VERIFIED":
        if prev_active_id is not None:
            prev_plan = db.get(RemediationPlan, prev_active_id)
            prev_plan.status = "SUPERSEDED"
            prev_plan.superseded_at = _now()
            prev_plan.superseded_by_plan_id = plan.id
            append_event(
                db, case_id, "plan_superseded",
                {"plan_id": prev_plan.id, "superseded_by_plan_id": plan.id, "cause": "replacement"},
                actor_label,
            )
        case.active_plan_id = plan.id
        activated = True
    else:  # completed ABSTAINED outcome
        if prev_active_id is None:
            case.active_plan_id = plan.id
            activated = True
        elif prev_active_status == "ABSTAINED":
            prev_plan = db.get(RemediationPlan, prev_active_id)
            prev_plan.status = "SUPERSEDED"
            prev_plan.superseded_at = _now()
            prev_plan.superseded_by_plan_id = plan.id
            append_event(
                db, case_id, "plan_superseded",
                {"plan_id": prev_plan.id, "superseded_by_plan_id": plan.id, "cause": "replacement"},
                actor_label,
            )
            case.active_plan_id = plan.id
            activated = True
        # else: the active VERIFIED plan stays active

    case.status = "PLAN_READY"
    case.planning_token = None
    case.planning_started_at = None
    case.planning_heartbeat_at = None
    case.updated_at = _now()
    if status == "VERIFIED":
        append_event(
            db, case_id, "plan_drafted",
            {
                "plan_id": plan.id,
                "sequence": plan.sequence,
                "action_count": len(verified.actions),
                "activated": activated,
            },
            actor_label,
        )
    else:
        append_event(
            db, case_id, "plan_abstained",
            {
                "plan_id": plan.id,
                "sequence": plan.sequence,
                "abstain_reason": abstain_reason,
                "activated": activated,
            },
            actor_label,
        )
    db.commit()
    return plan
