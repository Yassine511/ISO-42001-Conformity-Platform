"""Grounded chat Q&A service (M4): retrieve → cited draft → verify → answer or abstain.

Plain synchronous flow, deliberately NOT a LangGraph graph: chat is linear and
single-shot — no checkpointing, resume or interrupt. Consistency with the M3
pipeline lives at the function level: same hybrid_search, same deterministic
verifier primitives, same HttpJsonLLM provider and failure classification.
Accepted trade-off: an unexpected exception mid-request persists nothing and a
crash between the provider call and the commit loses the paid call — chat is
idempotent to re-ask.

Transaction phasing: all DB reads happen up front, then db.rollback() releases
the read transaction (and its connection) BEFORE the ~60s provider call; a
short write transaction at the end persists everything in one commit.

Trust rules (adversarially reviewed):
- SEMANTICS OF "VERIFIED", stated precisely: verification is CITATION-LOCATION
  verification — the quote exists exactly after documented normalization
  (case, accents, whitespace, typography) in a retrieved passage, the clause
  id was actually retrieved for this question. It does NOT establish that the
  citation semantically supports the claim text (an authentic but irrelevant
  quote passes): semantic entailment is not deterministically checkable. Same
  posture as M3's VERIFIED-never-means-verdict-correct. Chat answers are under
  PASSIVE review: labelled AI drafts whose clickable references let the reader
  assess support (no formal chat-claim confirmation workflow — formal human
  confirmation exists for pipeline findings in the M5 workspace); citation
  quality is measured in M6. The claims payload therefore says
  `citations_verified`, never `verified`.
- A claim survives verification only if EVERY citation it references verified
  (exact match after normalization for policy quotes; clause membership in the
  KB requirements RETRIEVED for this question — a hallucinated-but-existing
  clause id is stripped). The user-visible answer is assembled server-side
  from surviving claims — prose whose support failed is never shown.
- A fuzzy quote match is stripped like a failure (M3 invariant: VERIFIED =
  exact only) but its QuoteMatch provenance is persisted for human review.
- Abstention text is a deterministic template, epistemically honest: top-k
  retrieval cannot prove corpus-wide absence, so it claims nothing beyond the
  retrieved passages, and the suggested clause is "à examiner", not a proven
  gap. Infrastructure failures get a variant that does NOT claim evidence
  absence.
- Copyright surface, stated honestly: KB citation display text is always
  hydrated server-side from load_kb() (structural guarantee); answer prose is
  prompt-constrained only — same residual surface as the pipeline's rationale.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import ChatLlmCall, ChatMessage, Conversation, Finding, Organization
from app.pipeline import llm as llm_service
from app.pipeline.state import AbstainReason
from app.pipeline.verifier import MIN_QUOTE_LEN, find_quote_in_retrieved, normalize
from app.chat.prompts import (
    CHAT_PROMPT_VERSION,
    build_chat_messages,
    build_chat_repair_messages,
)
from app.chat.schema import ChatDraft
from app.services.provenance import source_slice
from app.services.retrieval import hybrid_search, load_kb

MAX_DRAFT_ATTEMPTS = 2  # initial attempt + one repair retry (parse failures only)

STATUS_ANSWERED = "ANSWERED"
STATUS_ABSTAINED = "ABSTAINED"

KB_ONLY_CAVEAT = (
    "Aucun passage des politiques de l'organisation n'a été cité à l'appui de "
    "cette réponse : elle décrit les exigences d'ISO/IEC 42001, non votre "
    "couverture documentaire."
)

INFRA_ABSTENTION = (
    "Vérification impossible : les fournisseurs LLM sont indisponibles. "
    "Aucune conclusion documentaire ne peut être tirée ; réessayez ultérieurement."
)


def answer_citation_ids(claims: list[dict]) -> list[str]:
    """Ids of the citations that back the FINAL ANSWER: those referenced by
    surviving claims, in first-reference order. Everything else in the
    persisted `citations` list (unreferenced, or referenced only by dropped
    claims) is audit provenance and must not be rendered as answer evidence."""
    seen: list[str] = []
    for claim in claims:
        if not claim.get("citations_verified"):
            continue
        for cid in claim["citation_ids"]:
            if cid not in seen:
                seen.append(cid)
    return seen


class OrganizationNotFoundError(LookupError):
    pass


class ConversationNotFoundError(LookupError):
    pass


class FindingNotFoundError(LookupError):
    pass


def _finding_snapshot(finding: Finding) -> dict:
    """IMMUTABLE drill-down context, built exclusively from persisted columns
    at ask time. Persisted on the message (the UI replays it after finding
    deletion or re-review) and injected as a non-citable prompt block."""
    return {
        "finding_id": finding.id,
        "assessment_id": finding.assessment_id,
        "requirement_id": finding.requirement_id,
        "requirement_fr": finding.requirement_fr,  # snapshot column, never live KB
        "domain": finding.domain,
        "ai_status": finding.status,
        "ai_verdict": finding.verdict,
        "abstain_reason": finding.abstain_reason,
        "ai_rationale": finding.rationale,
        "review_status": finding.review_status,
        "review_action": finding.review_action,
        "human_verdict": finding.human_verdict,
        "human_rationale": finding.human_rationale,
        "review_count": finding.review_count,
        "reviewed_at": finding.reviewed_at.isoformat() if finding.reviewed_at else None,
        "evidence": {
            "matched_chunk_id": finding.matched_chunk_id,
            "match_start": finding.match_start,
            "match_end": finding.match_end,
            "match_method": finding.match_method,
        },
    }


@dataclass
class CitationOutcome:
    """Verification outcome for one draft citation (full provenance, kept even
    when stripped — e.g. the fuzzy candidate for human review)."""

    citation: dict
    verified: bool
    error: str | None = None
    match: dict | None = None      # asdict(QuoteMatch) for policy citations
    kb_entry: dict | None = None   # hydrated {requirement_id, requirement_fr, domain}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_chat_draft(
    content: str, displayed_policy_ids: list[str]
) -> tuple[ChatDraft | None, list[str]]:
    """Parse + strictly validate model output, including the contextual
    retrieval_notes contract (needs the displayed passages, so it cannot live
    in the Pydantic model). Errors become repair feedback."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        return None, [f"JSON invalide : {exc}. Rends un objet JSON valide et complet."]
    try:
        draft = ChatDraft.model_validate(payload)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return None, [f"schéma invalide : {details}. Respecte exactement le schéma demandé."]

    errors: list[str] = []
    if draft.no_evidence:
        note_ids = {n.result_id for n in draft.retrieval_notes or []}
        displayed = set(displayed_policy_ids)
        if displayed and note_ids != displayed:
            missing = sorted(displayed - note_ids)
            unexpected = sorted(note_ids - displayed)
            parts = []
            if missing:
                parts.append(f"result_id manquants : {missing}")
            if unexpected:
                parts.append(f"result_id inconnus : {unexpected}")
            errors.append(
                "retrieval_notes incomplètes : avec no_evidence=true, fournis une "
                "note par extrait de politique affiché, référencé par son "
                f"result_id ({' ; '.join(parts)})."
            )
    elif draft.retrieval_notes:
        errors.append(
            "retrieval_notes interdites : elles ne sont attendues qu'avec "
            "no_evidence=true ; mets retrieval_notes à null."
        )
    if errors:
        return None, errors
    return draft, []


