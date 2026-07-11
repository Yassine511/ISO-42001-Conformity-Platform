# -*- coding: utf-8 -*-
"""M2 retrieval sanity gates: recall over dev-split gold, 3-arm ablation.

For every dev-split gold item with a document, query = the KB requirement
text. Arms: BM25 only | Vector only | Hybrid RRF.

Metrics:
  - document recall@5: gold document among the documents of the top-5 results;
  - evidence-anchor recall@k: some top-k chunk FULLY CONTAINS an occurrence of
    the gold quote (chunk_start <= quote_start and chunk_end >= quote_end, any
    occurrence, NFC-normalized). Max overlap ratio is a diagnostic only.

Floors (hybrid arm): doc R@5 >= 0.85, anchor R@5 >= 0.70, anchor R@10 >= 0.85.
Exit code 1 if a floor is missed.

Requires: postgres + qdrant up (docker compose up -d postgres qdrant), corpus
indexed — the script indexes/reconciles by itself (first run downloads the
embedding model, ~220 MB).

Usage: backend/.venv/Scripts/python scripts/retrieval_sanity.py [--org "Lumen AI"]
"""

import argparse
import hashlib
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402

settings.corpus_path = str(ROOT / "corpus")

from app.db import SessionLocal  # noqa: E402
from app.models import Chunk, Document, DocumentPage, Organization  # noqa: E402
from app.services import retrieval  # noqa: E402
from app.services.bm25 import Bm25Index  # noqa: E402
from app.services.embeddings import embed_texts  # noqa: E402

FLOORS = {"doc_r5": 0.85, "anchor_r5": 0.70, "anchor_r10": 0.85}
KB_FLOOR_R5 = 0.60  # NL queries (gold rationales) -> right KB requirement in top-5
K_MAX = 10


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def load_gold_dev():
    gold = json.loads((ROOT / "corpus" / "gold" / "gold_labels.json").read_text(encoding="utf-8"))
    kb = json.loads((ROOT / "corpus" / "kb" / "iso42001_kb.json").read_text(encoding="utf-8"))
    req = {e["id"]: e for e in kb["requirements"]}
    items = [
        {
            "gold_id": g["id"],
            "requirement_id": g["requirement_id"],
            "query": req[g["requirement_id"]]["requirement_fr"],
            "document": g["document"],
            "quote": nfc(g["evidence_quote_fr"]),
        }
        for g in gold["items"]
        if g["split"] == "dev" and g["document"] is not None
    ]
    return items


def quote_occurrences(pages: list[DocumentPage], quote: str) -> list[tuple[int, int, int]]:
    """All (page_number, start, end) occurrences of the quote."""
    occ = []
    for page in pages:
        text = nfc(page.text)
        start = text.find(quote)
        while start != -1:
            occ.append((page.page_number, start, start + len(quote)))
            start = text.find(quote, start + 1)
    return occ


