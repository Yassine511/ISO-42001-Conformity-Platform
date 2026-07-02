# Copilote de conformité ISO/IEC 42001 — INT102

AI copilot for ISO/IEC 42001 conformity assessment with a **verifiable trust layer**: every finding and every
chat answer must carry citations that a deterministic checker verifies against the source text; the system
abstains instead of guessing, a human confirms every verdict, and reliability is measured on a gold dataset.

Full specification: [Rapport_Projet_INT102.md](Rapport_Projet_INT102.md).

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

## Milestones

M1a foundation (this state) → M1b French corpus + gold labels → M2 hybrid RAG → M3 pipeline core
(judge/verify/abstain) → M4 chat copilot → M5 frontend HITL → M6 evaluation → M7 scoring & artifacts → M8 deliverables.
