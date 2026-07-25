"""Shared hybrid retrieval layer (M2): indexing + BM25/vector/RRF search.

Two retrieval unit types live in one versioned Qdrant collection:
  - policy chunks   (org-scoped, hydrated from the authoritative PG `chunks` table)
  - ISO KB entries  (global, hydrated from the versioned corpus/kb JSON)
result_id namespace: chunk_id for policy, "kb:{corpus_version}:{requirement_id}" for KB.

Consistency contract: PG/KB-JSON are authoritative, Qdrant is derived.
index_* are reconciliation operations (desired state -> upsert wait=True ->
commit PG -> delete stale). Search hydrates from the authoritative store and
discards unknown ids, so orphan vectors can never surface.
"""

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from qdrant_client import models as qm
from sqlalchemy import Row, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Chunk, Document, DocumentStatus, DocumentVersion
from app.services import qdrant
from app.services.bm25 import Bm25Index
from app.services.chunking import chunk_page, make_chunk_id_v3
from app.services.parsing import PARSER_VERSION
from app.services.embeddings import embed_texts

RRF_K = 60
ARM_TOP = 20  # minimum candidates per arm; grows with k so k=50 can be served


@dataclass
class RetrievedItem:
    result_id: str
    source_type: str  # "policy" | "iso_requirement"
    text: str
    rrf_score: float
    vector_rank: int | None
    bm25_rank: int | None
    # policy provenance
    document_id: str | None = None
    filename: str | None = None
    page_number: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    # kb provenance
    requirement_id: str | None = None
    domain: str | None = None


def load_kb() -> dict:
    path = Path(settings.corpus_path) / "kb" / "iso42001_kb.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "corpus_version": data["meta"]["corpus_version"],
        "by_id": {e["id"]: e for e in data["requirements"]},
    }


def kb_result_id(corpus_version: str, requirement_id: str) -> str:
    return f"kb:{corpus_version}:{requirement_id}"


# ---------------------------------------------------------------- indexing


def index_organization(db: Session, org_id: str) -> dict:
    """Reconcile Qdrant + PG chunks with the parsed pages of an organization."""
    report, stale_point_ids = sync_index(db, org_id)
    db.commit()
    drop_stale_points(stale_point_ids)
    return report


def drop_stale_points(stale_point_ids: list) -> None:
    """Post-commit cleanup of stale Qdrant points. A failure here is
    reconciliation debt, not a correctness problem: orphan vectors can never
    surface (search hydrates from PG/KB and discards unknown ids) and the next
    /index reconciles them away. Because the authoritative PG state is already
    committed by every caller, a Qdrant failure here must never propagate (it
    would misreport a succeeded /index as a 503) — swallow and log."""
    try:
        qdrant.delete_points_by_ids(stale_point_ids)
    except Exception:  # pragma: no cover - best-effort cleanup
        import logging

        logging.getLogger(__name__).warning(
            "stale-point cleanup failed after commit; next /index reconciles",
            exc_info=True,
        )


def materialize_version_chunks(db: Session, version: DocumentVersion) -> list[Chunk]:
    """One-time PG chunk creation for a version (write-once: a version's text
    is immutable, so existing rows are ALWAYS reused verbatim — pre-M7b
    document_id_v2 ids survive and findings.matched_chunk_id stays valid).
    Stages new rows in the caller's transaction; returns the version's rows."""
    existing = db.scalars(
        select(Chunk).where(Chunk.document_version_id == version.id)
    ).all()
    if existing:
        return existing
    rows: list[Chunk] = []
    for page in version.pages:
        for span in chunk_page(page.text):
            rows.append(
                Chunk(
                    id=make_chunk_id_v3(
                        version.id, version.parser_version, page.page_number,
                        span.char_start, span.char_end,
                    ),
                    document_id=version.document_id,
                    document_version_id=version.id,
                    page_number=page.page_number,
                    char_start=span.char_start,
                    char_end=span.char_end,
                    text=span.text,
                )
            )
    db.add_all(rows)
    return rows