def verify_citations(
    draft: ChatDraft, retrieved_policy: list[dict], retrieved_kb: list[dict], kb: dict
) -> dict[str, CitationOutcome]:
    """Deterministic per-citation verification, keyed by citation id.

    Policy quotes: EXACT match after normalization against the retrieved
    policy extracts (fuzzy = stripped, provenance kept). KB refs: the clause
    must be among the requirements RETRIEVED for this question (mirrors the
    quote rule — a clause id that exists in the standard but was never shown
    to the model is a hallucination, not evidence); display text is then
    hydrated from the authoritative KB, never taken from the model.
    """
    retrieved_clause_ids = {i["requirement_id"] for i in retrieved_kb}
    outcomes: dict[str, CitationOutcome] = {}
    for citation in draft.citations:
        raw = citation.model_dump(mode="json")
        if citation.type == "policy":
            quote = (citation.policy_quote or "").strip()
            nq = normalize(quote)
            if len(nq.text) < MIN_QUOTE_LEN:
                outcomes[citation.id] = CitationOutcome(
                    citation=raw,
                    verified=False,
                    error=(
                        f"policy_quote trop courte ({len(nq.text)} caractères utiles) : "
                        f"citez un passage d'au moins {MIN_QUOTE_LEN} caractères."
                    ),
                )
                continue
            match = find_quote_in_retrieved(nq, retrieved_policy)
            if match is None:
                outcomes[citation.id] = CitationOutcome(
                    citation=raw,
                    verified=False,
                    error=(
                        "citation introuvable : la policy_quote doit exister mot pour "
                        "mot dans les extraits fournis."
                    ),
                )
            elif match.method != "exact":
                # candidate, not proof (lire/lier, Date/Datte) — strip, keep provenance
                outcomes[citation.id] = CitationOutcome(
                    citation=raw,
                    verified=False,
                    error=(
                        f"citation approximative (similarité {match.score:.1f}) : "
                        "retirée — seule une citation exacte est vérifiable."
                    ),
                    match=asdict(match),
                )
            else:
                outcomes[citation.id] = CitationOutcome(
                    citation=raw, verified=True, match=asdict(match)
                )
        else:  # kb
            clause = (citation.clause_ref or "").strip()
            entry = kb["by_id"].get(clause) if clause in retrieved_clause_ids else None
            if entry is None:
                outcomes[citation.id] = CitationOutcome(
                    citation=raw,
                    verified=False,
                    error=(
                        f"clause_ref invalide : « {clause} » ne figure pas parmi les "
                        "exigences ISO/IEC 42001 récupérées pour cette question."
                    ),
                )
            else:
                outcomes[citation.id] = CitationOutcome(
                    citation=raw,
                    verified=True,
                    kb_entry={
                        "requirement_id": entry["id"],
                        "requirement_fr": entry["requirement_fr"],
                        "domain": entry.get("domain"),
                    },
                )
    return outcomes


