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
  `M4` chat, `M5` frontend/HITL, `M6` evaluation, `M7a` remediation planning agent, `M7b` document-editing
  tool, `M8` artifacts, `M9` deliverables). Omitted for cross-cutting fixes. (Commits older than the
  M7a/M7b introduction use the pre-renumbering `M7`/`M8` meanings.)
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
(judge/verify/abstain) → M4 chat copilot → M5 frontend HITL → M6 evaluation (this state) →
M7a remediation planning agent (triage → corrective-action plan → per-action human approval) →
M7b document-editing tool (anchored patches, versioning; originals immutable) →
M8 scoring & artifacts → M9 deliverables. Spec: `Plan_Projet_INT102.md` (§8 remediation, §14 roadmap).

## Evaluation (M6)

Measured on the frozen corpus v1.2.0 with the pre-M5-frozen contract (question generator +
grading rubric, sha256-bound) plus pipeline scoring rules frozen before the holdout run.
Full French report: `eval/m6/rapport_m6.md`; harness `backend/app/eval/`; runners
`scripts/eval_pipeline.py`, `scripts/eval_chat_run.py`, `scripts/eval_chat_score.py`
(the holdout requires `--m6-holdout` AND `HEAD == m6-freeze` with a clean worktree outside
the run's artifact directory). Holdout (test split, n=14, Wilson 95% CIs, raw counts always
published): pipeline verdict accuracy 9/14; the verification gate blocked 3/14 unsupported
first-draft citations (0 unsupported citations displayed — a structural invariant, checked
empirically, never claimed as a measured "hallucination reduction"); chat citation-location
validity 24/24; claim–citation semantic support precision 23/32; answer faithfulness 7/10
FAITHFUL, 0 UNFAITHFUL. Weakest measured point (stated, not hidden): abstention recall on
deliberately uncovered requirements — the system asserts authentic-but-irrelevant citations
instead of abstaining (0/3 pipeline, 1/3 chat); human review (M5) and remediation (M7) are
the designed countermeasures. Dev diagnostics (n=51) reported separately, never aggregated.

## Frontend + HITL (M5)

Three French UI pages on `http://localhost:5173` (`docker compose up --build -d`):

- **Documents & évaluations** — upload, index, launch an assessment (frozen 51-requirement dev
  manifest; the M6 test split is structurally unrunnable over HTTP), live per-node progress by
  polling, resume/abandon (cooperative cancellation). Creation freezes the run contract
  (requirement manifest, `retrieval_k`, document manifest) atomically with indexing under an
  org lock — one RUNNING assessment per organization, DB-enforced.
- **Espace de revue** — the formal human confirmation stage: split view requirement ↔ evidence
  with the cited span highlighted at its persisted offsets; the displayed quote is always the
  server-derived source slice (fail-closed), never the model string. Actions: approuver /
  modifier / remplacer (only option for abstentions). The AI draft is write-once — decisions
  live in `review_*` projections plus the immutable `finding_reviews` history (re-review allowed).
- **Copilote** — chat answers rendered from `answer_segments` with clickable `[n]` footnotes
  opening the source passage in context; unanswerable questions become amber « Écart potentiel »
  cards (suggested clause + unverified per-passage model notes); provider outages render as
  neutral service notices.

The containerized backend reads API keys from the repo-root `.env` (`MISTRAL_API_KEY=…`,
compose `env_file`); `backend/.env` serves host-side CLI runs. Frontend behaviour tests:
`cd frontend && npm run test`.

## Pipeline (M3)

LangGraph pipeline (`backend/app/pipeline/`): ① retrieve (hybrid RAG) → ② judge (Mistral, JSON
mode, French prompts; Groq fallback, 429s retried with backoff before falling back) → ③ verify
(deterministic citation verifier + clause/schema/threshold checks; one bounded repair retry, then
abstention). `VERIFIED` = **citation/schema-verified with an EXACT match after normalization**
(case, accents, whitespace, typographic quotes) — not "verdict proven correct" (M6 measures verdict
accuracy; M5 human review confirms). A near-match (fuzzy) citation is only a candidate: the judge
gets one retry to re-quote exactly, then the finding abstains with reason `fuzzy_citation`,
keeping the match offsets for priority human review. Full per-attempt provenance (`assessments`,
`findings`, `assessment_attempts`, `llm_calls`) and a PostgreSQL checkpointer
(`LANGGRAPH_STRICT_MSGPACK=true`). Exit-criterion demo (services up, `MISTRAL_API_KEY` in
`backend/.env`):

```
backend/.venv/Scripts/python scripts/assess_demo.py --org "Lumen AI" --requirement A.9.2  # VERIFIED
backend/.venv/Scripts/python scripts/assess_demo.py --org "Lumen AI" --requirement A.4.5  # ABSTAINED
backend/.venv/Scripts/python scripts/assess_demo.py --org "Lumen AI" --all-dev            # dev split only
backend/.venv/Scripts/python scripts/assess_demo.py --org "Lumen AI" --assessment <id>    # resume a crashed run
```

`--assessment` resumes a RUNNING assessment after a process crash: the assessment's stored
requirement manifest is authoritative (terminal findings are returned idempotently, checkpointed
threads resume mid-flight; a mismatching `--requirement/--all-dev` selection is rejected).