def sync_index(db: Session, org_id: str) -> tuple[dict, list]:
    """Reconciliation WITHOUT committing: materialize + embed + upsert the
    CURRENT version of every parsed document (wait=True) in the caller's open
    transaction; returns (report, stale_point_ids) for the caller to pass to
    drop_stale_points() AFTER its commit. This lets assessment creation freeze
    its document manifest and the index result in one atomic transaction. If
    the caller's commit fails, the upserted Qdrant points are harmless orphans
    (hydration rejects ids unknown to PG).

    M7b invariants: PG chunk rows are NEVER deleted here — historical versions
    keep their rows for finding provenance. The Qdrant keep-set is the chunks
    of current versions plus recoverable activation candidates
    (PENDING_INDEX/INDEX_FAILED — a mid-activation candidate indexed lock-free
    must survive a concurrent /index); everything else is stale. Pending
    versions are never activated here."""
    qdrant.ensure_collection()
    docs = db.scalars(
        select(Document).where(
            Document.organization_id == org_id,
            Document.status == DocumentStatus.PARSED.value,
            Document.current_version_id.is_not(None),
        )
    ).all()

    desired: list[Chunk] = []
    versions: list[DocumentVersion] = []
    previous_ids: set[str] = set()
    for doc in docs:
        version = db.get(DocumentVersion, doc.current_version_id)
        versions.append(version)
        existing = set(
            db.scalars(select(Chunk.id).where(Chunk.document_version_id == version.id)).all()
        )
        previous_ids |= existing
        desired.extend(materialize_version_chunks(db, version))
    desired_ids = {row.id for row in desired}

    # Recoverable activation candidates: their lock-free-indexed points must
    # not be reaped by a concurrent reconciliation (they are unreachable by
    # search anyway — the snapshot filter is current-ids-only).
    candidate_ids = set(
        db.scalars(
            select(Chunk.id)
            .join(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
            .where(
                DocumentVersion.organization_id == org_id,
                DocumentVersion.state.in_(("PENDING_INDEX", "INDEX_FAILED")),
            )
        ).all()
    )
    keep_ids = desired_ids | candidate_ids

    # Reconciliation must also see points that exist ONLY in Qdrant (orphans
    # from crashes or manual writes): scroll this org's policy points. Points
    # are keyed by their ACTUAL point id — an orphan's id is arbitrary and
    # cannot be recomputed from its (possibly absent) result_id.
    org_points = _scroll_org_points(org_id)  # actual_point_id -> payload tuple

    # 1) embed + upsert desired points (wait=True) BEFORE touching PG.
    # Re-embedding is skipped for points that already exist in CANONICAL,
    # FULLY-PAYLOADED form: chunk ids are content-addressed (version + parser +
    # chunker + offsets) and the embedding model is pinned to the collection
    # name, so an existing canonical point's vector is already correct. This
    # keeps the org-lock window of assessment creation to the genuinely new
    # chunks (the common case is zero). Points with an incomplete or
    # mismatched payload (e.g. pre-M7b rows missing document_version_id) are
    # NOT skipped — /index stays the repair path that re-upserts them whole.
    desired_by_id = {row.id: row for row in desired}
    present_canonical = {
        rid
        for raw_id, (canonical_key, rid, doc_id, version_id) in org_points.items()
        if rid in desired_by_id
        and canonical_key == qdrant.point_id(rid)
        and doc_id == desired_by_id[rid].document_id
        and version_id == desired_by_id[rid].document_version_id
    }
    to_upsert = [row for row in desired if row.id not in present_canonical]
    if to_upsert:
        vectors = embed_texts([row.text for row in to_upsert])
        qdrant.upsert_points(
            [_chunk_point(row, org_id, vec) for row, vec in zip(to_upsert, vectors)]
        )

    # 2) compute stale points BY ACTUAL POINT ID (raw int|UUID — never stringified
    # for deletion: deleting "42" does not delete point 42). Stale =
    #   - result_id missing or outside the keep-set, or
    #   - a NON-CANONICAL point claiming a kept result_id (its actual id
    #     differs from UUID5(result_id)) — otherwise it duplicates candidates.
    stale_point_ids: list = [
        raw_id
        for raw_id, (canonical_key, rid, _doc_id, _version_id) in org_points.items()
        if rid is None or rid not in keep_ids or canonical_key != qdrant.point_id(rid)
    ]

    report = {
        "documents": len(docs),
        "chunks": len(desired),
        "added": len(desired_ids - previous_ids),
        "removed": len(stale_point_ids),
        # Versions parsed by an older extractor: indexed as-is, but flagged so
        # the caller knows the parse (and thus the chunks) may be stale.
        "stale_parser": sorted(
            v.filename for v in versions if v.parser_version != PARSER_VERSION
        ),
    }
    return report, stale_point_ids


def _chunk_point(row: "Chunk | Row", org_id: str, vector: list[float]) -> qm.PointStruct:
    """`row` is any carrier of the chunk columns: an ORM Chunk (sync_index) or
    a detached column Row (patcher._index_candidate_points, which must not hold
    ORM identity across its rollback)."""
    return qm.PointStruct(
        id=qdrant.point_id(row.id),
        vector=vector,
        payload={
            "source_type": "policy",
            "result_id": row.id,
            "org_id": org_id,
            "document_id": row.document_id,
            "document_version_id": row.document_version_id,
            "page_number": row.page_number,
            "char_start": row.char_start,
            "char_end": row.char_end,
        },
    )


def _scroll_points(conditions: list) -> dict:
    """raw point id -> (str(id) for canonical comparison, payload result_id | None,
    payload document_id | None, payload document_version_id | None)."""
    client = qdrant.get_client()
    points_map: dict = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=qm.Filter(must=conditions),
            limit=256,
            offset=offset,
            with_payload=["result_id", "document_id", "document_version_id"],
            with_vectors=False,
        )
        for p in points:
            payload = p.payload or {}
            points_map[p.id] = (
                str(p.id),
                payload.get("result_id"),
                payload.get("document_id"),
                payload.get("document_version_id"),
            )
        if offset is None:
            break
    return points_map