# Shared with M5 finding review — the derivation rules must be identical, so
# the implementation lives in services/provenance.py; this alias keeps the
# historical name for in-module and API/test callers.
_source_slice = source_slice


def _citation_payload(outcome: CitationOutcome, retrieved_policy: list[dict]) -> dict:
    """Response/persistence shape for a VERIFIED citation. Snapshots location
    data so the citation stays renderable after document deletion."""
    citation = outcome.citation
    if citation["type"] == "policy":
        match = outcome.match or {}
        source = next(
            (i for i in retrieved_policy if i["result_id"] == match.get("chunk_id")), {}
        )
        source_quote, source_quote_error = _source_slice(
            source, match, citation["policy_quote"]
        )
        return {
            "id": citation["id"],
            "type": "policy",
            # model-provided string: matched normalized-exact, may differ from
            # the raw source characters (case/accents/typography) — never
            # render it as source text
            "quote": citation["policy_quote"],
            # authoritative raw source slice at the matched offsets — this is
            # what a UI renders as the citation text (None + error when the
            # provenance fails validation: fail closed, never a wrong slice)
            "source_quote": source_quote,
            "source_quote_error": source_quote_error,
            "chunk_id": match.get("chunk_id"),
            "document_id": source.get("document_id"),
            "filename": source.get("filename"),
            "page_number": source.get("page_number"),
            "match_start": match.get("match_start"),
            "match_end": match.get("match_end"),
            "match_method": match.get("method"),
            "match_score": match.get("score"),
        }
    kb_entry = outcome.kb_entry or {}
    return {
        "id": citation["id"],
        "type": "kb",
        "requirement_id": kb_entry.get("requirement_id"),
        "requirement_fr": kb_entry.get("requirement_fr"),
        "domain": kb_entry.get("domain"),
    }


def _abstention_text(question: str, retrieved_kb: list[dict]) -> str:
    """Deterministic auditor-voice abstention. Epistemically honest: it states
    only what the code actually established — no verifiable citation could be
    produced from the retrieved passages (NOT that the passages demonstrate
    nothing: that would be a semantic judgment the code cannot check) — and
    suggests a clause to EXAMINE, not a proven gap."""
    text = (
        "Aucune preuve vérifiable n'a été trouvée parmi les passages récupérés : "
        f"pour « {question} », aucune citation vérifiable n'a pu être établie à "
        "partir des politiques téléversées."
    )
    if retrieved_kb:
        top = retrieved_kb[0]
        text += (
            f" Au regard d'ISO/IEC 42001, la clause {top['requirement_id']} — "
            f"{top['text']} — est à examiner comme écart potentiel."
        )
    return text


