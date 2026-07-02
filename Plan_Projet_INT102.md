# ISO/IEC 42001 Compliance Copilot with a Verifiable Trust Layer
### Project Report — INT 102 Internship, Teamwill

**Author:** Yassine El Gares — Computer Systems Engineering (3rd year), MEDTECH
**Host company:** Teamwill Consulting
**Course:** INT 102 (mandatory internship)
**Document status:** Project specification & design report (implementation to follow)

---

## 1. Executive summary

This project delivers an **AI copilot for ISO/IEC 42001 conformity assessment**. The system has two faces, sharing a
single trust layer:

1. **A structured assessment pipeline** — given an organization's internal policy documents, it drafts compliance
   findings against the ISO 42001 (AI Management System) requirements, with a human confirming every verdict.
2. **A conversational copilot** — the user *discusses* the documents and the findings with the system ("do we cover
   third-party AI risk?", "why is A.7 only partially compliant?") and receives answers **with verified references**
   to both the policy text and the ISO clause.

The core engineering contribution is not "calling a language model" — that is a matter of days and produces an
unreliable tool. The contribution is the **trust layer** wrapped around the model, and it applies identically to both
faces: every finding and every chat answer must be grounded in citations that a deterministic checker verifies
against the source text; when the evidence is not there, the system **abstains** instead of guessing; a human
confirms every compliance decision; every step is logged for a full audit trail; and the system's reliability is
**measured** against a gold-standard dataset.

A memorable property of the design: the system applies **ISO 42001's own principles to itself** — human oversight,
transparency, logging, and evaluation — making it an AI tool governed the way the standard it assesses demands.

---

## 2. Context and problem statement

ISO/IEC 42001:2023 is the first international management-system standard for Artificial Intelligence. As
organizations adopt AI, they increasingly need to assess and document their conformity to it — today a slow, manual
consulting activity. In practice, consultants and auditors work **interrogatively**: they ask questions of a document
set ("where is the impact-assessment procedure?", "who owns model retirement?") and expect answers backed by exact
passages. A useful tool must support that conversational way of working, not only batch verdicts.

An obvious idea is to automate this with a large language model (LLM): feed it the policies and the standard, and let
it output compliance verdicts or chat answers. This naive approach has two fatal weaknesses in a compliance setting:

1. **Wrong answers.** An LLM can confidently output "compliant" — or confidently answer a question — when the
   evidence does not support it. In compliance, a false "compliant" is a serious, potentially liability-bearing error.
2. **Black box.** Auditors do not trust a verdict or an answer they cannot trace to evidence and cannot reproduce.

**Therefore the project's objective is not to build an AI that judges compliance, but to build the machinery that
makes an AI's compliance findings and answers verifiable, human-supervised, auditable, and measurably reliable.**

### Constraint: no real company documents
Teamwill has not yet begun its own ISO 42001 implementation, so no client documents are available. Rather than a
limitation, this is turned into a methodological strength: we author a **realistic synthetic organization with known
ground-truth labels**, which gives the evaluation a controlled, reproducible gold standard and removes all
confidentiality concerns.

---

## 3. Objectives

- Build an end-to-end tool that ingests policy documents and produces ISO 42001 conformity findings and artifacts
  (conformity dashboard, Statement of Applicability, gap & risk register, PDF report).
- Provide a **grounded chat copilot**: the user asks questions about the documents or the findings and receives
  answers whose citations are machine-verified, with clickable references to the source passages.
- Guarantee that **no verdict and no answer is asserted without machine-verified supporting evidence.**
- **Abstain** rather than guess: uncertain findings are routed to human review; unanswerable questions get an honest
  "no evidence found" instead of a fabrication.
- Keep a **human in charge of every compliance decision**.
- Maintain a **full provenance/audit trail** for every finding.
- **Measure** the system's reliability on a gold dataset: verdict accuracy and hallucination rate, with and without
  the verification layer.
- Present the system through a **clean, professional web interface**.

---

## 4. Design rationale (why this shape)

Three extreme designs were considered and rejected:

| Approach | Description | Why rejected |
|----------|-------------|--------------|
| A — Pure AI platform | LLM + RAG auto-judges documents and emits verdicts | Fast to build but untrustworthy; a black box; confidently-wrong verdicts |
| B — Pure deterministic tool | Human questionnaire + scoring, no AI | Reliable but shallow; no AI depth; risks feeling trivial |
| C — Plain RAG chatbot | "Chat with your documents" with no verification | Answers sound plausible but nothing checks the citations; useless the first time it invents a quote |

The chosen design is the **synthesis**: keep AI for what it is good at (reading documents, drafting findings, and
answering questions with evidence), but constrain it with deterministic citation verification, abstention, human
oversight, and measured evaluation. **AI proposes; deterministic code and a human decide.** The same principle
governs both the assessment pipeline and the chat.

---

## 5. System architecture

```
                ┌─────────────── Shared foundation ────────────────┐
Policy docs ───▶│ parse → chunk → embed → Qdrant (+ BM25)           │
ISO 42001 KB ──▶│ paraphrased atomic requirements (refs 4–10, A.2–A.10)│──▶ PostgreSQL
                │ hybrid retrieval (RRF) · citation verifier ·      │
                │ provenance store                                  │
                └────────────┬─────────────────────┬────────────────┘
                             │                     │
              ┌──────────────▼───────────┐  ┌──────▼──────────────────────┐
              │  Assessment pipeline     │  │  ★ Chat copilot             │
              │  (LangGraph)             │  │  question → retrieve →      │
              │  ① Retrieve → ② Judge →  │  │  cited answer → verify →    │
              │  ③ Verify → ④ Review     │  │  render with references     │
              │  (HITL) → ⑤ Score        │  │  or abstain ("no evidence") │
              └──────────────┬───────────┘  └──────┬──────────────────────┘
                             │                     │
              Conformity % · SoA · gaps ·    Verified answers · finding
              risk register · PDF report     drill-down (uses provenance)
```

**A note on the ISO 42001 knowledge base:** the text of ISO/IEC 42001 is copyrighted and cannot be reproduced in a
public repository or in the application. The knowledge base therefore contains **atomic requirements paraphrased in
our own words**, each carrying only a clause *reference* (e.g. "A.7.2") back to the standard. The system never
stores or emits verbatim ISO text; verbatim citation applies exclusively to the organization's own policy documents.

The **retriever, the citation verifier, and the provenance store are written once** and consumed by both sides. The
system has two clean layers:

- **AI proposes** — retrieval and LLM drafting (pipeline nodes ①–②; the chat's answer generation).
- **Deterministic code and human decide** — citation verification, abstention routing, human review, and scoring.

This separation is the entire reliability story and is what makes the tool defensible to an auditor.

---

## 6. The assessment pipeline (LangGraph)

The pipeline is orchestrated with **LangGraph**. A shared typed state (`GovernanceState`) carries
`requirements`, `retrieved`, `drafts`, `findings` (each tagged `VERIFIED | ABSTAINED | CONFIRMED`), `scores`, and an
`audit_log`. A **checkpointer** persists state, which makes the human-in-the-loop step resumable and lets the UI
stream per-node progress.

| # | Node | Input → Output | What it does | Trust mechanism |
|---|------|----------------|--------------|-----------------|
| ① | **Retrieve** | requirements → evidence candidates | Hybrid retrieval (BM25 + vector, merged with Reciprocal Rank Fusion) pulls the most relevant policy spans for each ISO requirement | Evidence is scoped and provenance-tagged |
| ② | **Judge** | requirement + evidence → draft finding | LLM-as-judge drafts a schema-constrained finding: `verdict, policy_quote, clause_ref, confidence, rationale` | **Grounding contract** — the model must cite an exact policy quote and a valid clause reference |
| ③ | **Verify** | draft → tagged finding | Deterministic checks: the cited `policy_quote` must exist near-verbatim in its source chunk, the `clause_ref` must be a valid knowledge-base identifier, the schema must be valid, and confidence must clear a threshold → tag `VERIFIED`, otherwise `ABSTAINED` | **Citation verification + abstention** — hallucinations are rejected by code, not trusted |
| ④ | **Review** *(human-in-the-loop interrupt)* | tagged findings → confirmed findings | The graph pauses; an auditor approves, edits, or overrides each finding in the UI; overrides are captured as data; the graph resumes | **Human oversight** — a person owns every decision |
| ⑤ | **Score & Assemble** | confirmed findings → artifacts | Deterministic computation of conformity % per clause/domain, gaps, the **derived AI risk register**, Statement of Applicability, and report | No AI in scoring → reproducible numbers |

**Why LangGraph is the right tool (not decoration):** it provides typed shared state across steps, a genuine
**human-in-the-loop interrupt** at node ④ with checkpoint/resume, and native per-node streaming for the live progress
interface — exactly the features this workflow needs.

### Designed-for-failure output contract (nodes ② + ③)

Open-weight models under a JSON-heavy grounding contract *will* sometimes emit malformed schemas, paraphrased or
truncated quotes. The system treats this as a normal, designed-for path — never an exception:

- **Constrained decoding first:** the provider's native JSON mode is enabled and the schema is kept deliberately
  small (five fields); the cited policy quote is capped at ~300 characters — short quotes are exponentially less
  likely to be truncated or paraphrased, and are easier to verify.
- **One bounded repair retry:** if Pydantic validation or citation verification fails, the draft is retried **once**,
  feeding the exact validation errors back to the model ("quote not found in source; cite verbatim"). No open-ended
  retry loops.
- **Then abstain:** a second failure tags the finding `ABSTAINED` and routes it to human review. Every failed attempt
  is recorded in the provenance log — so malformed output is not a bug to hide but a **data point**: it feeds the
  hallucination-rate metric and demonstrates the trust layer doing its job.
- **Tolerant-but-strict verification:** the citation checker does not require exact string equality (which would
  reject legitimate quotes over whitespace, casing, accents, or unicode punctuation). It normalizes both sides
  (case-fold, collapse whitespace, strip accents and smart quotes — normalization that matters doubly for French
  text, with its accents, apostrophes typographiques and non-breaking spaces) and accepts a match within a small edit-distance
  threshold of a substring of the source chunk. The threshold is a tested, documented constant: loose enough that
  honest quotes pass, strict enough that fabricated ones cannot. This matcher is the most safety-critical function in
  the codebase and is built and unit-tested against real model outputs in M3, before anything depends on it.

### Derived AI risk register (risk-based output, deterministic)

ISO 42001 is a *risk-based* management-system standard (clause 6.1.2), so the tool's outputs must speak risk, not
only conformity. Node ⑤ therefore derives an **AI risk register** from the confirmed findings — deterministically,
with no AI in the loop:

- Every `non-compliant` or `partial` finding maps to a risk entry with a **templated risk statement per Annex A
  domain** (e.g. an A.7 gap → *"Risk of untraceable or unfit training data due to a missing data-governance
  provision: ⟨requirement⟩"*).
- **Severity** reuses the existing `gap × control weight` formula, presented on a Low / Medium / High scale.
- Each entry carries a **provenance link to its source finding** (and thus its verified evidence) and a **treatment**
  — the remediation action the gap implies.

Because the derivation is pure code over human-confirmed findings, the register is reproducible and auditable like
every other score. A full AI system **impact assessment** (clause 6.1.4 / A.5) — harm categories, affected parties —
is deliberately out of scope and named as future work; assessing the organization's *own* impact-assessment
obligations remains covered as ordinary findings.

---

## 7. ★ The chat copilot (the "copilot" made real)

The chat is a first-class pillar, not a bolt-on. It is what makes the tool feel like a *copilot* rather than a batch
job, and it is the trust layer made visible: the user watches the system cite, verify, and — when the evidence isn't
there — decline to invent.

**Answer flow (every message):**

1. **Retrieve** — the question runs through the same hybrid retrieval over the policy chunks and the ISO 42001
   knowledge base.
2. **Draft** — the LLM produces a schema-constrained answer: prose plus a list of citations
   (`policy_quote` + source document/chunk, and/or `clause_ref` + our paraphrased requirement text — never verbatim
   ISO text).
3. **Verify** — the same deterministic checker used in pipeline node ③ confirms each policy quote exists
   near-verbatim in its claimed source and each clause reference resolves to a knowledge-base entry. Failed
   citations are stripped; an answer left without verified support is not shown.
4. **Render or abstain** — verified answers display with **clickable references** that open the exact passage in
   context. If nothing survives verification, the copilot **abstains as a professional finding, never as a failure**.
   In a compliance tool, absence of evidence *is* a finding — auditors call it exactly that.

### Abstention as a first-class answer (designed, not improvised)

The abstention response is specified up front, because its framing decides whether it reads as the system's best
moment or its most awkward one:

- **Voice of an auditor, not an apologetic bot.** The copilot never says "I don't know" or "Sorry, I couldn't find
  anything." The canonical form is: *"No documented evidence found. I searched the uploaded policies for coverage of
  ⟨topic⟩ and found no passage that addresses it. Under ISO 42001 this is a potential gap against ⟨clause⟩."*
- **It shows its work.** The abstention card lists what *was* searched — the top retrieved passages and why they
  don't qualify (e.g. "mentions vendors, but not AI-specific due diligence") — proving the system looked before it
  declined. An abstention with visible search effort reads as diligence; one without reads as failure.
- **It ends with an action, not a shrug:** one-click **"Add to gap register"** and **"Flag for human review"**
  buttons turn the non-answer into workflow output.
- **Distinct visual identity:** abstentions render as an amber ⚪/🟡 "Potential gap" card — the same visual family
  as findings — never in error styling (no red, no warning icons, no failure language).

**Two conversation modes:**

- **Document Q&A** — available as soon as documents are ingested, before any assessment: "Do we define roles for AI
  incident response?" → cited answer or honest gap signal. This is how a consultant explores a new client's corpus.
- **Finding drill-down** — after an assessment: "Why is A.7 only partially compliant?" The copilot answers from the
  stored finding and its provenance record (retrieved chunks, cited quotes, verification result, human decision),
  turning the audit trail into an interactive explanation instead of a static log. This replaces a separate
  provenance-viewer page: the lineage of any finding is one question away. Risk questions ("what are our top AI
  risks?") are answered the same way, from the derived risk register.

Chat exchanges are logged like everything else, so the audit trail covers conversations too.

---

## 8. The trust layer (reliability engineering)

The trust layer is the heart of the project and is **shared by both faces** of the system. It converts a
probabilistic model into a system with deterministic guarantees:

- **No claim without verified evidence** — neither a pipeline verdict nor a chat answer can assert something whose
  citation the deterministic checker cannot locate in the source text.
- **Abstention over guessing** — ungrounded or low-confidence findings are routed to a human; unanswerable questions
  get "no evidence found" instead of a fabrication.
- **Human owns every decision** — the AI is a *researcher* that drafts and cites; the human is the *judge*.
- **Full provenance / audit trail** — each finding records model version, retrieved chunks, cited quotes, confidence,
  verification result, human decision, and timestamps — the literal opposite of a black box. Chat drill-down exposes
  this trail conversationally.

(A prompt-injection scan of uploaded content at ingestion time is a stretch enhancement, out of core scope.)

---

## 9. Evaluation (minimal but real proof)

Most student AI projects claim reliability; this one **measures** it — at a deliberately contained scale. Because the
synthetic organization is authored by us, the ground truth is exact.

- **Gold dataset:** ~30–40 labelled items of the form `(policy excerpt, ISO requirement, ground-truth verdict,
  ground-truth evidence span)`, derived from the synthetic organization's documents.
- **Two headline metrics:**
  - **Verdict accuracy** — does the system reach the right conclusion?
  - **Hallucination rate** — the fraction of outputs whose citations fail verification, measured **with and without
    the verification layer**. This single before/after number is the project's proof that the trust layer works.
- The **human-override rate** (how often the auditor changes the AI's draft) is logged for free by node ④ and
  reported as an operational indicator.

Deeper evaluation — calibration analysis, ablation studies, failure taxonomy — is acknowledged as future work; the
architecture (gold JSON + a Python evaluation script) is built so those can be added without redesign.

---

## 10. Web interface

The frontend is clean and professional, sized to what the story needs. The interface language is **French**. The
first five pages below are core; the Dashboard, Statement of Applicability, and Report export pages belong to the
stretch tier defined in section 13.

**Technology:** React + Vite + TypeScript + Tailwind CSS + shadcn/ui + Recharts, with TanStack Query for data.
Design language: color-coded verdicts (🟢 compliant / 🟡 partial / 🔴 non-compliant / ⚪ insufficient evidence),
confidence indicators, and in-context evidence highlighting.

**Pages:**
- **Home** — organizations and assessments with status.
- **Upload & run** — drag-and-drop document upload with per-file status, then live per-node LangGraph progress.
- **★ Copilot chat** — the conversational interface: document Q&A and finding drill-down, with verified, clickable
  references; abstentions render as amber "Potential gap" cards with what-was-searched context and an
  "Add to gap register" action (see section 7).
- **★ Review workspace** — the human-in-the-loop screen: a split view of the ISO requirement/clause against the
  retrieved policy evidence, with the AI's cited quotes highlighted in-context, and approve / edit / override
  actions. Abstained items are flagged as "needs your judgment."
- **Dashboard** — one page, two zones:
  - *Conformity* — overall conformity gauge, verdict-breakdown donut, **Annex A radar chart** (conformity % per
    domain A.2–A.10), top-gaps list.
  - *Trust panel* — hallucination rate before vs after verification, abstention count, human-override rate. Small,
    but it answers "can you believe the AI?" at a glance.
- **Statement of Applicability** — per Annex A control: applicable Y/N + justification + status.
- **Gap & risk register** — a sortable table of gaps, each with its derived risk entry: templated risk statement,
  Low / Medium / High severity badge, and treatment (see section 6).
- **Report export** — downloadable PDF.

---

## 11. Synthetic organization and demo dataset

Since no client documents are available, we author **"Lumen AI"**, a fictional mid-size company deploying an internal
AI assistant, with roughly six policy documents deliberately seeded with a mix of compliant, partial, non-compliant,
and missing content across ISO 42001 requirements. The documents, the knowledge-base paraphrases, and the gold
labels are authored **in French** — matching Teamwill's working language and exercising the multilingual retrieval
stack end-to-end:

| Document | Primary ISO 42001 coverage |
|----------|----------------------------|
| `ai_usage_policy` | A.9 — Use of AI systems |
| `data_governance_policy` | A.7 — Data for AI systems |
| `ai_risk_management_policy` | A.5 — Impact assessment / Clause 6 — Planning |
| `model_lifecycle_policy` | A.6 — AI system life cycle |
| `third_party_ai_policy` | A.10 — Third-party and customer relationships |
| `ai_governance_charter` | A.2, A.3 — Policies and internal organization |

These documents, together with their authored ground-truth labels, **are** the evaluation gold set — giving a
controlled, reproducible benchmark. The seeded gaps also give the chat demo its best moments: questions whose honest
answer is an abstention.

---

## 12. Technology stack

| Layer | Choice |
|-------|--------|
| Orchestration | LangGraph (Postgres checkpointer, human-in-the-loop interrupt at node ④) |
| Backend | FastAPI + Python |
| LLM | **Mistral La Plateforme** (`mistral-large-latest`; `mistral-small-latest` for cheap calls) — native JSON mode, first-class French, French vendor. Fallback: Groq `llama-3.3-70b-versatile`. Batch runs are throttled to respect rate limits |
| Retrieval | sentence-transformers **`intfloat/multilingual-e5-small`** (FR/EN bilingual; alt: `paraphrase-multilingual-MiniLM-L12-v2`) + Qdrant + BM25 with a **French analyzer** (French stopwords + Snowball stemming), merged via RRF |
| Verification | Deterministic Python + Pydantic (shared by pipeline and chat) |
| Database | PostgreSQL |
| Parsing | PyMuPDF, python-docx |
| Frontend | React + Vite + TypeScript + Tailwind + shadcn/ui + Recharts |
| Reporting | ReportLab / HTML→PDF |
| Evaluation | Python eval script + gold JSON |
| Deployment | Docker Compose (FastAPI + Qdrant + PostgreSQL + frontend) |

**Non-goals (scope boundaries):** no autonomous verdicts (a human always confirms); no model fine-tuning; a single
standard (ISO 42001, though the knowledge base is structured to be extensible later); no real client data; no full
calibration/ablation study (core metrics only); no full AI system impact assessment (clause 6.1.4 — the risk
register is derived from conformity findings); no Kubernetes deployment.

---

## 13. Planning (indicative, ~7–8 weeks, solo)

| Milestone | Focus | Deliverable |
|-----------|-------|-------------|
| M1a | Foundation | Docker Compose (FastAPI + Qdrant + PostgreSQL + React); upload + parsing |
| M1b | Corpus authoring *(own workstream — ~1 week of careful writing)* | Paraphrased ISO 42001 knowledge base (French); authored Lumen AI documents (French) with seeded ground-truth labels — this **is** the gold set |
| M2 | RAG | Chunking, multilingual embeddings, Qdrant indexing, hybrid retrieval (French-analyzer BM25 + vector, RRF) |
| M3 | Pipeline core | Nodes ① Retrieve, ② Judge, ③ Verify with shared state + checkpointer; grounding contract with repair-retry-then-abstain path; fuzzy citation verifier unit-tested against real model outputs; provenance logging. **Exit criterion: a runnable end-to-end CLI demo** (one requirement → retrieve → judge → verify → abstain) — the system is demoable before any frontend exists |
| M4 | ★ Chat copilot | Grounded Q&A endpoint: retrieve → cited draft → verify → answer or abstain; chat logging |
| M5 | Frontend core + HITL | Upload & run page with live progress; review workspace (node ④); chat UI with clickable references |
| M6 | Evaluation | Gold-set run: verdict accuracy + hallucination rate (with/without verifier) — the reliability headline is secured **before** stretch features |
| M7 | Scoring & artifacts *(stretch tier)* | Node ⑤ scoring; dashboard (conformity + trust panel); gap & risk register (derived); then SoA table; PDF export; finding drill-down mode in chat |
| M8 | Deliverables | README, architecture diagram, internship report, presentation + rehearsed demo |

**Cut line (decided up front, not under panic in week 7):**

- **Core — non-negotiable:** M1–M5 + M6 evaluation. A working trust layer with a measured reliability result and a
  usable UI is a complete, defensible project even if nothing below ships.
- **Stretch — sacrificed first, in this order:** PDF export → Statement of Applicability page → finding drill-down
  chat mode → dashboard polish. Scoring and the gap & risk register sit at the top of the stretch tier (highest
  value, cut last).

---

## 14. Verification and testing

- **Unit tests:** the citation verifier (a planted fake quote is rejected; a real quote passes; a quote differing
  only by whitespace/casing/accents/smart-quotes passes; a paraphrase beyond the edit-distance threshold is
  rejected); the repair-retry path (malformed JSON → one retry → `ABSTAINED`); scoring invariants; Pydantic
  validation on every model output; node ③ routing (a forced failure yields `ABSTAINED`).
- **Adversarial tests:** a statement that superficially looks compliant but is not → no false "compliant"; an
  irrelevant document → abstention, not fabrication; **a chat question with no supporting evidence in the corpus →
  the copilot abstains instead of inventing a quote.**
- **System-level:** the gold-set evaluation (accuracy + hallucination before/after verification) is the reliability
  proof.

---

## 15. Deliverables

1. GitHub repository — LangGraph backend + chat copilot + React frontend + trust layer + evaluation script + Docker
   Compose + documentation.
2. A working human-in-the-loop compliance copilot (assessment pipeline + grounded chat) on the Lumen AI dataset.
3. A **reliability result** — verdict accuracy and the hallucination rate before/after verification.
4. ISO artifacts — Statement of Applicability, gap & risk register, PDF report.
5. The internship technical report (rapport de stage).
6. A presentation with a rehearsed live demonstration.

---

## 16. Demonstration script

Upload the Lumen AI documents → **ask the copilot a question** ("do we manage third-party AI risk?") and get an
answer with verified, clickable references → ask a question the corpus cannot support and watch the copilot produce
a **"Potential gap"** card — showing what it searched, citing the relevant ISO clause, and offering to add the gap
to the register — instead of inventing a quote → run the assessment with live per-node progress → the review workspace
shows a grounded finding with highlighted evidence and an abstained item flagged for human judgment → the human
confirms decisions → the dashboard fills in, its trust panel showing the **hallucination rate collapsing** once
verification is on → the gap & risk register shows each gap translated into a **severity-rated AI risk** →
**drill into a finding via chat** ("why is A.7 partial?") and see its full lineage explained
conversationally → export the Statement of Applicability and the PDF report. The system is the opposite of a black
box, and the user talked to it the whole way.

---

## 17. Open items (to confirm at kickoff)

- Live-progress transport: Server-Sent Events (nicer) vs polling (simpler).
- Final name for the synthetic organization (placeholder: "Lumen AI").