def _scroll_org_points(org_id: str) -> dict:
    return _scroll_points(
        [
            qm.FieldCondition(key="source_type", match=qm.MatchValue(value="policy")),
            qm.FieldCondition(key="org_id", match=qm.MatchValue(value=org_id)),
        ]
    )


def index_kb() -> dict:
    """Index the versioned ISO KB; purge points of other corpus versions."""
    qdrant.ensure_collection()
    kb = load_kb()
    entries = list(kb["by_id"].values())
    vectors = embed_texts([e["requirement_fr"] for e in entries])
    points = [
        qm.PointStruct(
            id=qdrant.point_id(kb_result_id(kb["corpus_version"], e["id"])),
            vector=vec,
            payload={
                "source_type": "iso_requirement",
                "result_id": kb_result_id(kb["corpus_version"], e["id"]),
                "requirement_id": e["id"],
                "corpus_version": kb["corpus_version"],
            },
        )
        for e, vec in zip(entries, vectors)
    ]
    qdrant.upsert_points(points)
    # Full reconciliation over ALL iso_requirement points (any corpus_version):
    # anything that is not a canonical point of a current KB entry is stale —
    # old versions, fabricated requirement ids, and non-canonical duplicates.
    desired_rids = {kb_result_id(kb["corpus_version"], e["id"]) for e in entries}
    kb_points = _scroll_points(
        [qm.FieldCondition(key="source_type", match=qm.MatchValue(value="iso_requirement"))]
    )
    stale = [
        raw_id
        for raw_id, (canonical_key, rid, _doc_id, _version_id) in kb_points.items()
        if rid is None or rid not in desired_rids or canonical_key != qdrant.point_id(rid)
    ]
    qdrant.delete_points_by_ids(stale)
    return {"requirements": len(entries), "corpus_version": kb["corpus_version"]}


# ---------------------------------------------------------------- search


class CorpusChangedError(RuntimeError):
    """The org's current-version snapshot changed during BOTH attempts of one
    hybrid search (a version activation raced the query twice). Retryable —
    callers map it per flow: search/chat -> HTTP 409 (nothing persisted),
    triage/planner -> ABSTAINED(retrieval_error) audit row, assessments ->
    loud run failure (the run guard makes this unreachable there)."""

    def __init__(self) -> None:
        super().__init__(
            "le corpus documentaire vient d'être modifié pendant la recherche ; "
            "réessayez."
        )


def _current_snapshot(db: Session, org_id: str) -> dict[str, str]:
    """{document_id: current_version_id} for the org's parsed documents — the
    ONE authoritative version set of a hybrid-search attempt. Both arms and
    hydration consume the same snapshot so RRF never fuses two states."""
    return dict(
        db.execute(
            select(Document.id, Document.current_version_id).where(
                Document.organization_id == org_id,
                Document.status == DocumentStatus.PARSED.value,
                Document.current_version_id.is_not(None),
            )
        ).all()
    )