def ask(
    db: Session,
    org_id: str,
    question: str,
    conversation_id: str | None = None,
    *,
    k_policy: int = 8,
    k_kb: int = 4,
    finding_id: str | None = None,
    kb_only: bool = False,
) -> ChatMessage:
    """One grounded Q&A exchange. Returns the persisted ChatMessage.

    kb_only=True («Norme seule») skips the policy retrieval arm entirely:
    with no retrieved policy passages there is nothing a policy citation could
    verify against, so the surviving answer is structurally KB-only. The
    requested mode itself is not persisted — evidence_scope records what
    survived verification (and stays null on abstention).

    Raises OrganizationNotFoundError / ConversationNotFoundError for the router
    to map to 404; Qdrant exceptions propagate (router maps to 503) — nothing
    is persisted in either case.
    """
    # ---- read phase (one transaction, released before the provider call) ----
    if db.get(Organization, org_id) is None:
        raise OrganizationNotFoundError(org_id)
    if conversation_id is not None:
        conv = db.get(Conversation, conversation_id)
        if conv is None or conv.organization_id != org_id:
            raise ConversationNotFoundError(conversation_id)

    finding_snapshot: dict | None = None
    retrieval_query = question
    if finding_id is not None:
        finding = db.get(Finding, finding_id)
        if finding is None or finding.assessment.organization_id != org_id:
            raise FindingNotFoundError(finding_id)
        finding_snapshot = _finding_snapshot(finding)
        # Server-owned retrieval query: a terse follow-up («Pourquoi ?»)
        # retrieves nothing on its own — anchor retrieval on the finding's
        # requirement text and rationale. The verbatim user question is still
        # what the model is asked to answer.
        retrieval_query = " ".join(
            part
            for part in (
                finding.requirement_fr or finding.requirement_id,
                finding.rationale,
                question,
            )
            if part
        )

    kb = load_kb()
    retrieved_policy = (
        []
        if kb_only
        else [asdict(i) for i in hybrid_search(db, org_id, retrieval_query, k=k_policy, scope="policy")]
    )
    retrieved_kb = [asdict(i) for i in hybrid_search(db, org_id, retrieval_query, k=k_kb, scope="kb")]
    db.rollback()  # end the read transaction: no connection held across the LLM call

    displayed_policy_ids = [i["result_id"] for i in retrieved_policy]

    # ---- draft loop: ≤2 attempts, repair on parse/schema failure only ----
    base_messages = build_chat_messages(
        question, retrieved_policy, retrieved_kb, finding_context=finding_snapshot
    )
    schema = ChatDraft.model_json_schema()
    messages = base_messages

    draft: ChatDraft | None = None
    raw_draft: str | None = None
    infra_reason: str | None = None
    final_model: str | None = None
    final_provider: str | None = None
    attempts_meta: list[dict] = []
    calls: list[tuple[int, llm_service.LLMCall]] = []

    for attempt_number in range(1, MAX_DRAFT_ATTEMPTS + 1):
        outcome = llm_service.complete_json(
            messages, json_schema=schema, schema_name="chat_draft"
        )
        calls.extend((attempt_number, c) for c in outcome.calls)
        if outcome.content is None:
            infra_reason = llm_service.classify_failure(outcome.calls)
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
        draft, parse_errors = _parse_chat_draft(raw_draft, displayed_policy_ids)
        attempts_meta.append(
            {
                "attempt_number": attempt_number,
                "parsed_ok": draft is not None,
                "validation_errors": parse_errors,
            }
        )
        if draft is not None:
            break
        messages = build_chat_repair_messages(base_messages, raw_draft, parse_errors)

    # ---- decide outcome ----
    status = STATUS_ABSTAINED
    abstain_reason: str | None = None
    evidence_scope: str | None = None
    answer: str
    claims_payload: list[dict] = []
    citations_payload: list[dict] = []
    stripped_payload: list[dict] = []
    notes_payload: list[dict] | None = None

    if infra_reason is not None:
        # infrastructure abstention: must NOT claim evidence absence
        abstain_reason = infra_reason
        answer = INFRA_ABSTENTION
    elif draft is None:
        abstain_reason = AbstainReason.VERIFICATION_FAILED.value
        answer = _abstention_text(question, retrieved_kb)
    elif draft.no_evidence:
        abstain_reason = AbstainReason.MODEL_ABSTAINED.value
        answer = _abstention_text(question, retrieved_kb)
        notes_payload = [n.model_dump(mode="json") for n in draft.retrieval_notes or []]
        if draft.claims or draft.citations:
            # incoherent (no_evidence with claimed support): abstain
            # deterministically, record the incoherence — no retry
            attempts_meta[-1]["validation_errors"] = attempts_meta[-1]["validation_errors"] + [
                "incohérence : no_evidence=true avec des claims/citations non vides ; "
                "abstention retenue, support ignoré."
            ]
    else:
        outcomes = verify_citations(draft, retrieved_policy, retrieved_kb, kb)
        stripped_payload = [
            {"citation": o.citation, "error": o.error, "match": o.match}
            for o in outcomes.values()
            if not o.verified
        ]
        citations_payload = [
            _citation_payload(o, retrieved_policy) for o in outcomes.values() if o.verified
        ]
        surviving: list[dict] = []
        for claim in draft.claims:
            failed = [cid for cid in claim.citation_ids if not outcomes[cid].verified]
            entry = {
                "text": claim.text,
                "kind": claim.kind,
                "citation_ids": claim.citation_ids,
                # citation-LOCATION verified, not semantic support (module doc)
                "citations_verified": not failed,
                "failed_citation_ids": failed,
            }
            claims_payload.append(entry)
            if not failed:  # ALL citations must verify — partial support never survives
                # copy: the persisted claims payload and the answer-assembly
                # list must never alias the same dict (a future edit to one
                # would silently rewrite the other)
                surviving.append(dict(entry))

        if not surviving:
            abstain_reason = AbstainReason.VERIFICATION_FAILED.value
            answer = _abstention_text(question, retrieved_kb)
        else:
            status = STATUS_ANSWERED
            # scope from the VERIFIED CITATIONS the surviving claims reference,
            # not from claim kinds: a standard claim may also cite a verified
            # policy quote, and the kb_only caveat must never be false
            referenced = {cid for c in surviving for cid in c["citation_ids"]}
            cited_types = {outcomes[cid].citation["type"] for cid in referenced}
            if cited_types == {"kb"}:
                evidence_scope = "kb_only"
            elif cited_types == {"policy"}:
                evidence_scope = "policy"
            else:
                evidence_scope = "mixed"
            answer = "\n\n".join(c["text"] for c in surviving)
            if evidence_scope == "kb_only":
                answer += "\n\n" + KB_ONLY_CAVEAT

    # ---- write phase (short transaction, one commit) ----
    if conversation_id is not None:
        conv = db.get(Conversation, conversation_id)
        if conv is None:  # deleted between phases: surface as 404, persist nothing
            raise ConversationNotFoundError(conversation_id)
        conv.updated_at = _now()
    else:
        conv = Conversation(organization_id=org_id, title=question[:200])
        db.add(conv)
        db.flush()

    if finding_id is not None and db.get(Finding, finding_id) is None:
        # deleted between phases: keep the immutable snapshot, drop the pointer
        finding_id = None

    message = ChatMessage(
        conversation_id=conv.id,
        finding_id=finding_id,
        finding_context_snapshot=finding_snapshot,
        question=question,
        status=status,
        abstain_reason=abstain_reason,
        answer=answer,
        evidence_scope=evidence_scope,
        claims=claims_payload,
        citations=citations_payload,
        stripped_citations=stripped_payload,
        retrieval_notes=notes_payload,
        retrieved_policy=retrieved_policy,
        retrieved_kb=retrieved_kb,
        raw_draft=raw_draft,
        attempts=attempts_meta,
        draft_attempts=len(attempts_meta),
        prompt_version=CHAT_PROMPT_VERSION,
        corpus_version=kb["corpus_version"],
        final_model=final_model,
        final_provider=final_provider,
    )
    db.add(message)
    db.flush()

    call_number = 0
    for draft_attempt_number, call in calls:
        call_number += 1  # continues across the repair retry (pipeline convention)
        db.add(
            ChatLlmCall(
                chat_message_id=message.id,
                call_number=call_number,
                draft_attempt_number=draft_attempt_number,
                prompt_version=CHAT_PROMPT_VERSION,
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
                started_at=llm_service.parse_call_ts(call.started_at) or _now(),
                finished_at=llm_service.parse_call_ts(call.finished_at),
            )
        )
    db.commit()
    return message
