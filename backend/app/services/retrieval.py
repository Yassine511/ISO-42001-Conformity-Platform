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
from dataclasses import dataclass
from pathlib import Path

from qdrant_client import models as qm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Chunk, Document, DocumentStatus
from app.services import qdrant
from app.services.bm25 import Bm25Index
from app.services.chunking import chunk_page, make_chunk_id
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
    /index reconciles them away."""
    qdrant.delete_points_by_ids(stale_point_ids)


def sync_index(db: Session, org_id: str) -> tuple[dict, list]:
    """Reconciliation WITHOUT committing: embed + upsert Qdrant (wait=True) and
    synchronize the PG chunk rows in the caller's open transaction; returns
    (report, stale_point_ids) for the caller to pass to drop_stale_points()
    AFTER its commit. This lets assessment creation freeze its document
    manifest and the index result in one atomic transaction (a commit inside
    this function would release the org row lock mid-sequence). If the caller's
    commit fails, the upserted Qdrant points are harmless orphans (hydration
    rejects ids unknown to PG)."""
    qdrant.ensure_collection()
    docs = db.scalars(
        select(Document).where(
            Document.organization_id == org_id,
            Document.status == DocumentStatus.PARSED.value,
        )
    ).all()

    desired: list[tuple[Chunk, str]] = []  # (row, text) — text kept for embedding
    for doc in docs:
        for page in doc.pages:
            for span in chunk_page(page.text):
                cid = make_chunk_id(doc.id, doc.parser_version, page.page_number, span.char_start, span.char_end)
                desired.append(
                    (
                        Chunk(
                            id=cid,
                            document_id=doc.id,
                            page_number=page.page_number,
                            char_start=span.char_start,
                            char_end=span.char_end,
                            text=span.text,
                        ),
                        span.text,
                    )
                )

    doc_ids = [d.id for d in docs]
    previous_ids = set(
        db.scalars(select(Chunk.id).where(Chunk.document_id.in_(doc_ids))).all()
    ) if doc_ids else set()
    desired_ids = {row.id for row, _ in desired}
    # Reconciliation must also see points that exist ONLY in Qdrant (orphans
    # from crashes or manual writes): scroll this org's policy points. Points
    # are keyed by their ACTUAL point id — an orphan's id is arbitrary and
    # cannot be recomputed from its (possibly absent) result_id.
    org_points = _scroll_org_points(org_id)  # actual_point_id -> result_id | None

    # 1) embed + upsert desired points (wait=True) BEFORE touching PG
    if desired:
        vectors = embed_texts([text for _, text in desired])
        points = [
            qm.PointStruct(
                id=qdrant.point_id(row.id),
                vector=vec,
                payload={
                    "source_type": "policy",
                    "result_id": row.id,
                    "org_id": org_id,
                    "document_id": row.document_id,
                    "page_number": row.page_number,
                    "char_start": row.char_start,
                    "char_end": row.char_end,
                },
            )
            for (row, _), vec in zip(desired, vectors)
        ]
        qdrant.upsert_points(points)

    # 2) stage authoritative rows in the caller's transaction (no commit here)
    for stale_id in previous_ids - desired_ids:
        db.delete(db.get(Chunk, stale_id))
    for row, _ in desired:
        if row.id not in previous_ids:
            db.add(row)

    # 3) compute stale points BY ACTUAL POINT ID (raw int|UUID — never stringified
    # for deletion: deleting "42" does not delete point 42). Stale =
    #   - result_id missing or not desired, or
    #   - a NON-CANONICAL point claiming a desired result_id (its actual id
    #     differs from UUID5(result_id)) — otherwise it duplicates candidates.
    # Plus PG leftovers, whose canonical ids we can recompute.
    stale_point_ids: list = [
        raw_id
        for raw_id, (canonical_key, rid) in org_points.items()
        if rid is None or rid not in desired_ids or canonical_key != qdrant.point_id(rid)
    ]
    seen_keys = {canonical_key for canonical_key, _ in org_points.values()}
    stale_point_ids += [
        qdrant.point_id(cid)
        for cid in previous_ids - desired_ids
        if qdrant.point_id(cid) not in seen_keys
    ]

    report = {
        "documents": len(docs),
        "chunks": len(desired),
        "added": len(desired_ids - previous_ids),
        "removed": len(stale_point_ids),
        # Docs parsed by an older extractor: indexed as-is, but flagged so the
        # caller knows the parse (and thus the chunks) may be stale.
        "stale_parser": sorted(
            d.filename for d in docs if d.parser_version != PARSER_VERSION
        ),
    }
    return report, stale_point_ids


def _scroll_points(conditions: list) -> dict:
    """raw point id -> (str(id) for canonical comparison, payload result_id | None)."""
    client = qdrant.get_client()
    points_map: dict = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=qm.Filter(must=conditions),
            limit=256,
            offset=offset,
            with_payload=["result_id"],
            with_vectors=False,
        )
        for p in points:
            points_map[p.id] = (str(p.id), (p.payload or {}).get("result_id"))
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
        for raw_id, (canonical_key, rid) in kb_points.items()
        if rid is None or rid not in desired_rids or canonical_key != qdrant.point_id(rid)
    ]
    qdrant.delete_points_by_ids(stale)
    return {"requirements": len(entries), "corpus_version": kb["corpus_version"]}


# ---------------------------------------------------------------- search


def _vector_arm(
    query_vec: list[float], scope: str, org_id: str, corpus_version: str, arm_top: int
) -> list[str]:
    """result_ids ranked by cosine similarity, best first."""
    conditions_by_scope = {
        "policy": qm.Filter(
            must=[
                qm.FieldCondition(key="source_type", match=qm.MatchValue(value="policy")),
                qm.FieldCondition(key="org_id", match=qm.MatchValue(value=org_id)),
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


def _bm25_entries(db: Session, scope: str, org_id: str, kb: dict | None) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    if scope in ("policy", "both"):
        rows = db.execute(
            select(Chunk.id, Chunk.text)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.organization_id == org_id)
        ).all()
        entries.extend((cid, text) for cid, text in rows)
    if scope in ("kb", "both") and kb is not None:
        for e in kb["by_id"].values():
            text = e["requirement_fr"] + " " + " ".join(e.get("keywords_fr", []))
            entries.append((kb_result_id(kb["corpus_version"], e["id"]), text))
    return entries


def hybrid_search(db: Session, org_id: str, query: str, k: int, scope: str = "policy") -> list[RetrievedItem]:
    # KB is only loaded when the scope needs it: policy search must not
    # depend on the corpus files being present.
    kb = load_kb() if scope in ("kb", "both") else None
    query_vec = embed_texts([query])[0]

    arm_top = max(ARM_TOP, k)  # each arm must supply at least k candidates
    vector_ids = _vector_arm(query_vec, scope, org_id, kb["corpus_version"] if kb else "", arm_top)
    bm25_hits = Bm25Index(_bm25_entries(db, scope, org_id, kb)).search(query, arm_top)

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
        item = _hydrate(db, org_id, rid, score, vector_rank.get(rid), bm25_rank.get(rid), kb)
        if item is not None:
            results.append(item)
    return results


def _hydrate(
    db: Session, org_id: str, rid: str, score: float, vrank: int | None, brank: int | None, kb: dict | None
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