def _vector_arm(
    query_vec: list[float],
    scope: str,
    org_id: str,
    corpus_version: str,
    arm_top: int,
    current_version_ids: list[str],
) -> list[str]:
    """result_ids ranked by cosine similarity, best first. The policy filter
    is snapshot-scoped (document_version_id IN current versions) so stale or
    pending points can never consume candidate slots; an empty snapshot asks
    Qdrant nothing (never an empty MatchAny)."""
    conditions_by_scope = {
        "policy": qm.Filter(
            must=[
                qm.FieldCondition(key="source_type", match=qm.MatchValue(value="policy")),
                qm.FieldCondition(key="org_id", match=qm.MatchValue(value=org_id)),
                qm.FieldCondition(
                    key="document_version_id", match=qm.MatchAny(any=current_version_ids)
                ),
            ]
        ),
        "kb": qm.Filter(
            must=[
                qm.FieldCondition(key="source_type", match=qm.MatchValue(value="iso_requirement")),
                qm.FieldCondition(key="corpus_version", match=qm.MatchValue(value=corpus_version)),
            ]
        ),
    }
    scopes = ["policy", "kb"] if scope == "both" else [scope]
    scored: list[tuple[float, str]] = []
    for s in scopes:
        if s == "policy" and not current_version_ids:
            continue
        hits = qdrant.get_client().query_points(
            collection_name=settings.qdrant_collection,
            query=query_vec,
            query_filter=conditions_by_scope[s],
            limit=arm_top,
            with_payload=True,
        ).points
        # tolerate malformed points (no payload/result_id): skip, never crash
        scored.extend(
            (h.score, h.payload["result_id"])
            for h in hits
            if h.payload and "result_id" in h.payload
        )
    scored.sort(key=lambda p: (-p[0], p[1]))
    return [rid for _, rid in scored[:arm_top]]


def _bm25_entries(
    db: Session, scope: str, kb: dict | None, current_version_ids: list[str]
) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    if scope in ("policy", "both") and current_version_ids:
        # Same snapshot as the vector arm — never a fresh live join, so both
        # arms rank the exact same version set.
        rows = db.execute(
            select(Chunk.id, Chunk.text).where(
                Chunk.document_version_id.in_(current_version_ids)
            )
        ).all()
        entries.extend((cid, text) for cid, text in rows)
    if scope in ("kb", "both") and kb is not None:
        for e in kb["by_id"].values():
            text = e["requirement_fr"] + " " + " ".join(e.get("keywords_fr", []))
            entries.append((kb_result_id(kb["corpus_version"], e["id"]), text))
    return entries


# BM25 index cache, keyed on CONTENT identity — never on time or org alone:
# the policy arm is identified by the frozenset of current version ids (a
# version's chunk set is write-once, so the same id set always yields the
# same entries) and the KB arm by a fingerprint of the loaded KB texts
# (load_kb() re-reads the file per request, so version alone would not detect
# an edited file in tests/dev). A snapshot retry naturally gets its own key.
_BM25_CACHE: "OrderedDict[tuple, Bm25Index]" = OrderedDict()
_BM25_CACHE_MAX = 8
_BM25_CACHE_LOCK = threading.Lock()


def _kb_fingerprint(kb: dict) -> tuple:
    return (
        kb["corpus_version"],
        hash(tuple(sorted((e["id"], e["requirement_fr"], " ".join(e.get("keywords_fr", []))) for e in kb["by_id"].values()))),
    )


def _bm25_for(
    db: Session, scope: str, kb: dict | None, current_version_ids: list[str]
) -> Bm25Index:
    key = (
        frozenset(current_version_ids) if scope in ("policy", "both") else None,
        _kb_fingerprint(kb) if kb is not None and scope in ("kb", "both") else None,
    )
    with _BM25_CACHE_LOCK:
        cached = _BM25_CACHE.get(key)
        if cached is not None:
            _BM25_CACHE.move_to_end(key)
            return cached
    index = Bm25Index(_bm25_entries(db, scope, kb, current_version_ids))
    with _BM25_CACHE_LOCK:
        _BM25_CACHE[key] = index
        _BM25_CACHE.move_to_end(key)
        while len(_BM25_CACHE) > _BM25_CACHE_MAX:
            _BM25_CACHE.popitem(last=False)
    return index


