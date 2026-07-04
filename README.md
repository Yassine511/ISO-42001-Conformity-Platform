# ISO 42001 Conformity Platform

**Copilote de conformité ISO/IEC 42001 — INT102 (Teamwill)**

AI copilot for ISO/IEC 42001 conformity assessment with a **verifiable trust layer**: every finding and every
chat answer must carry citations that a deterministic checker verifies against the source text; the system
abstains instead of guessing, a human confirms every verdict, and reliability is measured on a gold dataset.

Full specification: [Plan_Projet_INT102.md](Plan_Projet_INT102.md).

## Architecture

- `backend/` — FastAPI + SQLAlchemy (PostgreSQL). Document upload & parsing (PyMuPDF, python-docx),
  then RAG, LangGraph assessment pipeline, chat copilot, trust layer (milestones M2+).
- `frontend/` — React + Vite + TypeScript + Tailwind + TanStack Query (interface in French).
- `docker-compose.yml` — PostgreSQL, Qdrant, backend, frontend.

## Quick start (Docker)

```bash
docker compose up --build
# Frontend : http://localhost:5173   API : http://localhost:8000/docs
```

## Local development

```bash
# services
docker compose up -d postgres qdrant

# backend
cd backend
python -m venv .venv && .venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\uvicorn app.main:app --reload            # http://localhost:8000

# tests
.venv\Scripts\python -m pytest

# frontend
cd ../frontend
npm install && npm run dev                              # http://localhost:5173 (proxies /api)
```

## Configuration

Environment variables (see `backend/app/config.py`; a `.env` at the repo root is picked up by Docker Compose):

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | local Postgres | SQLAlchemy connection string |
| `QDRANT_URL` | `http://localhost:6333` | Vector store (M2) |
| `MISTRAL_API_KEY` | — | LLM provider (M3+) |
| `GROQ_API_KEY` | — | Fallback LLM (M3+) |

## Commit message convention

Commits follow a clear, descriptive format tied to the project milestones:

```
<Mx> <area>: <imperative summary>

<optional body: what changed and why, one bullet per significant change>
```

- **`Mx`** — the milestone the work belongs to (`M1a` foundation, `M1b` corpus, `M2` RAG, `M3` pipeline,
  `M4` chat, `M5` frontend/HITL, `M6` evaluation, `M7` artifacts, `M8` deliverables). Omitted for
  cross-cutting fixes.
- **`area`** — `backend`, `frontend`, `infra`, `corpus`, `eval`, or `docs`.
- Summary in the imperative mood ("add citation verifier", not "added"), ≤ 72 characters.

Examples:

```
M1a backend: add document upload and per-page parsing
M2 backend: index chunks in Qdrant with multilingual embeddings
infra: map container Postgres to host port 5433
```

## Retrieval (M2)

Hybrid retrieval = French-analyzer BM25 + vector search (fastembed
`paraphrase-multilingual-MiniLM-L12-v2`, 384-dim) merged with RRF, over a versioned Qdrant
collection (`retrieval_minilm12_v1`). PostgreSQL is authoritative; Qdrant is a rebuildable
derived index (`/index` reconciles, search hydrates from PG and discards orphans).

```
POST /api/organizations/{id}/index    # chunk + embed + reconcile (first run downloads ~220 MB model)
POST /api/kb/index                    # index the 65 ISO KB requirements (reads CORPUS_PATH)
POST /api/organizations/{id}/search   # {"query": "...", "k": 8, "scope": "policy|kb|both"}
```

Exit gates (dev gold split, `scripts/retrieval_sanity.py`, strict six-document baseline):
doc recall@5 ≥ 0.85, anchor recall@5 ≥ 0.70, anchor recall@10 ≥ 0.85 — measured
0.95 / 0.86 / 0.93 (hybrid) on corpus v1.2.0; KB scope R@5 = 0.96 on natural-language
rationale queries (floor 0.60).

## Milestones

M1a foundation → M1b French corpus + gold labels → M2 hybrid RAG → M3 pipeline core
(judge/verify/abstain, this state) → M4 chat copilot → M5 frontend HITL → M6 evaluation → M7 scoring & artifacts → M8 deliverables.

## Pipeline (M3)

LangGraph pipeline (`backend/app/pipeline/`): ① retrieve (hybrid RAG) → ② judge (Mistral, JSON
mode, French prompts; Groq fallback) → ③ verify (deterministic fuzzy citation verifier with
token-alignment guards + clause/schema/threshold checks; one bounded repair retry, then abstention).
`VERIFIED` = **citation/schema-verified** — the quote exists near-verbatim in source with exact page
offsets — not "verdict proven correct" (M6 measures verdict accuracy; M5 human review confirms).
Full per-attempt provenance (`assessments`, `findings`, `assessment_attempts`, `llm_calls`) and a
PostgreSQL checkpointer (`LANGGRAPH_STRICT_MSGPACK=true`). Exit-criterion demo (run with services up
and `MISTRAL_API_KEY` in `backend/.env`):

```
backend/.venv/Scripts/python scripts/assess_demo.py --org "Lumen AI" --requirement A.9.2  # VERIFIED
backend/.venv/Scripts/python scripts/assess_demo.py --org "Lumen AI" --requirement A.4.5  # ABSTAINED
backend/.venv/Scripts/python scripts/assess_demo.py --org "Lumen AI" --all-dev            # dev split only
```
