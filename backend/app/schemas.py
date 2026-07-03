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
    checksum: str
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


class IndexReport(BaseModel):
    documents: int
    chunks: int
    added: int
    removed: int
    stale_parser: list[str] = []


class KbIndexReport(BaseModel):
    requirements: int
    corpus_version: str