def hybrid_search(db: Session, org_id: str, query: str, k: int, scope: str = "policy") -> list[RetrievedItem]:
    """Snapshot-consistent hybrid retrieval. One {document: current version}
    snapshot per attempt feeds the vector filter, the BM25 corpus AND
    hydration; if the mapping changed by the end of the attempt (a version
    activation raced us) the WHOLE attempt is retried once with a fresh
    snapshot, and a second change raises CorpusChangedError — results mixing
    two corpus states are never returned. Assessments never hit the retry
    (the run guard freezes the corpus while they run)."""
    # KB is only loaded when the scope needs it: policy search must not
    # depend on the corpus files being present.
    kb = load_kb() if scope in ("kb", "both") else None
    query_vec = embed_texts([query])[0]
    needs_policy = scope in ("policy", "both")

    for _ in range(2):
        snapshot = _current_snapshot(db, org_id) if needs_policy else {}
        results = _hybrid_attempt(db, org_id, query, k, scope, kb, query_vec, snapshot)
        if not needs_policy or _current_snapshot(db, org_id) == snapshot:
            return results
    raise CorpusChangedError()


def _hybrid_attempt(
    db: Session,
    org_id: str,
    query: str,
    k: int,
    scope: str,
    kb: dict | None,
    query_vec: list[float],
    snapshot: dict[str, str],
) -> list[RetrievedItem]:
    current_ids = sorted(snapshot.values())
    arm_top = max(ARM_TOP, k)  # each arm must supply at least k candidates
    vector_ids = _vector_arm(
        query_vec, scope, org_id, kb["corpus_version"] if kb else "", arm_top, current_ids
    )
    bm25_hits = _bm25_for(db, scope, kb, current_ids).search(query, arm_top)

    vector_rank = {rid: i + 1 for i, rid in enumerate(vector_ids)}
    bm25_rank = {rid: i + 1 for i, (rid, _) in enumerate(bm25_hits)}

    fused: dict[str, float] = {}
    for rid, rank in list(vector_rank.items()) + list(bm25_rank.items()):
        fused[rid] = fused.get(rid, 0.0) + 1.0 / (RRF_K + rank)
    ranked = sorted(fused.items(), key=lambda p: (-p[1], p[0]))  # deterministic tie-break

    # hydrate from authoritative stores; discard unknown ids
    results: list[RetrievedItem] = []
    for rid, score in ranked:
        if len(results) >= k:
            break
        item = _hydrate(
            db, org_id, rid, score, vector_rank.get(rid), bm25_rank.get(rid), kb, snapshot
        )
        if item is not None:
            results.append(item)
    return results


def _hydrate(
    db: Session,
    org_id: str,
    rid: str,
    score: float,
    vrank: int | None,
    brank: int | None,
    kb: dict | None,
    snapshot: dict[str, str],
) -> RetrievedItem | None:
    if rid.startswith("kb:"):
        if kb is None:
            return None
        _, version, req_id = rid.split(":", 2)
        entry = kb["by_id"].get(req_id)
        if entry is None or version != kb["corpus_version"]:
            return None
        return RetrievedItem(
            result_id=rid,
            source_type="iso_requirement",
            text=entry["requirement_fr"],
            rrf_score=score,
            vector_rank=vrank,
            bm25_rank=brank,
            requirement_id=entry["id"],
            domain=entry["domain"],
        )
    chunk = db.get(Chunk, rid)
    if chunk is None:
        return None
    if chunk.document.organization_id != org_id:
        return None  # authoritative isolation check — never trust point payloads
    # Final fail-closed membership check against THE attempt's snapshot: a
    # chunk of a superseded/pending version can never surface, whatever the
    # arms produced.
    if snapshot.get(chunk.document_id) != chunk.document_version_id:
        return None
    return RetrievedItem(
        result_id=rid,
        source_type="policy",
        text=chunk.text,
        rrf_score=score,
        vector_rank=vrank,
        bm25_rank=brank,
        document_id=chunk.document_id,
        filename=chunk.document.filename,
        page_number=chunk.page_number,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
    )
