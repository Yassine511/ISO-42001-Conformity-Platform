# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ISO/IEC 42001 compliance copilot with a **verifiable trust layer**: AI drafts compliance findings and
chat answers, deterministic code verifies every citation against source text, uncertain outputs become
abstentions, and a human confirms every verdict. Full spec: `Plan_Projet_INT102.md` (§14 = milestone
roadmap). Currently through **M3** (LangGraph pipeline `backend/app/pipeline/`: retrieve → judge →
verify, fuzzy citation verifier, one bounded repair retry then abstention, per-attempt provenance in
`assessments/findings/assessment_attempts/llm_calls`, CLI demo `scripts/assess_demo.py`); next is
**M4** (chat copilot reusing the same retrieval + citation verification). After M6, core continues
with **M7a/M7b** (remediation planning agent + optional document-editing tool, spec §8: triage →
corrective-action plan → per-action human approval → anchored patch with raw-equality unique anchors;
**original uploads are immutable** — agent output is always a separate artifact or an explicitly
activated `DocumentVersion`); the former M7/M8 stretch milestones are now **M8/M9** — old milestone
numbers in commit history predate this renumbering. M3 semantics: `VERIFIED`
means **citation/schema-verified via an EXACT match after normalization** (quote exists in source,
clause matches, schema valid) — never "verdict proven correct"; a fuzzy near-match only earns a
repair retry then `ABSTAINED(fuzzy_citation)` for human review; verdict accuracy is measured in M6,
human review (M5) produces CONFIRMED.

User-facing text (UI, API error messages, corpus, gold labels) is **French**. Code, comments and
commits are English.

## Commands

```bash
# backend tests (run from backend/ — 100+ tests, no Docker/model/LLM needed)
cd backend && .venv/Scripts/python -m pytest -q
.venv/Scripts/python -m pytest tests/test_retrieval.py::test_index_and_search_policy -q  # single test

# corpus consistency (KB/gold/documents cross-checks; also runs under pytest)
backend/.venv/Scripts/python scripts/validate_corpus.py

# retrieval quality gates (needs live postgres+qdrant and the indexed corpus)
backend/.venv/Scripts/python scripts/retrieval_sanity.py --org "Lumen AI"

# full stack — frontend :5173, API :8000/docs, postgres host-port 5433, qdrant :6333
docker compose up --build -d

# local backend dev (services in Docker, app on the host)
docker compose up -d postgres qdrant
cd backend && .venv/Scripts/uvicorn app.main:app --reload

# frontend
cd frontend && npm run dev        # dev server, proxies /api
cd frontend && npm run build      # tsc + vite production build

# new DB migration (Alembic; migrations run automatically at backend startup)
# add backend/alembic/versions/000N_*.py by hand following the existing pattern
```

## Commit convention

`<Mx> <area>: <imperative summary>` — milestone tag (`M1a`…`M9`, omit for cross-cutting), area is
`backend|frontend|infra|corpus|eval|docs`. See README for examples.

## Architecture: the invariants that matter

**Provenance chain (the whole point of the design).** `documents → document_pages → chunks` in
PostgreSQL. Every chunk stores `page_number, char_start, char_end` with the tested invariant
`page_text[char_start:char_end] == chunk_text`. The M3 citation verifier will resolve quotes through
these offsets — never break them. Chunk ids are content-addressed:
`sha256(document_id:parser_version:chunker_version:page:start:end)`. Bump `PARSER_VERSION`
(`services/parsing.py`) or `CHUNKER_VERSION` (`services/chunking.py`) whenever extraction/chunking
logic changes.

**PostgreSQL is authoritative; Qdrant is a derived, rebuildable index.** `/index` and `/kb/index` are
full reconciliation operations: embed + upsert (`wait=True`) → commit PG → delete stale points **by
actual raw point id** (never a recomputed/stringified id). Search hydrates results from PG (policy) or
the versioned KB JSON (kb) and silently discards anything unknown — orphan vectors can never surface,
and hydration re-checks `organization_id` (point payloads are never trusted for isolation). Qdrant
being down is a 503, never a silent skip.

**One versioned Qdrant collection** (`retrieval_minilm12_v1`) holds two source types distinguished by
payload: policy chunks (org-scoped) and the 65 ISO KB requirements (scoped by `corpus_version`).
`result_id` namespace: `chunk_id` for policy, `kb:{corpus_version}:{requirement_id}` for KB. Changing
the embedding model or chunker semantics means a **new collection name** + reindex, not mutation.

**Hybrid retrieval** = BM25 (French analyzer: accent-strip, stopwords, Snowball stemming;
`BM25Plus` deliberately — Okapi's negative IDF inverts relevance on tiny corpora; candidates filtered
by token overlap, rebuilt per request, no caching) + vector arm, fused with RRF (k=60, 1-based ranks,
`result_id` tie-break). Embeddings come through an injectable provider (`services/embeddings.py`);
tests swap in a hashed-BoW fake and an in-memory Qdrant via `tests/conftest.py` — CI never downloads
the model (~220 MB, cached in the `fastembed_cache` Docker volume).

## The corpus is a versioned artifact, not fixtures

`corpus/` = paraphrased ISO 42001 KB (65 requirements, clauses 4–10 + Annex A) + 6 French "Lumen AI"
policy documents with deliberately seeded gaps + 65 gold labels (100% KB coverage, dev/test split —
**test split is reserved for the M6 report, never for tuning**). `corpus_version` must match between
KB and gold (validator-enforced). Gold `evidence_quote_fr` must be a verbatim NFC substring of its
document — **any edit to a corpus document must be followed by `scripts/validate_corpus.py`**; a
broken quote is a blocking error. 11 requirements are deliberately uncovered corpus-wide (the correct
system answer is abstention). Conventions and verdict semantics: `corpus/README.md`.

**Copyright constraint:** the ISO 42001 text is copyrighted. The KB contains only paraphrases with
clause references; never commit standard text to the repo (the validator flags paraphrases > 400
chars as a verbatim guard). The French standard PDF used as reference lives outside the repo.

## Retrieval quality gates (M2 exit criteria, re-run after retrieval changes)

`scripts/retrieval_sanity.py` enforces, on the dev gold split against a checksum-verified
six-document baseline: doc recall@5 ≥ 0.85, evidence-anchor recall@5 ≥ 0.70 (full quote containment,
not overlap), anchor recall@10 ≥ 0.85, KB-scope hybrid R@5 ≥ 0.60 with a hard failure if the KB
vector arm scores zero. It prints a BM25 | Vector | Hybrid ablation; last clean baseline:
0.95 / 0.86 / 0.93 policy, KB 1.00 | 0.86 | 0.96.

## Working style expectations

The user audits delivered work rigorously (four audit rounds so far, most findings valid) and expects
claims to be verified against sources or reproduced before being accepted — do the same: reproduce a
reported bug before fixing it, and never publish a metric that wasn't measured on a clean baseline.
Milestone work follows plan → adversarial review → implement → measure gates → commit + push.
