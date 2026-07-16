"""M4 chat endpoints: grounded Q&A + conversation replay.

Total provider failure is HTTP 200 with an ABSTAINED message (infrastructure
reason), NOT 503: the exchange must enter the audit log either way, and
state.is_infrastructure_failure lets clients render it distinctly. 503 is
reserved for backing-store failure before any answerable work happened.
GET endpoints replay strictly from persisted rows.
"""

from fastapi import APIRouter, Depends, HTTPException
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_org_member
from app.chat import service
from app.db import get_db
from app.models import ChatMessage, Conversation, Organization
from app.pipeline.state import is_infrastructure_failure
from app.schemas import ChatAsk, ChatMessageOut, ConversationOut
from app.services.retrieval import CorpusChangedError

router = APIRouter(
    prefix="/api", tags=["chat"], dependencies=[Depends(require_org_member)]
)

QDRANT_ERRORS = (ResponseHandlingException, UnexpectedResponse, ConnectionError)


def _normalize_claims(claims: list) -> list:
    """Legacy belt: rows persisted before revision 0010 carry `verified`
    instead of `citations_verified`. The 0010 data migration backfills
    Postgres; this normalization covers stores the migration never ran on."""
    out = []
    for claim in claims:
        if "citations_verified" not in claim:
            claim = {
                **{k: v for k, v in claim.items() if k != "verified"},
                "citations_verified": claim.get("verified", False),
            }
        out.append(claim)
    return out


def _backfill_source_quotes(citations: list, retrieved_policy: list) -> list:
    """Legacy belt: rows persisted before source_quote existed. Derived
    deterministically from the persisted retrieval snapshot (chunk text +
    page-relative offsets), never re-fetched."""
    out = []
    for c in citations:
        if c.get("type") == "policy" and "source_quote" not in c:
            source = next(
                (i for i in retrieved_policy if i["result_id"] == c.get("chunk_id")), {}
            )
            source_quote, error = service._source_slice(
                source,
                {"match_start": c.get("match_start"), "match_end": c.get("match_end")},
                c.get("quote"),
            )
            c = {**c, "source_quote": source_quote, "source_quote_error": error}
        out.append(c)
    return out


def message_to_out(message: ChatMessage) -> ChatMessageOut:
    """Response shape from the persisted row only — GET replay is byte-stable.

    searched/suggested_clause are derived from the persisted retrieval JSON
    (deterministic), never re-retrieved or re-templated."""
    suggested = None
    if (
        message.status == service.STATUS_ABSTAINED
        and not is_infrastructure_failure(message.abstain_reason)
        and message.retrieved_kb
    ):
        top = message.retrieved_kb[0]
        suggested = {
            "requirement_id": top["requirement_id"],
            "requirement_fr": top["text"],
            "domain": top.get("domain"),
        }
    claims = _normalize_claims(message.claims)
    citations = _backfill_source_quotes(message.citations, message.retrieved_policy)
    # Answer segmentation (M5 footnote rendering): the persisted `answer` is
    # the surviving claims joined with blank lines, plus the KB-only caveat —
    # a client cannot split that string safely, so the segments and the caveat
    # are served explicitly, derived from persisted data only.
    answer_segments = []
    answer_caveat = None
    if message.status == service.STATUS_ANSWERED:
        answer_segments = [
            {"text": c["text"], "citation_ids": c.get("citation_ids", [])}
            for c in claims
            if c.get("citations_verified")
        ]
        if message.evidence_scope == "kb_only":
            answer_caveat = service.KB_ONLY_CAVEAT
    # answer citations in CLAIM-REFERENCE order (footnote order for M5),
    # not draft declaration order
    by_id = {c["id"]: c for c in citations}
    answer_citations = [
        by_id[cid] for cid in service.answer_citation_ids(claims) if cid in by_id
    ]
    return ChatMessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        finding_id=message.finding_id,
        finding_context=message.finding_context_snapshot,
        question=message.question,
        status=message.status,
        abstain_reason=message.abstain_reason,
        answer=message.answer,
        evidence_scope=message.evidence_scope,
        claims=claims,
        answer_segments=answer_segments,
        answer_caveat=answer_caveat,
        answer_citations=answer_citations,
        citations=citations,
        stripped_citations=message.stripped_citations,
        retrieval_notes=message.retrieval_notes,
        searched=message.retrieved_policy + message.retrieved_kb,
        suggested_clause=suggested,
        final_model=message.final_model,
        final_provider=message.final_provider,
        created_at=message.created_at,
    )


@router.post("/organizations/{org_id}/chat/messages", response_model=ChatMessageOut)
def post_message(org_id: str, body: ChatAsk, db: Session = Depends(get_db)):
    try:
        message = service.ask(
            db,
            org_id,
            body.question,
            body.conversation_id,
            k_policy=body.k_policy,
            k_kb=body.k_kb,
            finding_id=body.finding_id,
            kb_only=body.kb_only,
        )
    except service.OrganizationNotFoundError:
        raise HTTPException(404, "Organisation introuvable.")
    except service.ConversationNotFoundError:
        raise HTTPException(404, "Conversation introuvable.")
    except service.FindingNotFoundError:
        raise HTTPException(404, "Constat introuvable pour cette organisation.")
    except CorpusChangedError as exc:
        # Retryable, nothing persisted: retrieval happens before any
        # ChatMessage row exists (same doctrine as the Qdrant 503 below).
        raise HTTPException(409, str(exc))
    except QDRANT_ERRORS as exc:
        raise HTTPException(503, f"Index vectoriel indisponible : {exc}")
    return message_to_out(message)


@router.get(
    "/organizations/{org_id}/chat/conversations", response_model=list[ConversationOut]
)
def list_conversations(org_id: str, db: Session = Depends(get_db)):
    if not db.get(Organization, org_id):
        raise HTTPException(404, "Organisation introuvable.")
    return db.scalars(
        select(Conversation)
        .where(Conversation.organization_id == org_id)
        .order_by(Conversation.updated_at.desc())
    ).all()


@router.get(
    "/organizations/{org_id}/chat/conversations/{conversation_id}/messages",
    response_model=list[ChatMessageOut],
)
def list_messages(org_id: str, conversation_id: str, db: Session = Depends(get_db)):
    if not db.get(Organization, org_id):
        raise HTTPException(404, "Organisation introuvable.")
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.organization_id != org_id:
        raise HTTPException(404, "Conversation introuvable.")
    messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at)
    ).all()
    return [message_to_out(m) for m in messages]
