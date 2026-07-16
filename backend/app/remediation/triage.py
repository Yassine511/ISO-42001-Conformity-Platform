"""Triage drafter (M7a): similar-gap search + LLM-suggested triage.

Input-revision contract (stale-input protection):
1. under the case lock, snapshot evidence_revision + the exact finding-link
   snapshots, then RELEASE the lock (no LLM/network call under locks);
2. run the similar-gap search and the ≤2-attempt LLM loop;
3. relock the case and require status == 'TRIAGE' AND evidence_revision ==
   the snapshot before persisting — a stale result is DISCARDED (409), never
   persisted against a different case composition.

Abstention taxonomy (models.REMEDIATION_ABSTAIN_REASONS):
- schema_invalid: both attempts failed JSON/schema validation;
- llm_error / rate_limited: provider trail exhausted (classify_failure);
- retrieval_error: Qdrant/search failed BEFORE any LLM call — the draft row
  is still persisted (ABSTAINED) so case creation returns 201 with an
  auditable abstention instead of an ambiguous 503.
"""

import json
from dataclasses import asdict

from pydantic import ValidationError
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.models import (
    Finding,
    RemediationCase,
    RemediationTriageDraft,
)
from app.pipeline import llm as llm_service
from app.remediation.common import now as _now
from app.remediation.common import persist_attempt_calls
from app.remediation.prompts import (
    REMEDIATION_PROMPT_VERSION,
    build_repair_messages,
    build_triage_messages,
)
from app.remediation.schema import TriageDraft
from app.remediation.service import (
    ELIGIBLE_VERDICTS,
    RemediationConflictError,
    append_event,
    finding_snapshot,
    lock_case,
)
from app.services.retrieval import CorpusChangedError, hybrid_search, load_kb

MAX_DRAFT_ATTEMPTS = 2
# CorpusChangedError joins the tuple: same operational-abort class as Qdrant
# being down — an ABSTAINED(retrieval_error) draft, never a crash.
QDRANT_ERRORS = (
    ResponseHandlingException,
    UnexpectedResponse,
    ConnectionError,
    CorpusChangedError,
)

STALE_TRIAGE_FR = (
    "Résultat de triage périmé : les constats liés ou le statut du cas ont "
    "changé pendant la rédaction. Relancez le triage."
)


def _parse_triage(content: str) -> tuple[TriageDraft | None, list[str]]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        return None, [f"JSON invalide : {exc}. Rends un objet JSON valide et complet."]
    try:
        return TriageDraft.model_validate(payload), []
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return None, [f"schéma invalide : {details}. Respecte exactement le schéma demandé."]


def _similar_findings(db: Session, org_id: str, linked_ids: set[str]) -> list[dict]:
    """Other CONFIRMED gap findings of the org (existing-findings arm of the
    similar-gap search). Deterministic SQL, most recent first, capped."""
    from app.models import Assessment

    # Exclusion + cap in SQL, and only the columns this snapshot needs: the
    # full Finding row carries large JSON provenance (retrieved/audit_log)
    # that must not be hydrated just to build five summaries.
    query = (
        select(Finding)
        .options(
            load_only(
                Finding.id,
                Finding.requirement_id,
                Finding.requirement_fr,
                Finding.domain,
                Finding.human_verdict,
                Finding.human_rationale,
            )
        )
        .join(Assessment, Finding.assessment_id == Assessment.id)
        .where(
            Assessment.organization_id == org_id,
            Finding.review_status == "CONFIRMED",
            Finding.human_verdict.in_(ELIGIBLE_VERDICTS),
        )
        .order_by(Finding.reviewed_at.desc())
        .limit(5)
    )
    if linked_ids:
        query = query.where(Finding.id.not_in(linked_ids))
    return [
        {
            "finding_id": f.id,
            "requirement_id": f.requirement_id,
            "requirement_fr": f.requirement_fr,
            "domain": f.domain,
            "human_verdict": f.human_verdict,
            "human_rationale": f.human_rationale,
        }
        for f in db.scalars(query)
    ]


def _similar_corpus(db: Session, org_id: str, query: str) -> list[dict]:
    """Corpus arm of the similar-gap search: hybrid retrieval over BOTH the
    policy corpus and the ISO KB (spec §8 — similar gaps may surface either
    as policy passages or as related requirements)."""
    results = [asdict(i) for i in hybrid_search(db, org_id, query, k=5, scope="both")]
    return [
        {
            "source_id": r["result_id"],
            "type": r.get("source_type"),
            "document": r.get("filename"),
            "page": r.get("page_number"),
            "exigence": r.get("requirement_id"),
            "texte": r["text"],
        }
        for r in results
    ]


