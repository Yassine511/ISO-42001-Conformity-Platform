"""M7b anchored-patch flow: draft -> human diff decision -> token-fenced
two-phase activation (PG authoritative, Qdrant derived).

DRAFTING (draft_patch_proposal, planner.py three-phase shape):
0. under the case lock: guard rails (operable APPROVED document_amendment
   action, open case, TXT/MD current version), staleness pins snapshot,
   DRAFTING proposal row with its own lease (the case PLANNING lease is
   structurally unusable — its coherence CHECK ties it to status='PLANNING');
1. no retrieval phase: the server serves the FULL page text of the
   human-confirmed target version (immutable, read under the initial lock);
2. <=2 LLM attempts with one repair; heartbeats are token-fenced UPDATEs on
   the proposal row;
3. relock, revalidate token, persist. VERIFIED iff find_all_exact_anchors
   returns EXACTLY ONE span on page 1 within bounds — raw literal equality,
   no normalization (deliberate opposite of the read-side verifier). An
   ABSTAINED proposal persists NO resolved span (ambiguous candidates go to
   verifier_errors diagnostics).

DECISION + ACTIVATION (decide_patch / recover_patch_activation):
- Tx A (lock order org[run_guard] -> case -> document -> base version):
  staleness gates, duplicate-decision idempotency, apply the FINAL HUMAN
  text at the resolved span, serialize UTF-8 (no normalization), create the
  PENDING_INDEX candidate + pages + chunks + decision + activation lease,
  version_created document event. Commit.
- lock-free indexing of the candidate's points (token-fenced heartbeats);
- Tx B (same lock order, EVERY candidate mutation fenced by
  activation_token): token-loss => no PG mutation, deterministic state
  report; assessment RUNNING => temporary conflict (keep PENDING_INDEX,
  clear token, activation_error='assessment_conflict'); authority gate =>
  ABANDONED(stale_action|authority_lost); CAS on current_version_id/base
  ACTIVE/candidate recoverable => ABANDONED(stale_base); org-wide current
  source_checksum recheck => ABANDONED(checksum_conflict); success: base ->
  SUPERSEDED (flushed first vs the one-ACTIVE partial unique), candidate ->
  ACTIVE, pointer + mirrors flipped, version_indexed + version_activated
  document events + patch_approved case event, post-commit best-effort
  deletion of the superseded points (GC debt only — the snapshot filter and
  hydration are the correctness layer).
- recovery takes over the token (fencing a stale worker out) and re-drives
  idempotently; ABANDONED is terminal and deliberately does NOT reserve its
  text_checksum (a fresh authorized proposal may recreate the same content).
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    Chunk,
    Document,
    DocumentPage,
    DocumentVersion,
    PatchDecision,
    PatchProposal,
    RemediationAction,
    RemediationAttempt,
    RemediationCase,
    RemediationLlmCall,
)
from app.pipeline import llm as llm_service
from app.remediation.actions import _operable_action
from app.remediation.prompts import (
    PATCH_PROMPT_VERSION,
    build_patch_messages,
    build_repair_messages,
)
from app.remediation.schema import PatchDraft
from app.remediation.service import (
    RemediationConflictError,
    RemediationInvalidError,
    RemediationNotFoundError,
    append_event,
    lock_case,
)
from app.services import qdrant
from app.services.anchors import find_all_exact_anchors
from app.services.checksums import text_checksum
from app.services.chunking import CHUNKER_VERSION
from app.services.embeddings import embed_texts
from app.services.retrieval import _chunk_point, materialize_version_chunks
from app.services.run_guard import (
    RUNNING_CONFLICT_FR,
    lock_organization,
    running_assessment_id,
)
from app.services.version_events import append_version_event

MAX_DRAFT_ATTEMPTS = 2
MIN_ANCHOR_LEN = 20  # schema-enforced too; the verifier re-checks for a typed error
DRAFTING_LEASE_SECONDS = 300
ACTIVATION_LEASE_SECONDS = 300
MAX_FINAL_TEXT_CHARS = 8000
MAX_RESULT_BYTES = 20 * 1024 * 1024  # same policy as document upload

PATCH_TARGET_FORMATS = ("txt", "md")

DRAFT_IN_PROGRESS_FR = (
    "Une rédaction de correctif est déjà en cours pour cette action ; "
    "réessayez lorsque son verrou aura expiré."
)
LEASE_LOST_FR = (
    "Rédaction interrompue : le verrou du brouillon a été perdu en cours de "
    "route ; le résultat a été écarté. Relancez la proposition de correctif."
)
STALE_INPUT_FR = (
    "Contexte périmé : l'action, le plan actif ou les preuves du cas ont "
    "changé depuis la création de la proposition. Redemandez un correctif."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# --------------------------------------------------------------- drafting


def _require_patch_target(db: Session, org_id: str, document_id: str) -> tuple[Document, DocumentVersion]:
    doc = db.get(Document, document_id)
    if doc is None or doc.organization_id != org_id:
        db.rollback()
        raise RemediationNotFoundError("Document introuvable pour cette organisation.")
    if doc.current_version_id is None:
        db.rollback()
        raise RemediationInvalidError(
            "Ce document n'a pas de version analysée exploitable."
        )
    version = db.get(DocumentVersion, doc.current_version_id)
    if version.canonical_format not in PATCH_TARGET_FORMATS:
        db.rollback()
        raise RemediationInvalidError(
            "Le correctif ancré ne s'applique qu'aux documents TXT/Markdown ; "
            "pour un PDF/DOCX, générez une proposition de rédaction (artefact) "
            "puis téléversez la révision."
        )
    return doc, version


def action_context(db: Session, case: RemediationCase, action: RemediationAction) -> dict:
    """Server-owned drafting context: the HUMAN-approved effective values and
    requirement scope (never the AI columns), plus the staleness pins."""
    requirements = [
        {"id": r.requirement_id, "texte": r.requirement_fr, "domaine": r.domain}
        for r in action.requirements
    ]
    return {
        "action_snapshot": {
            "description": action.description,
            "rationale": action.rationale,
            "owner_role": action.owner_role,
            "success_criterion": action.success_criterion,
            "priority": action.priority,
        },
        "requirements": requirements,
        "pins": {
            "input_action_review_count": action.review_count,
            "input_plan_id": case.active_plan_id,
            "input_case_evidence_revision": case.evidence_revision,
        },
    }


def _recover_stale_drafting(db: Session, proposal: PatchProposal, *, actor_label) -> None:
    """Terminal ABSTAINED(draft_interrupted) audit row for a stale DRAFTING
    lease. Caller holds the case lock; caller commits."""
    proposal.status = "ABSTAINED"
    proposal.abstain_reason = "draft_interrupted"
    proposal.drafting_token = None
    proposal.drafting_started_at = None
    proposal.drafting_heartbeat_at = None
    append_event(
        db, proposal.case_id, "patch_abstained",
        {
            "proposal_id": proposal.id,
            "action_id": proposal.action_id,
            "abstain_reason": "draft_interrupted",
            "attempts": proposal.attempts,
        },
        actor_label,
    )


def _verify_patch(parsed: PatchDraft, page_text: str) -> tuple[list[str], tuple[int, int] | None, str | None]:
    """Deterministic write gate. Returns (errors, resolved span, gate_kind).
    Raw literal equality, exactly one occurrence, page 1 only."""
    errors: list[str] = []
    if parsed.anchor_page != 1:
        return (
            ["anchor_page doit valoir 1 : les documents TXT/Markdown n'ont qu'une page."],
            None,
            "anchor_not_found",
        )
    spans = find_all_exact_anchors(page_text, parsed.anchor_quote)
    if not spans:
        errors.append(
            "anchor_quote introuvable dans le document par égalité littérale "
            "stricte — copie l'ancre caractère par caractère, sans modifier "
            "espaces, accents, ponctuation ni majuscules."
        )
        return errors, None, "anchor_not_found"
    if len(spans) > 1:
        errors.append(
            f"anchor_quote ambiguë : {len(spans)} occurrences dans le document "
            f"(positions {[s.start for s in spans[:5]]}) — choisis un extrait "
            "plus long qui n'apparaît qu'une seule fois."
        )
        return errors, None, "anchor_ambiguous"
    return [], (spans[0].start, spans[0].end), None


def draft_patch_proposal(
    db: Session,
    session_factory,
    org_id: str,
    case_id: str,
    action_id: str,
    document_id: str,
    *,
    actor_label: str | None = None,
    lease_seconds: int = DRAFTING_LEASE_SECONDS,
) -> PatchProposal:
    """Draft one anchored-patch proposal. Returns the persisted row
    (VERIFIED or ABSTAINED). session_factory provides the short token-fenced
    heartbeat transactions."""
    # ---- phase 0: lock, guard rails, snapshot, DRAFTING row ----
    case = lock_case(db, org_id, case_id)
    action = _operable_action(db, case, action_id)
    if action.lifecycle != "APPROVED":
        db.rollback()
        raise RemediationConflictError(
            "Un correctif ne peut être proposé que pour une action APPROVED "
            f"(statut actuel : {action.lifecycle})."
        )
    if action.action_type != "document_amendment":
        db.rollback()
        raise RemediationInvalidError(
            "Le correctif documentaire ne s'applique qu'aux actions de type "
            "« document_amendment »."
        )
    doc, version = _require_patch_target(db, org_id, document_id)

    # one live DRAFTING proposal per action; stale ones are recovered
    for stale in db.scalars(
        select(PatchProposal).where(
            PatchProposal.action_id == action_id,
            PatchProposal.status == "DRAFTING",
        )
    ).all():
        heartbeat = _aware(stale.drafting_heartbeat_at)
        if heartbeat is not None and _now() - heartbeat < timedelta(seconds=lease_seconds):
            db.rollback()
            raise RemediationConflictError(DRAFT_IN_PROGRESS_FR)
        _recover_stale_drafting(db, stale, actor_label=actor_label)

    context = action_context(db, case, action)
    page_text = version.pages[0].text  # TXT/MD: exactly one page, immutable
    token = str(uuid.uuid4())
    proposal = PatchProposal(
        case_id=case_id,
        action_id=action_id,
        document_id=doc.id,
        document_version_id=version.id,
        base_text_checksum=version.text_checksum,
        requirement_ids=[r["id"] for r in context["requirements"]],
        requirements_snapshot=context["requirements"],
        status="DRAFTING",
        drafting_token=token,
        drafting_started_at=_now(),
        drafting_heartbeat_at=_now(),
        prompt_version=PATCH_PROMPT_VERSION,
        **context["pins"],
    )
    db.add(proposal)
    db.commit()
    proposal_id = proposal.id

    # ---- phase 2: LLM loop with token-fenced heartbeats (no retrieval:
    # the target text is already snapshotted from the immutable version) ----
    lease_lost = False

    def _heartbeat() -> None:
        nonlocal lease_lost
        if lease_lost:
            return
        hb = None
        try:
            hb = session_factory()
            result = hb.execute(
                update(PatchProposal)
                .where(
                    PatchProposal.id == proposal_id,
                    PatchProposal.drafting_token == token,
                )
                .values(drafting_heartbeat_at=_now())
            )
            hb.commit()
            if result.rowcount != 1:
                lease_lost = True
        except Exception:
            lease_lost = True
        finally:
            if hb is not None:
                hb.close()

    base_messages = build_patch_messages(
        context["action_snapshot"],
        context["requirements"],
        {
            "document": doc.filename,
            "format": version.canonical_format,
            "page": 1,
            "texte": page_text,
        },
    )
    schema = PatchDraft.model_json_schema()
    messages = base_messages

    verified: PatchDraft | None = None
    span: tuple[int, int] | None = None
    abstain_reason: str | None = None
    gate_kind: str | None = None
    attempts_meta: list[dict] = []
    calls: list[tuple[int, llm_service.LLMCall]] = []

    for attempt_number in range(1, MAX_DRAFT_ATTEMPTS + 1):
        outcome = llm_service.complete_json(
            messages,
            json_schema=schema,
            schema_name="patch_draft",
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
        parsed: PatchDraft | None
        try:
            payload = json.loads(raw_draft)
        except json.JSONDecodeError as exc:
            parsed, errors = None, [f"JSON invalide : {exc}."]
        else:
            try:
                parsed = PatchDraft.model_validate(payload)
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
            errors, span, gate_kind = _verify_patch(parsed, page_text)
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
        last_schema_ok = attempts_meta[-1]["parsed_ok"] if attempts_meta else False
        abstain_reason = (gate_kind or "anchor_not_found") if last_schema_ok else "schema_invalid"

    # ---- phase 3: relock, revalidate token, persist ----
    case = lock_case(db, org_id, case_id)
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None or proposal.drafting_token != token or lease_lost:
        db.rollback()
        raise RemediationConflictError(LEASE_LOST_FR)

    proposal.attempts = len(attempts_meta)
    proposal.drafting_token = None
    proposal.drafting_started_at = None
    proposal.drafting_heartbeat_at = None
    # write-once AI columns: the last parsed draft (even a failed one is kept
    # on the ABSTAINED row for audit — but never a resolved span)
    last_draft = verified
    if last_draft is not None:
        proposal.anchor_quote = last_draft.anchor_quote
        proposal.anchor_page = last_draft.anchor_page
        proposal.operation = last_draft.operation
        proposal.new_text_fr = last_draft.new_text_fr
        proposal.rationale = last_draft.rationale
    all_errors = [e for m in attempts_meta for e in m["validation_errors"]]
    proposal.verifier_errors = all_errors or None
    if verified is not None:
        proposal.status = "VERIFIED"
        proposal.anchor_char_start, proposal.anchor_char_end = span
        append_event(
            db, case_id, "patch_proposed",
            {
                "proposal_id": proposal.id,
                "action_id": action_id,
                "document_id": proposal.document_id,
                "document_version_id": proposal.document_version_id,
                "operation": proposal.operation,
                "anchor_page": proposal.anchor_page,
                "attempts": proposal.attempts,
            },
            actor_label,
        )
    else:
        proposal.status = "ABSTAINED"
        proposal.abstain_reason = abstain_reason
        append_event(
            db, case_id, "patch_abstained",
            {
                "proposal_id": proposal.id,
                "action_id": action_id,
                "abstain_reason": abstain_reason,
                "attempts": proposal.attempts,
            },
            actor_label,
        )

    call_number = 0
    for meta in attempts_meta:
        attempt = RemediationAttempt(
            case_id=case_id,
            stage="patch",
            patch_proposal_id=proposal.id,
            attempt_number=meta["attempt_number"],
            prompt_version=PATCH_PROMPT_VERSION,
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
                    prompt_version=PATCH_PROMPT_VERSION,
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
    db.commit()
    return proposal


# --------------------------------------------------------------- diff view


def proposal_view(db: Session, org_id: str, case_id: str, proposal_id: str) -> dict:
    """Server-derived diff data: the raw page slice at the RESOLVED span (the
    UI never renders the model quote as evidence) plus surrounding context."""
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None or proposal.case_id != case_id:
        raise RemediationNotFoundError("Proposition de correctif introuvable.")
    case = db.get(RemediationCase, case_id)
    if case.organization_id != org_id:
        raise RemediationNotFoundError("Proposition de correctif introuvable.")
    out = {
        "id": proposal.id,
        "case_id": proposal.case_id,
        "action_id": proposal.action_id,
        "document_id": proposal.document_id,
        "document_version_id": proposal.document_version_id,
        "base_text_checksum": proposal.base_text_checksum,
        "status": proposal.status,
        "abstain_reason": proposal.abstain_reason,
        "verifier_errors": proposal.verifier_errors,
        "operation": proposal.operation,
        "anchor_page": proposal.anchor_page,
        "new_text_fr": proposal.new_text_fr,
        "rationale": proposal.rationale,
        "attempts": proposal.attempts,
        "requirement_ids": proposal.requirement_ids,
        "created_at": proposal.created_at.isoformat(),
        "anchor_char_start": proposal.anchor_char_start,
        "anchor_char_end": proposal.anchor_char_end,
        "anchor_slice": None,
        "context_before": None,
        "context_after": None,
        "decision": None,
    }
    if proposal.status == "VERIFIED":
        page = db.scalar(
            select(DocumentPage).where(
                DocumentPage.document_version_id == proposal.document_version_id,
                DocumentPage.page_number == 1,
            )
        )
        start, end = proposal.anchor_char_start, proposal.anchor_char_end
        text = page.text
        out["anchor_slice"] = text[start:end]
        out["context_before"] = text[max(0, start - 400):start]
        out["context_after"] = text[end:end + 400]
    decision = proposal.decision
    if decision is not None:
        out["decision"] = {
            "id": decision.id,
            "decision": decision.decision,
            "final_text_fr": decision.final_text_fr,
            "result_version_id": decision.result_version_id,
            "actor_label": decision.actor_label,
            "created_at": decision.created_at.isoformat(),
        }
        if decision.result_version_id:
            result = db.get(DocumentVersion, decision.result_version_id)
            out["decision"]["result_state"] = result.state
            out["decision"]["result_abandoned_reason"] = result.abandoned_reason
            out["decision"]["result_activation_error"] = result.activation_error
    return out


# ----------------------------------------------------------- decision / Tx A


def _candidate_status(db: Session, decision: PatchDecision) -> dict:
    """Deterministic idempotent report for an existing decision."""
    if decision.decision == "reject":
        return {"outcome": "rejected", "decision_id": decision.id, "version_id": None}
    version = db.get(DocumentVersion, decision.result_version_id)
    base = {"decision_id": decision.id, "version_id": version.id}
    if version.state == "ACTIVE":
        return {"outcome": "already_active", **base}
    if version.state == "ABANDONED":
        return {"outcome": f"abandoned:{version.abandoned_reason}", **base}
    return {"outcome": "pending", **base}


def _apply_operation(page_text: str, operation: str, start: int, end: int, final_text: str) -> str:
    """insert_after: the final text becomes a new paragraph immediately after
    the anchor; replace: the anchor span is substituted in place."""
    if operation == "replace":
        return page_text[:start] + final_text + page_text[end:]
    return page_text[:end] + "\n\n" + final_text + page_text[end:]


def _lock_activation_scope(
    db: Session, org_id: str, case_id: str, proposal: PatchProposal
) -> tuple[RemediationCase, Document]:
    """Declared lock order: org (run_guard) -> case -> document. Version rows
    are locked by the caller as needed."""
    org = lock_organization(db, org_id)
    if org is None:
        db.rollback()
        raise RemediationNotFoundError("Organisation introuvable.")
    case = lock_case(db, org_id, case_id)
    doc = db.get(Document, proposal.document_id, with_for_update=True)
    return case, doc


def decide_patch(
    db: Session,
    org_id: str,
    case_id: str,
    proposal_id: str,
    *,
    decision: str,
    final_text_fr: str | None = None,
    actor_label: str | None = None,
) -> dict:
    """Record the human decision. approve/edit run the full two-phase
    activation; returns a deterministic outcome dict (see _candidate_status).
    Duplicate requests are idempotent status reads, never opaque conflicts."""
    if decision not in ("approve", "edit", "reject"):
        raise RemediationInvalidError("Décision inconnue (approve, edit ou reject).")

    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None or proposal.case_id != case_id:
        raise RemediationNotFoundError("Proposition de correctif introuvable.")

    # ---- Tx A ----
    case, doc = _lock_activation_scope(db, org_id, case_id, proposal)
    if case.status == "CLOSED":
        db.rollback()
        raise RemediationConflictError("Cas clôturé : rouvrez-le d'abord.")
    existing = db.scalar(
        select(PatchDecision).where(PatchDecision.proposal_id == proposal_id)
    )
    if existing is not None:
        result = _candidate_status(db, existing)
        db.rollback()
        return result
    if proposal.status != "VERIFIED":
        db.rollback()
        raise RemediationConflictError(
            "Seule une proposition VÉRIFIÉE peut être décidée "
            f"(statut actuel : {proposal.status})."
        )

    if decision == "reject":
        row = PatchDecision(
            proposal_id=proposal_id, decision="reject", actor_label=actor_label
        )
        db.add(row)
        db.flush()
        append_event(
            db, case_id, "patch_rejected",
            {"proposal_id": proposal_id, "decision_id": row.id},
            actor_label,
        )
        db.commit()
        return {"outcome": "rejected", "decision_id": row.id, "version_id": None}

    if running_assessment_id(db, org_id):
        db.rollback()
        raise RemediationConflictError(RUNNING_CONFLICT_FR)

    # staleness gate (round-2 finding 11): pins must still hold
    action = db.get(RemediationAction, proposal.action_id)
    if (
        action.lifecycle != "APPROVED"
        or action.review_count != proposal.input_action_review_count
        or case.active_plan_id != proposal.input_plan_id
        or case.evidence_revision != proposal.input_case_evidence_revision
    ):
        db.rollback()
        raise RemediationConflictError(STALE_INPUT_FR)

    base = db.get(DocumentVersion, proposal.document_version_id, with_for_update=True)
    if doc.current_version_id != base.id or base.state != "ACTIVE":
        db.rollback()
        raise RemediationConflictError(
            "La version de base a été remplacée depuis la proposition ; "
            "redemandez un correctif sur la version actuelle."
        )
    if base.text_checksum != proposal.base_text_checksum:
        db.rollback()
        raise RemediationConflictError(
            "Le contenu du document a changé depuis la proposition "
            "(somme de contrôle différente) ; redemandez un correctif."
        )

    final_text = (
        proposal.new_text_fr if decision == "approve" else (final_text_fr or "").strip()
    )
    if not final_text or len(final_text) > MAX_FINAL_TEXT_CHARS:
        db.rollback()
        raise RemediationInvalidError(
            "Le texte final est obligatoire pour « edit » et limité à "
            f"{MAX_FINAL_TEXT_CHARS} caractères."
        )

    page_text = base.pages[0].text
    new_page = _apply_operation(
        page_text, proposal.operation, proposal.anchor_char_start,
        proposal.anchor_char_end, final_text,
    )
    new_bytes = new_page.encode("utf-8")  # exact serialized bytes, no normalization
    if not new_page.strip():
        db.rollback()
        raise RemediationInvalidError("Le document résultant serait vide.")
    if len(new_bytes) > MAX_RESULT_BYTES:
        db.rollback()
        raise RemediationInvalidError(
            "Le document résultant dépasse la taille maximale (20 Mo)."
        )
    new_text_ck = text_checksum([new_page])
    twin = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == doc.id,
            DocumentVersion.text_checksum == new_text_ck,
            DocumentVersion.state != "ABANDONED",
        )
    )
    if twin is not None:
        db.rollback()
        raise RemediationConflictError(
            f"Contenu identique à la version {twin.version_number} "
            f"({twin.state}) : aucun nouveau contenu à appliquer."
        )

    worker_token = str(uuid.uuid4())
    max_number = db.scalar(
        select(DocumentVersion.version_number)
        .where(DocumentVersion.document_id == doc.id)
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    )
    candidate = DocumentVersion(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        organization_id=org_id,
        version_number=(max_number or 0) + 1,
        state="PENDING_INDEX",
        source_checksum=hashlib.sha256(new_bytes).hexdigest(),
        text_checksum=new_text_ck,
        parser_version=base.parser_version,
        chunker_version=CHUNKER_VERSION,
        chunk_id_scheme="version_id_v3",
        page_count=1,
        origin="patch",
        supersedes_version_id=base.id,
        canonical_format=base.canonical_format,
        filename=base.filename,
        byte_size=len(new_bytes),
        activation_token=worker_token,
        activation_started_at=_now(),
        activation_heartbeat_at=_now(),
    )
    candidate.pages = [DocumentPage(document_id=doc.id, page_number=1, text=new_page)]
    db.add(candidate)
    db.flush()
    materialize_version_chunks(db, candidate)
    row = PatchDecision(
        proposal_id=proposal_id,
        decision=decision,
        final_text_fr=final_text,
        final_text_checksum=hashlib.sha256(final_text.encode("utf-8")).hexdigest(),
        result_version_id=candidate.id,
        actor_label=actor_label,
    )
    db.add(row)
    db.flush()
    append_version_event(
        db, doc.id, "version_created",
        {
            "document_version_id": candidate.id,
            "version_number": candidate.version_number,
            "origin": "patch",
            "supersedes_version_id": base.id,
            "proposal_id": proposal_id,
            "decision_id": row.id,
            "activation_token": worker_token,
            "source_checksum": candidate.source_checksum,
            "text_checksum": candidate.text_checksum,
        },
        actor_label,
    )
    db.commit()

    return _index_and_activate(
        db, org_id, case_id, proposal, row.id, candidate.id, worker_token,
        actor_label=actor_label,
    )


# ------------------------------------------------------- indexing + Tx B


def _fenced(db: Session, version_id: str, token: str, **values) -> bool:
    """Token-fenced candidate mutation; True iff this worker still owned it."""
    result = db.execute(
        update(DocumentVersion)
        .where(
            DocumentVersion.id == version_id,
            DocumentVersion.activation_token == token,
        )
        .values(**values)
    )
    return result.rowcount == 1


def _index_candidate_points(
    db: Session, org_id: str, version_id: str, token: str
) -> None:
    """Lock-free candidate indexing with token-fenced heartbeats. Raises on
    Qdrant/embedding failure (caller marks INDEX_FAILED)."""
    rows = db.scalars(
        select(Chunk).where(Chunk.document_version_id == version_id)
    ).all()
    db.rollback()  # no transaction held across embedding/Qdrant work
    qdrant.ensure_collection()
    vectors = embed_texts([r.text for r in rows])
    _fenced(db, version_id, token, activation_heartbeat_at=_now())
    db.commit()
    qdrant.upsert_points([_chunk_point(r, org_id, v) for r, v in zip(rows, vectors)])
    _fenced(db, version_id, token, activation_heartbeat_at=_now())
    db.commit()


def _index_and_activate(
    db: Session,
    org_id: str,
    case_id: str,
    proposal: PatchProposal,
    decision_id: str,
    candidate_id: str,
    worker_token: str,
    *,
    actor_label: str | None,
) -> dict:
    indexed_at = None
    try:
        _index_candidate_points(db, org_id, candidate_id, worker_token)
        indexed_at = _now()
    except Exception as exc:  # Qdrant/embedding failure -> INDEX_FAILED
        db.rollback()
        case, doc = _lock_activation_scope(db, org_id, case_id, proposal)
        # the failing worker is done with the candidate: clear its token so
        # recovery is possible immediately (no fake stale-lease wait)
        if _fenced(
            db, candidate_id, worker_token,
            state="INDEX_FAILED",
            activation_error=f"indexation échouée : {exc}",
            activation_token=None,
            activation_started_at=None,
            activation_heartbeat_at=None,
        ):
            append_version_event(
                db, doc.id, "version_index_failed",
                {
                    "document_version_id": candidate_id,
                    "error": str(exc),
                    "activation_token": worker_token,
                },
                actor_label,
            )
            db.commit()
        else:
            db.rollback()
        return {"outcome": "index_failed", "decision_id": decision_id, "version_id": candidate_id}

    return _activate_candidate(
        db, org_id, case_id, proposal, decision_id, candidate_id, worker_token,
        indexed_at=indexed_at, actor_label=actor_label,
    )


def _abandon(
    db: Session,
    doc: Document,
    case_id: str,
    proposal: PatchProposal | None,
    candidate: DocumentVersion,
    worker_token: str,
    reason: str,
    *,
    actor_label: str | None,
) -> None:
    """Terminal abandonment (token-fenced) + both event streams. Caller holds
    the locks and commits."""
    if not _fenced(
        db, candidate.id, worker_token,
        state="ABANDONED",
        abandoned_reason=reason,
        activation_token=None,
        activation_started_at=None,
        activation_heartbeat_at=None,
        activation_error=None,
    ):
        raise RemediationConflictError(LEASE_LOST_FR)
    append_version_event(
        db, doc.id, "version_activation_abandoned",
        {
            "document_version_id": candidate.id,
            "abandoned_reason": reason,
            "activation_token": worker_token,
        },
        actor_label,
    )
    append_event(
        db, case_id, "patch_activation_abandoned",
        {
            "document_id": doc.id,
            "version_id": candidate.id,
            "abandoned_reason": reason,
            "proposal_id": proposal.id if proposal else None,
        },
        actor_label,
    )


def _activate_candidate(
    db: Session,
    org_id: str,
    case_id: str,
    proposal: PatchProposal,
    decision_id: str,
    candidate_id: str,
    worker_token: str,
    *,
    indexed_at: datetime | None,
    actor_label: str | None,
) -> dict:
    """Tx B: the activation switch. Every candidate mutation is token-fenced."""
    case, doc = _lock_activation_scope(db, org_id, case_id, proposal)
    candidate = db.get(DocumentVersion, candidate_id, with_for_update=True)

    # gate 1: token ownership — a lost token means another worker recovered
    # the activation; report ITS state deterministically, mutate nothing.
    if candidate.activation_token != worker_token:
        db.rollback()
        candidate = db.get(DocumentVersion, candidate_id)
        if candidate.state == "ACTIVE":
            return {"outcome": "already_active", "decision_id": decision_id, "version_id": candidate_id}
        if candidate.state == "ABANDONED":
            return {
                "outcome": f"abandoned:{candidate.abandoned_reason}",
                "decision_id": decision_id,
                "version_id": candidate_id,
            }
        return {"outcome": "pending", "decision_id": decision_id, "version_id": candidate_id}

    # gate 2: a RUNNING assessment froze the old corpus — temporary conflict,
    # candidate stays recoverable with a cleared token (no fake stale wait).
    if running_assessment_id(db, org_id):
        _fenced(
            db, candidate_id, worker_token,
            activation_token=None,
            activation_started_at=None,
            activation_heartbeat_at=None,
            activation_error="assessment_conflict",
        )
        db.commit()
        return {"outcome": "assessment_conflict", "decision_id": decision_id, "version_id": candidate_id}

    # gate 3: authority — the action/plan/evidence pins must still hold.
    action = db.get(RemediationAction, proposal.action_id)
    if action.lifecycle != "APPROVED" or action.review_count != proposal.input_action_review_count:
        _abandon(db, doc, case_id, proposal, candidate, worker_token, "stale_action", actor_label=actor_label)
        db.commit()
        return {"outcome": "abandoned:stale_action", "decision_id": decision_id, "version_id": candidate_id}
    if (
        case.status == "CLOSED"
        or case.active_plan_id != proposal.input_plan_id
        or case.evidence_revision != proposal.input_case_evidence_revision
    ):
        _abandon(db, doc, case_id, proposal, candidate, worker_token, "authority_lost", actor_label=actor_label)
        db.commit()
        return {"outcome": "abandoned:authority_lost", "decision_id": decision_id, "version_id": candidate_id}

    # gate 4: CAS on the base pointer.
    base = db.get(DocumentVersion, candidate.supersedes_version_id, with_for_update=True)
    if (
        doc.current_version_id != base.id
        or base.state != "ACTIVE"
        or candidate.state not in ("PENDING_INDEX", "INDEX_FAILED")
    ):
        _abandon(db, doc, case_id, proposal, candidate, worker_token, "stale_base", actor_label=actor_label)
        db.commit()
        return {"outcome": "abandoned:stale_base", "decision_id": decision_id, "version_id": candidate_id}

    # gate 5: org-wide current source-checksum uniqueness (documents mirror).
    conflict = db.scalar(
        select(Document.id).where(
            Document.organization_id == org_id,
            Document.checksum == candidate.source_checksum,
            Document.id != doc.id,
        )
    )
    if conflict is not None:
        _abandon(db, doc, case_id, proposal, candidate, worker_token, "checksum_conflict", actor_label=actor_label)
        db.commit()
        return {"outcome": "abandoned:checksum_conflict", "decision_id": decision_id, "version_id": candidate_id}

    # success: SUPERSEDED first (flushed) vs the one-ACTIVE partial unique.
    base.state = "SUPERSEDED"
    db.flush()
    if not _fenced(
        db, candidate_id, worker_token,
        state="ACTIVE",
        activation_token=None,
        activation_started_at=None,
        activation_heartbeat_at=None,
        activation_error=None,
    ):
        db.rollback()
        raise RemediationConflictError(LEASE_LOST_FR)
    doc.current_version_id = candidate_id
    doc.checksum = candidate.source_checksum
    doc.page_count = candidate.page_count
    doc.parser_version = candidate.parser_version
    payload_common = {
        "document_version_id": candidate_id,
        "base_version_id": base.id,
        "activation_token": worker_token,
        "proposal_id": proposal.id,
        "decision_id": decision_id,
        "indexed_at": indexed_at.isoformat() if indexed_at else None,
    }
    append_version_event(db, doc.id, "version_indexed", payload_common, actor_label)
    append_version_event(db, doc.id, "version_activated", payload_common, actor_label)
    append_event(
        db, case_id, "patch_approved",
        {
            "proposal_id": proposal.id,
            "decision_id": decision_id,
            "decision": db.get(PatchDecision, decision_id).decision,
            "document_id": doc.id,
            "base_version_id": base.id,
            "result_version_id": candidate_id,
        },
        actor_label,
    )
    base_chunk_ids = [
        cid
        for cid in db.scalars(
            select(Chunk.id).where(Chunk.document_version_id == base.id)
        ).all()
    ]
    db.commit()

    # post-commit GC of the superseded points: failure is reconciliation debt,
    # never a correctness problem (snapshot filter + hydration).
    try:
        qdrant.delete_points_by_ids([qdrant.point_id(cid) for cid in base_chunk_ids])
    except Exception:
        pass
    return {"outcome": "activated", "decision_id": decision_id, "version_id": candidate_id}


# --------------------------------------------------------------- recovery


def recover_patch_activation(
    db: Session,
    org_id: str,
    case_id: str,
    proposal_id: str,
    *,
    actor_label: str | None = None,
    lease_seconds: int = ACTIVATION_LEASE_SECONDS,
) -> dict:
    """Re-drive a stranded activation (crash, timeout, assessment conflict).
    Takes over the token — fencing any stale worker out — then re-runs
    indexing + Tx B idempotently. ABANDONED is terminal; an already-ACTIVE
    result is an idempotent success."""
    proposal = db.get(PatchProposal, proposal_id)
    if proposal is None or proposal.case_id != case_id:
        raise RemediationNotFoundError("Proposition de correctif introuvable.")
    decision = db.scalar(
        select(PatchDecision).where(PatchDecision.proposal_id == proposal_id)
    )
    if decision is None or decision.result_version_id is None:
        raise RemediationConflictError(
            "Aucune activation à reprendre : la proposition n'a pas de "
            "décision d'application."
        )

    case, doc = _lock_activation_scope(db, org_id, case_id, proposal)
    candidate = db.get(DocumentVersion, decision.result_version_id, with_for_update=True)
    if candidate.state == "ACTIVE":
        db.rollback()
        return {"outcome": "already_active", "decision_id": decision.id, "version_id": candidate.id}
    if candidate.state == "ABANDONED":
        db.rollback()
        return {
            "outcome": f"abandoned:{candidate.abandoned_reason}",
            "decision_id": decision.id,
            "version_id": candidate.id,
        }
    heartbeat = _aware(candidate.activation_heartbeat_at)
    if (
        candidate.activation_token is not None
        and heartbeat is not None
        and _now() - heartbeat < timedelta(seconds=lease_seconds)
    ):
        db.rollback()
        raise RemediationConflictError(
            "Une activation est encore en cours pour cette version ; "
            "réessayez lorsque son verrou aura expiré."
        )
    worker_token = str(uuid.uuid4())
    candidate.state = "PENDING_INDEX"  # INDEX_FAILED re-drive resets the state
    candidate.activation_token = worker_token
    candidate.activation_started_at = _now()
    candidate.activation_heartbeat_at = _now()
    candidate.activation_error = None
    append_version_event(
        db, doc.id, "version_recovered",
        {
            "document_version_id": candidate.id,
            "activation_token": worker_token,
            "proposal_id": proposal_id,
        },
        actor_label,
    )
    db.commit()

    return _index_and_activate(
        db, org_id, case_id, proposal, decision.id, candidate.id, worker_token,
        actor_label=actor_label,
    )


# --------------------------------------------------------------- artifacts

ARTIFACT_TARGET_FORMATS = ("pdf", "docx")


def _sanitize_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "._- ").strip() or "proposition.md"


def draft_artifact(
    db: Session,
    session_factory,
    org_id: str,
    case_id: str,
    action_id: str,
    document_id: str,
    *,
    actor_label: str | None = None,
    lease_seconds: int = DRAFTING_LEASE_SECONDS,
):
    """Draft a Markdown revision proposal for a PDF/DOCX target. Same guard
    rails, staleness pins and DRAFTING lease as the patch drafter; the output
    is ONLY a RemediationArtifact — the patch/artifact flow can never create
    a PDF/DOCX version (only an explicit human superseding upload can)."""
    from app.models import RemediationArtifact
    from app.remediation.prompts import build_artifact_messages
    from app.remediation.schema import ArtifactDraft

    case = lock_case(db, org_id, case_id)
    action = _operable_action(db, case, action_id)
    if action.lifecycle != "APPROVED":
        db.rollback()
        raise RemediationConflictError(
            "Un artefact ne peut être proposé que pour une action APPROVED "
            f"(statut actuel : {action.lifecycle})."
        )
    if action.action_type != "document_amendment":
        db.rollback()
        raise RemediationInvalidError(
            "La proposition de rédaction ne s'applique qu'aux actions de type "
            "« document_amendment »."
        )
    doc = db.get(Document, document_id)
    if doc is None or doc.organization_id != org_id:
        db.rollback()
        raise RemediationNotFoundError("Document introuvable pour cette organisation.")
    if doc.current_version_id is None:
        db.rollback()
        raise RemediationInvalidError("Ce document n'a pas de version analysée exploitable.")
    version = db.get(DocumentVersion, doc.current_version_id)
    if version.canonical_format not in ARTIFACT_TARGET_FORMATS:
        db.rollback()
        raise RemediationInvalidError(
            "La proposition de rédaction (artefact) est réservée aux documents "
            "PDF/DOCX ; pour un TXT/Markdown, utilisez le correctif ancré."
        )

    for stale in db.scalars(
        select(RemediationArtifact).where(
            RemediationArtifact.action_id == action_id,
            RemediationArtifact.status == "DRAFTING",
        )
    ).all():
        heartbeat = _aware(stale.drafting_heartbeat_at)
        if heartbeat is not None and _now() - heartbeat < timedelta(seconds=lease_seconds):
            db.rollback()
            raise RemediationConflictError(DRAFT_IN_PROGRESS_FR)
        stale.status = "ABSTAINED"
        stale.abstain_reason = "draft_interrupted"
        stale.drafting_token = None
        stale.drafting_started_at = None
        stale.drafting_heartbeat_at = None
        append_event(
            db, case_id, "artifact_abstained",
            {
                "artifact_id": stale.id,
                "action_id": action_id,
                "abstain_reason": "draft_interrupted",
                "attempts": stale.attempts,
            },
            actor_label,
        )

    context = action_context(db, case, action)
    pages = [{"page": p.page_number, "texte": p.text} for p in version.pages]
    token = str(uuid.uuid4())
    artifact = RemediationArtifact(
        case_id=case_id,
        action_id=action_id,
        document_id=doc.id,
        document_version_id=version.id,
        base_text_checksum=version.text_checksum,
        canonical_format=version.canonical_format,
        requirement_ids=[r["id"] for r in context["requirements"]],
        requirements_snapshot=context["requirements"],
        status="DRAFTING",
        drafting_token=token,
        drafting_started_at=_now(),
        drafting_heartbeat_at=_now(),
        prompt_version=PATCH_PROMPT_VERSION,
        **context["pins"],
    )
    db.add(artifact)
    db.commit()
    artifact_id = artifact.id

    lease_lost = False

    def _heartbeat() -> None:
        nonlocal lease_lost
        if lease_lost:
            return
        hb = None
        try:
            hb = session_factory()
            result = hb.execute(
                update(RemediationArtifact)
                .where(
                    RemediationArtifact.id == artifact_id,
                    RemediationArtifact.drafting_token == token,
                )
                .values(drafting_heartbeat_at=_now())
            )
            hb.commit()
            if result.rowcount != 1:
                lease_lost = True
        except Exception:
            lease_lost = True
        finally:
            if hb is not None:
                hb.close()

    base_messages = build_artifact_messages(
        context["action_snapshot"],
        context["requirements"],
        {"document": doc.filename, "format": version.canonical_format, "pages": pages},
    )
    schema = ArtifactDraft.model_json_schema()
    messages = base_messages
    verified = None
    abstain_reason: str | None = None
    attempts_meta: list[dict] = []
    calls: list[tuple[int, llm_service.LLMCall]] = []

    from app.remediation.prompts import build_repair_messages as _repair

    for attempt_number in range(1, MAX_DRAFT_ATTEMPTS + 1):
        outcome = llm_service.complete_json(
            messages,
            json_schema=schema,
            schema_name="artifact_draft",
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
        try:
            payload = json.loads(raw_draft)
        except json.JSONDecodeError as exc:
            parsed, errors = None, [f"JSON invalide : {exc}."]
        else:
            try:
                parsed = ArtifactDraft.model_validate(payload)
                errors = []
            except ValidationError as exc:
                parsed = None
                details = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                    for e in exc.errors()
                )
                errors = [f"schéma invalide : {details}."]
        attempts_meta.append(
            {
                "attempt_number": attempt_number,
                "parsed_ok": parsed is not None,
                "validation_errors": errors,
            }
        )
        if not errors:
            verified = parsed
            break
        messages = _repair(base_messages, raw_draft, errors)

    if verified is None and abstain_reason is None:
        abstain_reason = "schema_invalid"

    case = lock_case(db, org_id, case_id)
    artifact = db.get(RemediationArtifact, artifact_id)
    if artifact is None or artifact.drafting_token != token or lease_lost:
        db.rollback()
        raise RemediationConflictError(LEASE_LOST_FR)
    artifact.attempts = len(attempts_meta)
    artifact.drafting_token = None
    artifact.drafting_started_at = None
    artifact.drafting_heartbeat_at = None
    all_errors = [e for m in attempts_meta for e in m["validation_errors"]]
    artifact.verifier_errors = all_errors or None
    if verified is not None:
        stem = doc.filename.rsplit(".", 1)[0]
        artifact.status = "VERIFIED"
        artifact.filename = _sanitize_filename(
            f"proposition_{stem}_{_now().date().isoformat()}.md"
        )
        artifact.content_md = verified.content_md
        artifact.rationale = verified.rationale
        append_event(
            db, case_id, "artifact_created",
            {
                "artifact_id": artifact.id,
                "action_id": action_id,
                "document_id": doc.id,
                "document_version_id": version.id,
                "filename": artifact.filename,
                "attempts": artifact.attempts,
            },
            actor_label,
        )
    else:
        artifact.status = "ABSTAINED"
        artifact.abstain_reason = abstain_reason
        append_event(
            db, case_id, "artifact_abstained",
            {
                "artifact_id": artifact.id,
                "action_id": action_id,
                "abstain_reason": abstain_reason,
                "attempts": artifact.attempts,
            },
            actor_label,
        )

    call_number = 0
    for meta in attempts_meta:
        attempt = RemediationAttempt(
            case_id=case_id,
            stage="artifact",
            remediation_artifact_id=artifact.id,
            attempt_number=meta["attempt_number"],
            prompt_version=PATCH_PROMPT_VERSION,
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
                    prompt_version=PATCH_PROMPT_VERSION,
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
    db.commit()
    return artifact


# ------------------------------------------------------ superseding uploads

FORMAT_FAMILIES = {"pdf": "pdf", "docx": "docx", "txt": "textuel", "md": "textuel"}


def _artifact_authority_errors(db: Session, artifact, base: DocumentVersion) -> str | None:
    """Round-4 artifact authority recheck (shared by upload Tx A, Tx B and
    recovery): None when the corrective-action lineage still holds, else the
    typed abandoned_reason."""
    action = db.get(RemediationAction, artifact.action_id)
    case = db.get(RemediationCase, artifact.case_id)
    if (
        artifact.status != "VERIFIED"
        or artifact.document_id != base.document_id
        or artifact.document_version_id != base.id
    ):
        return "authority_lost"
    if (
        action is None
        or action.lifecycle != "APPROVED"
        or action.action_type != "document_amendment"
        or action.review_count != artifact.input_action_review_count
    ):
        return "stale_action"
    if (
        case.status == "CLOSED"
        or case.active_plan_id != artifact.input_plan_id
        or case.evidence_revision != artifact.input_case_evidence_revision
    ):
        return "authority_lost"
    return None


def supersede_upload(
    db: Session,
    org_id: str,
    *,
    supersedes_version_id: str,
    remediation_artifact_id: str | None,
    filename: str,
    data: bytes,
    content_type: str | None,
    pages: list[str],
    canonical_format: str,
    actor_label: str | None = None,
) -> dict:
    """Explicit human superseding re-upload: the ONLY way a PDF/DOCX gets a
    new version. Caller (api/documents.py) already holds the org lock and
    checked no assessment is RUNNING, and has parsed the bytes. Returns the
    activation outcome dict (same contract as decide_patch)."""
    from app.models import RemediationArtifact
    from app.services.parsing import PARSER_VERSION

    base = db.get(DocumentVersion, supersedes_version_id, with_for_update=True)
    if base is None or base.organization_id != org_id:
        db.rollback()
        raise RemediationNotFoundError("Version à remplacer introuvable.")
    artifact = None
    if remediation_artifact_id is not None:
        artifact = db.get(RemediationArtifact, remediation_artifact_id)
        if artifact is None:
            db.rollback()
            raise RemediationNotFoundError("Artefact de remédiation introuvable.")
        # lock order org -> case -> document -> versions
        lock_case(db, org_id, artifact.case_id)
    doc = db.get(Document, base.document_id, with_for_update=True)
    if doc.current_version_id != base.id or base.state != "ACTIVE":
        db.rollback()
        raise RemediationConflictError(
            "supersedes_version_id ne désigne pas la version ACTIVE actuelle "
            "du document ; rechargez et réessayez."
        )
    if FORMAT_FAMILIES[canonical_format] != FORMAT_FAMILIES[base.canonical_format]:
        db.rollback()
        raise RemediationInvalidError(
            f"Famille de format incompatible : la version actuelle est "
            f"{base.canonical_format}, le fichier téléversé est {canonical_format}."
        )
    if artifact is not None:
        reason = _artifact_authority_errors(db, artifact, base)
        if reason is not None:
            db.rollback()
            raise RemediationConflictError(
                "La proposition (artefact) ne fait plus autorité "
                f"({reason}) : l'action, le plan ou la version cible a changé."
            )

    new_text_ck = text_checksum(pages)
    twin = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == doc.id,
            DocumentVersion.text_checksum == new_text_ck,
            DocumentVersion.state != "ABANDONED",
        )
    )
    if twin is not None:
        # retry idempotency: the SAME supersession attempt resumes its
        # candidate; anything else is a per-document content conflict
        if (
            twin.state in ("PENDING_INDEX", "INDEX_FAILED")
            and twin.supersedes_version_id == supersedes_version_id
            and twin.canonical_format == canonical_format
            and twin.source_artifact_id == remediation_artifact_id
        ):
            db.rollback()
            return {"outcome": "pending", "decision_id": None, "version_id": twin.id}
        db.rollback()
        raise RemediationConflictError(
            f"Contenu identique à la version {twin.version_number} "
            f"({twin.state}) de ce document."
        )

    worker_token = str(uuid.uuid4())
    max_number = db.scalar(
        select(DocumentVersion.version_number)
        .where(DocumentVersion.document_id == doc.id)
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    )
    candidate = DocumentVersion(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        organization_id=org_id,
        version_number=(max_number or 0) + 1,
        state="PENDING_INDEX",
        source_checksum=hashlib.sha256(data).hexdigest(),
        text_checksum=new_text_ck,
        parser_version=PARSER_VERSION,
        chunker_version=CHUNKER_VERSION,
        chunk_id_scheme="version_id_v3",
        page_count=len(pages),
        origin="upload",
        supersedes_version_id=base.id,
        source_artifact_id=remediation_artifact_id,
        canonical_format=canonical_format,
        filename=filename,
        reported_mime=content_type,
        byte_size=len(data),
        activation_token=worker_token,
        activation_started_at=_now(),
        activation_heartbeat_at=_now(),
    )
    candidate.pages = [
        DocumentPage(document_id=doc.id, page_number=i + 1, text=text)
        for i, text in enumerate(pages)
    ]
    db.add(candidate)
    db.flush()
    materialize_version_chunks(db, candidate)
    append_version_event(
        db, doc.id, "version_created",
        {
            "document_version_id": candidate.id,
            "version_number": candidate.version_number,
            "origin": "upload",
            "supersedes_version_id": base.id,
            "source_artifact_id": remediation_artifact_id,
            "activation_token": worker_token,
            "source_checksum": candidate.source_checksum,
            "text_checksum": candidate.text_checksum,
        },
        actor_label,
    )
    db.commit()

    return _index_and_activate_upload(
        db, org_id, candidate.id, worker_token, actor_label=actor_label
    )


def _index_and_activate_upload(
    db: Session, org_id: str, candidate_id: str, worker_token: str, *, actor_label
) -> dict:
    indexed_at = None
    try:
        _index_candidate_points(db, org_id, candidate_id, worker_token)
        indexed_at = _now()
    except Exception as exc:
        db.rollback()
        candidate = db.get(DocumentVersion, candidate_id)
        db.get(Document, candidate.document_id, with_for_update=True)
        if _fenced(
            db, candidate_id, worker_token,
            state="INDEX_FAILED",
            activation_error=f"indexation échouée : {exc}",
            activation_token=None,
            activation_started_at=None,
            activation_heartbeat_at=None,
        ):
            append_version_event(
                db, candidate.document_id, "version_index_failed",
                {
                    "document_version_id": candidate_id,
                    "error": str(exc),
                    "activation_token": worker_token,
                },
                actor_label,
            )
            db.commit()
        else:
            db.rollback()
        return {"outcome": "index_failed", "decision_id": None, "version_id": candidate_id}
    return _activate_upload_candidate(
        db, org_id, candidate_id, worker_token, indexed_at=indexed_at,
        actor_label=actor_label,
    )


def _activate_upload_candidate(
    db: Session,
    org_id: str,
    candidate_id: str,
    worker_token: str,
    *,
    indexed_at: datetime | None,
    actor_label: str | None,
) -> dict:
    """Tx B, upload variant. Twin of _activate_candidate minus the patch
    gates, plus the artifact authority recheck when lineage is present —
    keep the two in step when the protocol evolves."""
    from app.models import RemediationArtifact

    org = lock_organization(db, org_id)
    if org is None:
        db.rollback()
        raise RemediationNotFoundError("Organisation introuvable.")
    peek = db.get(DocumentVersion, candidate_id)
    artifact = (
        db.get(RemediationArtifact, peek.source_artifact_id)
        if peek.source_artifact_id
        else None
    )
    if artifact is not None:
        lock_case(db, org_id, artifact.case_id)
    doc = db.get(Document, peek.document_id, with_for_update=True)
    candidate = db.get(DocumentVersion, candidate_id, with_for_update=True)

    if candidate.activation_token != worker_token:
        db.rollback()
        candidate = db.get(DocumentVersion, candidate_id)
        if candidate.state == "ACTIVE":
            return {"outcome": "already_active", "decision_id": None, "version_id": candidate_id}
        if candidate.state == "ABANDONED":
            return {
                "outcome": f"abandoned:{candidate.abandoned_reason}",
                "decision_id": None,
                "version_id": candidate_id,
            }
        return {"outcome": "pending", "decision_id": None, "version_id": candidate_id}

    if running_assessment_id(db, org_id):
        _fenced(
            db, candidate_id, worker_token,
            activation_token=None,
            activation_started_at=None,
            activation_heartbeat_at=None,
            activation_error="assessment_conflict",
        )
        db.commit()
        return {"outcome": "assessment_conflict", "decision_id": None, "version_id": candidate_id}

    def _abandon_upload(reason: str) -> dict:
        if not _fenced(
            db, candidate_id, worker_token,
            state="ABANDONED",
            abandoned_reason=reason,
            activation_token=None,
            activation_started_at=None,
            activation_heartbeat_at=None,
            activation_error=None,
        ):
            db.rollback()
            raise RemediationConflictError(LEASE_LOST_FR)
        append_version_event(
            db, doc.id, "version_activation_abandoned",
            {
                "document_version_id": candidate_id,
                "abandoned_reason": reason,
                "activation_token": worker_token,
            },
            actor_label,
        )
        if artifact is not None:
            append_event(
                db, artifact.case_id, "patch_activation_abandoned",
                {
                    "document_id": doc.id,
                    "version_id": candidate_id,
                    "abandoned_reason": reason,
                    "artifact_id": artifact.id,
                },
                actor_label,
            )
        db.commit()
        return {
            "outcome": f"abandoned:{reason}",
            "decision_id": None,
            "version_id": candidate_id,
        }

    if artifact is not None:
        base_for_check = db.get(DocumentVersion, candidate.supersedes_version_id)
        reason = _artifact_authority_errors(db, artifact, base_for_check)
        if reason is not None:
            return _abandon_upload(reason)

    base = db.get(DocumentVersion, candidate.supersedes_version_id, with_for_update=True)
    if (
        doc.current_version_id != base.id
        or base.state != "ACTIVE"
        or candidate.state not in ("PENDING_INDEX", "INDEX_FAILED")
    ):
        return _abandon_upload("stale_base")

    conflict = db.scalar(
        select(Document.id).where(
            Document.organization_id == org_id,
            Document.checksum == candidate.source_checksum,
            Document.id != doc.id,
        )
    )
    if conflict is not None:
        return _abandon_upload("checksum_conflict")

    base.state = "SUPERSEDED"
    db.flush()
    if not _fenced(
        db, candidate_id, worker_token,
        state="ACTIVE",
        activation_token=None,
        activation_started_at=None,
        activation_heartbeat_at=None,
        activation_error=None,
    ):
        db.rollback()
        raise RemediationConflictError(LEASE_LOST_FR)
    doc.current_version_id = candidate_id
    doc.checksum = candidate.source_checksum
    doc.page_count = candidate.page_count
    doc.parser_version = candidate.parser_version
    doc.filename = candidate.filename
    doc.content_type = candidate.reported_mime or doc.content_type
    payload_common = {
        "document_version_id": candidate_id,
        "base_version_id": base.id,
        "activation_token": worker_token,
        "source_artifact_id": candidate.source_artifact_id,
        "indexed_at": indexed_at.isoformat() if indexed_at else None,
    }
    append_version_event(db, doc.id, "version_indexed", payload_common, actor_label)
    append_version_event(db, doc.id, "version_activated", payload_common, actor_label)
    if artifact is not None:
        superseded_event = append_version_event(
            db, doc.id, "version_superseded_by_upload",
            {
                "document_version_id": candidate_id,
                "superseded_version_id": base.id,
                "source_artifact_id": artifact.id,
            },
            actor_label,
        )
        append_event(
            db, artifact.case_id, "version_superseded_by_upload",
            {
                "artifact_id": artifact.id,
                "document_id": doc.id,
                "superseded_version_id": base.id,
                "new_version_id": candidate_id,
                "document_version_event_id": superseded_event.id,
            },
            actor_label,
        )
    base_chunk_ids = db.scalars(
        select(Chunk.id).where(Chunk.document_version_id == base.id)
    ).all()
    db.commit()
    try:
        qdrant.delete_points_by_ids([qdrant.point_id(cid) for cid in base_chunk_ids])
    except Exception:
        pass
    return {"outcome": "activated", "decision_id": None, "version_id": candidate_id}


def recover_upload_activation(
    db: Session,
    org_id: str,
    document_id: str,
    version_id: str,
    *,
    actor_label: str | None = None,
    lease_seconds: int = ACTIVATION_LEASE_SECONDS,
) -> dict:
    """Re-drive a stranded superseding-upload activation (twin of
    recover_patch_activation)."""
    org = lock_organization(db, org_id)
    if org is None:
        db.rollback()
        raise RemediationNotFoundError("Organisation introuvable.")
    candidate = db.get(DocumentVersion, version_id, with_for_update=True)
    if (
        candidate is None
        or candidate.document_id != document_id
        or candidate.organization_id != org_id
    ):
        db.rollback()
        raise RemediationNotFoundError("Version de document introuvable.")
    doc = db.get(Document, document_id, with_for_update=True)
    if candidate.state == "ACTIVE":
        db.rollback()
        return {"outcome": "already_active", "decision_id": None, "version_id": version_id}
    if candidate.state == "ABANDONED":
        db.rollback()
        return {
            "outcome": f"abandoned:{candidate.abandoned_reason}",
            "decision_id": None,
            "version_id": version_id,
        }
    if candidate.state not in ("PENDING_INDEX", "INDEX_FAILED"):
        db.rollback()
        raise RemediationConflictError(
            "Cette version n'est pas une activation à reprendre "
            f"(état : {candidate.state})."
        )
    heartbeat = _aware(candidate.activation_heartbeat_at)
    if (
        candidate.activation_token is not None
        and heartbeat is not None
        and _now() - heartbeat < timedelta(seconds=lease_seconds)
    ):
        db.rollback()
        raise RemediationConflictError(
            "Une activation est encore en cours pour cette version ; "
            "réessayez lorsque son verrou aura expiré."
        )
    worker_token = str(uuid.uuid4())
    candidate.state = "PENDING_INDEX"
    candidate.activation_token = worker_token
    candidate.activation_started_at = _now()
    candidate.activation_heartbeat_at = _now()
    candidate.activation_error = None
    append_version_event(
        db, doc.id, "version_recovered",
        {"document_version_id": version_id, "activation_token": worker_token},
        actor_label,
    )
    db.commit()
    return _index_and_activate_upload(
        db, org_id, version_id, worker_token, actor_label=actor_label
    )
