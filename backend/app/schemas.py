from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class OrganizationCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    filename: str
    content_type: str
    status: str
    error: str | None
    page_count: int
    checksum: str | None
    parser_version: str
    created_at: datetime


class DocumentPageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_number: int
    text: str


class SearchRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    k: int = Field(default=8, ge=1, le=50)
    scope: Literal["policy", "kb", "both"] = "policy"


class SearchResult(BaseModel):
    result_id: str
    source_type: Literal["policy", "iso_requirement"]
    text: str
    rrf_score: float
    vector_rank: int | None
    bm25_rank: int | None
    document_id: str | None = None
    filename: str | None = None
    page_number: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    requirement_id: str | None = None
    domain: str | None = None


class ChatAsk(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    conversation_id: str | None = None
    k_policy: int = Field(default=8, ge=1, le=20)
    k_kb: int = Field(default=4, ge=1, le=10)


class ChatClaimOut(BaseModel):
    text: str
    kind: Literal["organization", "standard"]
    citation_ids: list[str]
    citations_verified: bool = Field(
        description=(
            "Citation-LOCATION verified: every referenced quote exists verbatim in a "
            "retrieved passage and every clause was among the retrieved KB requirements. "
            "NOT a semantic-support judgment — claim quality is human-reviewed (M5) and "
            "measured (M6)."
        )
    )
    failed_citation_ids: list[str] = []


class ChatCitationOut(BaseModel):
    """Verified citation (tagged by type). Policy fields snapshot the source
    location; KB fields carry the server-hydrated paraphrase."""

    id: str
    type: Literal["policy", "kb"]
    # policy
    quote: str | None = None
    chunk_id: str | None = None
    document_id: str | None = None
    filename: str | None = None
    page_number: int | None = None
    match_start: int | None = None
    match_end: int | None = None
    match_method: str | None = None
    match_score: float | None = None
    # kb
    requirement_id: str | None = None
    requirement_fr: str | None = None
    domain: str | None = None


class StrippedCitationOut(BaseModel):
    citation: dict
    error: str | None
    match: dict | None = None  # fuzzy candidate provenance, when any


class RetrievalNoteOut(BaseModel):
    result_id: str
    reason: str


class SuggestedClauseOut(BaseModel):
    requirement_id: str
    requirement_fr: str
    domain: str | None = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(BaseModel):
    id: str
    conversation_id: str
    question: str
    status: Literal["ANSWERED", "ABSTAINED"]
    abstain_reason: str | None
    answer: str
    evidence_scope: Literal["policy", "kb_only", "mixed"] | None
    claims: list[ChatClaimOut]
    answer_citations: list[ChatCitationOut] = Field(
        description=(
            "ANSWER EVIDENCE: the location-verified citations referenced by surviving "
            "claims, in claim-reference (footnote) order. This is what a UI renders "
            "next to the answer."
        )
    )
    citations: list[ChatCitationOut] = Field(
        description=(
            "AUDIT PROVENANCE: every location-verified citation, including those "
            "referenced only by dropped claims or by nothing. Never render these as "
            "evidence for the final answer — use answer_citations."
        )
    )
    stripped_citations: list[StrippedCitationOut]
    retrieval_notes: list[RetrievalNoteOut] | None = Field(
        description=(
            "MODEL-GENERATED, UNVERIFIED commentary on why each displayed passage does "
            "not answer the question (no_evidence path). Deterministically checked for "
            "COVERAGE only (one note per displayed passage) — the reasons themselves are "
            "not verified and must be labelled as model commentary in any UI."
        )
    )
    searched: list[SearchResult]
    suggested_clause: SuggestedClauseOut | None
    final_model: str | None
    final_provider: str | None
    created_at: datetime


class IndexReport(BaseModel):
    documents: int
    chunks: int
    added: int
    removed: int
    stale_parser: list[str] = []


class KbIndexReport(BaseModel):
    requirements: int
    corpus_version: str