def draft_triage(
    db: Session,
    org_id: str,
    case_id: str,
    *,
    actor_label: str | None = None,
) -> RemediationTriageDraft:
    """Draft (or redraft) the triage proposal for a TRIAGE case. Returns the
    persisted draft row (VERIFIED or ABSTAINED). Raises
    RemediationConflictError when the case moved/changed mid-draft (stale
    result discarded) or is not in TRIAGE."""
    # ---- phase 1: snapshot under the case lock, then release ----
    case = lock_case(db, org_id, case_id)
    if case.status != "TRIAGE":
        db.rollback()
        raise RemediationConflictError(
            f"Triage impossible : statut {case.status} (TRIAGE requis)."
        )
    input_revision = case.evidence_revision
    links = list(case.finding_links)
    snapshots = [finding_snapshot(l) for l in links]
    linked_ids = {l.finding_id for l in links}
    corpus_version = load_kb()["corpus_version"]
    db.rollback()  # release the lock before search/LLM work

    # ---- phase 2a: similar-gap search (retrieval_error on failure) ----
    search_error: str | None = None
    similar_findings: list[dict] = []
    similar_corpus: list[dict] = []
    try:
        similar_findings = _similar_findings(db, org_id, linked_ids)
        primary = next((s for s in snapshots if s["is_primary"]), snapshots[0])
        query_parts = [
            primary.get("finding_requirement_fr") or primary["finding_requirement_id"],
            primary.get("finding_human_rationale") or "",
        ]
        similar_corpus = _similar_corpus(db, org_id, " ".join(p for p in query_parts if p))
    except QDRANT_ERRORS as exc:
        search_error = f"recherche indisponible : {exc}"
    finally:
        db.rollback()  # no connection held across the provider call

    attempts_meta: list[dict] = []
    calls: list[tuple[int, llm_service.LLMCall]] = []
    parsed: TriageDraft | None = None
    raw_draft: str | None = None
    abstain_reason: str | None = None
    final_model: str | None = None
    final_provider: str | None = None

    if search_error is not None:
        abstain_reason = "retrieval_error"
    else:
        # ---- phase 2b: LLM loop, ≤2 attempts, repair on parse failure ----
        base_messages = build_triage_messages(snapshots, similar_findings, similar_corpus)
        schema = TriageDraft.model_json_schema()
        messages = base_messages
        for attempt_number in range(1, MAX_DRAFT_ATTEMPTS + 1):
            outcome = llm_service.complete_json(
                messages, json_schema=schema, schema_name="triage_draft"
            )
            calls.extend((attempt_number, c) for c in outcome.calls)
            if outcome.content is None:
                abstain_reason = llm_service.classify_failure(outcome.calls)
                attempts_meta.append(
                    {
                        "attempt_number": attempt_number,
                        "parsed_ok": False,
                        "validation_errors": [
                            outcome.error or "tous les fournisseurs ont échoué"
                        ],
                    }
                )
                break
            raw_draft = outcome.content
            final_call = outcome.final_call
            if final_call is not None:
                final_provider = final_call.provider
                final_model = final_call.reported_model or final_call.requested_model
            parsed, errors = _parse_triage(raw_draft)
            attempts_meta.append(
                {
                    "attempt_number": attempt_number,
                    "parsed_ok": parsed is not None,
                    "validation_errors": errors,
                }
            )
            if parsed is not None:
                break
            messages = build_repair_messages(base_messages, raw_draft, errors)
        if parsed is None and abstain_reason is None:
            abstain_reason = "schema_invalid"

    # ---- phase 3: relock, revalidate, persist ----
    case = lock_case(db, org_id, case_id)
    if case.status != "TRIAGE" or case.evidence_revision != input_revision:
        db.rollback()
        raise RemediationConflictError(STALE_TRIAGE_FR)

    last = db.scalar(
        select(RemediationTriageDraft.sequence)
        .where(RemediationTriageDraft.case_id == case_id)
        .order_by(RemediationTriageDraft.sequence.desc())
        .limit(1)
    )
    draft = RemediationTriageDraft(
        case_id=case_id,
        sequence=(last or 0) + 1,
        status="VERIFIED" if parsed is not None else "ABSTAINED",
        abstain_reason=abstain_reason,
        ai_classification=parsed.classification if parsed else None,
        ai_correction_note=parsed.correction_note if parsed else None,
        ai_scope=parsed.scope if parsed else None,
        ai_scope_rationale=parsed.scope_rationale if parsed else None,
        raw_draft=raw_draft,
        input_evidence_revision=input_revision,
        input_finding_links=snapshots,
        similar_findings=similar_findings,
        similar_corpus=similar_corpus,
        draft_attempts=len(attempts_meta),
        prompt_version=REMEDIATION_PROMPT_VERSION,
        corpus_version=corpus_version,
        final_model=final_model,
        final_provider=final_provider,
    )
    db.add(draft)
    db.flush()

    persist_attempt_calls(
        db,
        case_id=case_id,
        stage="triage",
        triage_draft_id=draft.id,
        attempts_meta=attempts_meta,
        calls=calls,
        prompt_version=REMEDIATION_PROMPT_VERSION,
    )
    append_event(
        db, case_id, "triage_drafted",
        {
            "triage_draft_id": draft.id,
            "sequence": draft.sequence,
            "status": draft.status,
            "abstain_reason": draft.abstain_reason,
            "input_evidence_revision": input_revision,
        },
        actor_label,
    )
    case.updated_at = _now()
    db.commit()
    return draft