def arm_results(db, org_id: str, query: str, kb: dict) -> dict[str, list[Chunk]]:
    """Top-K_MAX policy chunks per arm."""
    # M7b: the arms are snapshot-scoped to the org's current versions.
    current_ids = sorted(retrieval._current_snapshot(db, org_id).values())
    bm25_hits = Bm25Index(
        retrieval._bm25_entries(db, "policy", kb, current_ids)
    ).search(query, K_MAX)
    vec_ids = retrieval._vector_arm(
        embed_texts([query])[0], "policy", org_id, kb["corpus_version"], K_MAX, current_ids
    )
    hybrid = retrieval.hybrid_search(db, org_id, query, K_MAX, "policy")
    out = {
        "BM25": [rid for rid, _ in bm25_hits],
        "Vector": vec_ids[:K_MAX],
        "Hybrid": [r.result_id for r in hybrid],
    }
    return {
        arm: [c for c in (db.get(Chunk, rid) for rid in ids) if c is not None]
        for arm, ids in out.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", default="Lumen AI")
    args = parser.parse_args()

    db = SessionLocal()
    org = db.scalar(select(Organization).where(Organization.name == args.org))
    if org is None:
        print(f"Organisation {args.org!r} introuvable — créez-la et téléversez les documents corpus/.")
        return 1

    print("Réconciliation de l'index (premier run : téléchargement du modèle ~220 Mo)…")
    report = retrieval.index_organization(db, org.id)
    print(f"Index : {report}")
    kb_report = retrieval.index_kb()  # the KB gate must exercise KB VECTORS too
    print(f"KB : {kb_report}")
    kb = retrieval.load_kb()

    docs_by_name = {
        d.filename: d
        for d in db.scalars(select(Document).where(Document.organization_id == org.id)).all()
    }
    items = load_gold_dev()
    all_docs = db.scalars(select(Document).where(Document.organization_id == org.id)).all()
    corpus_files = sorted((ROOT / "corpus" / "documents").glob("*.md"))
    corpus_checksums = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in corpus_files
    }
    problems = []
    if len(all_docs) != len(corpus_files):
        problems.append(f"{len(all_docs)} documents dans l'organisation, {len(corpus_files)} attendus")
    missing_docs = set(corpus_checksums) - {d.filename for d in all_docs}
    if missing_docs:
        problems.append(f"documents gold absents : {sorted(missing_docs)}")
    for d in all_docs:
        expected = corpus_checksums.get(d.filename)
        if expected is None:
            problems.append(f"document hors corpus : {d.filename}")
        elif d.checksum != expected:
            problems.append(f"contenu modifié (checksum différent du corpus) : {d.filename}")
    if report.get("stale_parser"):
        problems.append(f"documents parsés par un extracteur obsolète : {report['stale_parser']}")
    if problems:
        print("Baseline non propre :")
        for p in problems:
            print(f"  - {p}")
        return 1

    arms = ["BM25", "Vector", "Hybrid"]
    stats = {a: {"doc_r5": 0, "anchor_r5": 0, "anchor_r10": 0, "overlap_sum": 0.0} for a in arms}
    misses: list[str] = []

    for item in items:
        gold_doc = docs_by_name[item["document"]]
        # M7b: pages hang off the CURRENT version, not the document row.
        gold_pages = db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_version_id == gold_doc.current_version_id)
            .order_by(DocumentPage.page_number)
        ).all()
        occurrences = quote_occurrences(gold_pages, item["quote"])
        if not occurrences:
            print(f"  !! citation introuvable pour {item['gold_id']} (corpus modifié ?)")
            return 1
        per_arm = arm_results(db, org.id, item["query"], kb)
        for arm in arms:
            chunks = per_arm[arm]
            if gold_doc.id in {c.document_id for c in chunks[:5]}:
                stats[arm]["doc_r5"] += 1
            contained_at = None
            best_overlap = 0.0
            for rank, c in enumerate(chunks, 1):
                if c.document_id != gold_doc.id:
                    continue
                for page_no, qs, qe in occurrences:
                    if c.page_number != page_no:
                        continue
                    inter = max(0, min(c.char_end, qe) - max(c.char_start, qs))
                    best_overlap = max(best_overlap, inter / (qe - qs))
                    if c.char_start <= qs and c.char_end >= qe and contained_at is None:
                        contained_at = rank
            if contained_at is not None and contained_at <= 5:
                stats[arm]["anchor_r5"] += 1
            if contained_at is not None and contained_at <= 10:
                stats[arm]["anchor_r10"] += 1
            elif arm == "Hybrid":
                misses.append(f"{item['gold_id']} ({item['requirement_id']}) overlap_max={best_overlap:.2f}")
            stats[arm]["overlap_sum"] += best_overlap

    n = len(items)
    print(f"\n{n} cas dev évalués — ablation :")
    header = f"{'métrique':<14}" + "".join(f"{a:>10}" for a in arms) + f"{'plancher':>10}"
    print(header)
    rows = [("doc_r5", "doc R@5"), ("anchor_r5", "anchor R@5"), ("anchor_r10", "anchor R@10")]
    failed = False
    for key, label in rows:
        line = f"{label:<14}"
        for a in arms:
            line += f"{stats[a][key] / n:>10.2f}"
        line += f"{FLOORS[key]:>10.2f}"
        if stats["Hybrid"][key] / n < FLOORS[key]:
            line += "  ✗ ÉCHEC"
            failed = True
        print(line)
    diag = f"{'overlap moyen':<14}" + "".join(f"{stats[a]['overlap_sum'] / n:>10.2f}" for a in arms)
    print(diag + "   (diagnostic)")

    if misses:
        print("\nCas hybrides sans containment @10 :")
        for m in misses:
            print(f"  - {m}")

    # KB-scope gate: natural-language queries (gold rationales) must surface
    # the right requirement — measured per arm, because a hybrid-only number
    # can hide a dead vector index behind a strong BM25.
    gold = json.loads((ROOT / "corpus" / "gold" / "gold_labels.json").read_text(encoding="utf-8"))
    kb_cases = [g for g in gold["items"] if g["split"] == "dev"]
    # KB scope ignores the policy version snapshot (current_ids unused there).
    kb_entries = retrieval._bm25_entries(db, "kb", kb, [])
    kb_arm_hits = {"BM25": 0, "Vector": 0, "Hybrid": 0}
    for g in kb_cases:
        want = retrieval.kb_result_id(kb["corpus_version"], g["requirement_id"])
        bm25_ids = [rid for rid, _ in Bm25Index(kb_entries).search(g["rationale_fr"], 5)]
        vec_ids = retrieval._vector_arm(
            embed_texts([g["rationale_fr"]])[0], "kb", org.id, kb["corpus_version"], 5, []
        )
        hybrid = retrieval.hybrid_search(db, org.id, g["rationale_fr"], 5, "kb")
        kb_arm_hits["BM25"] += want in bm25_ids
        kb_arm_hits["Vector"] += want in vec_ids
        kb_arm_hits["Hybrid"] += any(r.requirement_id == g["requirement_id"] for r in hybrid)
    n_kb = len(kb_cases)
    kb_fail = kb_arm_hits["Hybrid"] / n_kb < KB_FLOOR_R5
    print(f"\nKB (requêtes NL = rationales dev, n={n_kb}) R@5 :")
    print("  " + " | ".join(f"{a} {kb_arm_hits[a] / n_kb:.2f}" for a in ("BM25", "Vector", "Hybrid"))
          + f" (plancher hybride {KB_FLOOR_R5:.2f})" + ("  ✗ ÉCHEC" if kb_fail else ""))
    if kb_arm_hits["Vector"] == 0:
        print("  !! bras vectoriel KB à zéro — index KB vectoriel absent ?")
        kb_fail = True
    failed = failed or kb_fail

    print("\n" + ("ÉCHEC : plancher(s) manqué(s)." if failed else "Tous les planchers M2 sont atteints."))
    db.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
