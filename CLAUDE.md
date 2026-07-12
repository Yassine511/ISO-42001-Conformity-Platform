# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ISO/IEC 42001 compliance copilot with a **verifiable trust layer**: AI drafts compliance findings and
chat answers, deterministic code verifies every citation against source text, uncertain outputs become
abstentions, and a human confirms every verdict. Full spec: `Plan_Projet_INT102.md` (§14 = milestone
roadmap). Currently through **M7a** (M3: LangGraph pipeline `backend/app/pipeline/`: retrieve → judge →
verify, fuzzy citation verifier, one bounded repair retry then abstention, per-attempt provenance in
`assessments/findings/assessment_attempts/llm_calls`, CLI demo `scripts/assess_demo.py`. M4: grounded
chat `backend/app/chat/` — claim-bound draft (a claim survives only if EVERY citation it references
verifies: exact quote match + clause among the RETRIEVED KB requirements; the answer is assembled
server-side from surviving claims, fuzzy quotes stripped with provenance). Chat verification is
**citation-location verification** (exact after documented normalization), never semantic entailment —
an authentic-but-irrelevant quote passes; claims carry `citations_verified`. Chat is **passive review**:
answers are labelled AI drafts, the reader assesses support via rendered source slices at matched
offsets (no formal chat-claim confirmation workflow); citation quality is measured in M6. Formal human
confirmation applies to pipeline findings (M5 workspace).
Same verifier/retrieval/LLM layer, conversation logging in
`conversations/chat_messages/chat_llm_calls`, CLI demo `scripts/chat_demo.py`.
M5: frontend core + HITL. Assessment run API (`backend/app/api/assessments.py` + shared runner
`backend/app/pipeline/runner.py` — the CLI delegates to it): the persisted Assessment row is the
**run contract** (frozen requirement manifest + `retrieval_k` + `document_manifest`), creation is
atomic index-then-create under the org row lock (`services/run_guard.py`; corpus mutations 409
while RUNNING), a partial unique index enforces one RUNNING per org, cancellation is cooperative
(`cancel_requested`), live progress is **polled** (resolves spec §18 — no SSE). Human review is an
**application-level stage over persisted findings**, never a LangGraph interrupt: AI finding
columns are write-once; the decision lives in `review_*` projection columns + the immutable
`finding_reviews` table (approve/edit VERIFIED-only, override is the only action for ABSTAINED,
re-review appends history). UIs render **server-derived source slices** (`services/provenance.py`,
fail-closed) — never model quotes; wording «citation localisée, pertinence à confirmer». Chat
serves `answer_segments`/`answer_caveat` so footnotes never require splitting `answer` client-side.
**M6 holdout protection is structural**: runs draw only from the frozen 51-id dev manifest
(`backend/app/pipeline/dev_split.py`, cross-checked against gold in tests); `create_assessment`
rejects test-split ids unless `allow_holdout=True` (M6-script-only, unreachable over HTTP).
Frontend pages: upload & run (per-node live progress), review workspace (split view + offset
highlighting), chat (footnote citations, amber «Écart potentiel» abstention cards; infrastructure
abstentions always neutral). Frontend tests: Vitest + Testing Library (`npm run test`).
M6 (evaluation) is **done** — harness `backend/app/eval/` (frozen scoring rules
`eval/m6/regles_notation_pipeline.md`; the headline pipeline table is a **verification-gate
diagnostic**, never an "ablation": post-gate 0 unsupported displayed citations is a structural
invariant, checked empirically; Wilson CIs everywhere; tamper-proof grading sheets with
structural rubric-§4 masking) + runners `scripts/eval_{pipeline,chat_run,chat_score}.py`
(`--m6-holdout` requires HEAD == `m6-freeze` tag and a worktree clean outside
`eval/m6/runs/<run_id>/`; sealed first pass, ONE predeclared recovery per failure mode —
resume / lineage-linked recovery assessment / re-ask; explicit N vs n_scored). Holdout results
(n=14, full report `eval/m6/rapport_m6.md`): verdict accuracy 9/14 (64,3 % [38,8; 83,7]), gate
blocked 3/14 unsupported first drafts, 0 invariant failures; chat location validity 24/24,
pair support precision 23/32, faithfulness 7/10. Known weakness: abstention recall on the
uncovered requirements (0/3 pipeline — authentic-but-irrelevant citations earn VERIFIED
partial verdicts; the M5 review + M7 remediation are the countermeasures). Grading: AI-prefilled
labels reviewed/accepted by the author (declared deviation from rubric §6). Eval runs use the
dedicated org **"Lumen AI (eval M6)"** (exactly the six corpus documents — the demo org carries
an extra upload and fails the checksum baseline).
**M7a (remediation planning agent) is done** — `backend/app/remediation/` +
`api/remediation.py` + frontend remediation pages, migration `0013`. A case opens from a
CONFIRMED **gap** finding only (`human_verdict IN partial/non_compliant/missing` — CONFIRMED
alone includes compliant); one ACTIVE case per finding (finding row lock at
creation/link/reopen); link rows snapshot the finding's review state. Triage is
LLM-suggested/human-approved with a stale-input contract: `evidence_revision` on the case,
drafts snapshot it, link/unlink only in TRIAGE, approval names an EXPLICIT draft id. Plans
draft synchronously (chat-style ≤2 attempts) under a PLANNING lease renewed via
`complete_json(on_call_finished=...)` (stale lease ⇒ `draft_interrupted` recovery row, never
activated; lost heartbeat ⇒ persistence refused), gated deterministically by **requirement
binding** (`impacted_requirement_ids ⊆ allowed_requirement_ids` actually offered in the
prompt — a KB-valid-but-unoffered id fails) and **quote binding** (`quote_source_id` must
name one server evidence item, exact-only against THAT item, `matched_chunk_id ==
quote_source_id`). Abstention taxonomy: completed outcomes
(`schema_invalid|verification_failed|llm_error|rate_limited` — may activate/supersede per
`active_plan_id`, the sole authority) vs operational aborts
(`retrieval_error|draft_interrupted` — audit rows, never activated, previous state
restored). Actions: write-once AI columns + human projection (approve/edit/reject; re-review
only while APPROVED; mandatory priority); the human-approved effective scope lives in
`remediation_action_requirements` (never the AI list); lifecycle and effectiveness are
independent dimensions; **active-plan action authority** — actions of superseded/abstained
plans are inert archives and never block closure; CLOSED cases are immutable except reopen
(which re-locks findings against active-case collisions). Scoped reassessments: append-only
launch records with a pre-generated `planned_assessment_id`
(`create_assessment(assessment_id=...)`), PENDING until `runner.launch` (False = live local
thread = success), deterministic reconciliation with org+manifest verification; holdout
exclusions always explicit (`included_requirement_ids`/`excluded_holdout_ids`); zero-dev
scopes cannot cite a reassessment. Everything audits into append-only `remediation_events`
(validated versioned payloads) + the `remediation_attempts`/`remediation_llm_calls` pair.
Injection posture: JSON-escaped evidence blocks + server-owned identifier lists; the
adversarial suite proves the deterministic contracts hold, never that a live model is
unsteerable.
**M7b (document-editing tool, spec §8) is done** — `backend/app/remediation/patcher.py` +
`services/anchors.py` + `services/checksums.py` + `services/version_events.py` +
frontend patch panels, migration `0014`. The founding invariant holds in every path:
**original uploads are immutable**; agent output is a separate `RemediationArtifact` or an
explicitly activated new `DocumentVersion`, never a change to the company's file. A genuine
restructuring migration puts `Document → DocumentVersion → pages/chunks`: pages/chunks are
re-parented under a version (composite ownership FKs prove `document_id` and
`document_version_id` name the same logical document), `documents.checksum/parser_version/
page_count` become projections of the current version (`checksum == current_version.
source_checksum`, raw bytes) written only on successful parse, and `Document.current_version_id`
(post-hoc circular FK, 0013 pattern) is the single authority for which version serves
retrieval. Two checksums, never interchangeable: `source_checksum` (raw uploaded/generated
bytes; org-level dedup + the M6 corpus baseline) and `text_checksum` (canonical
length-prefixed page-sequence hash, `services/checksums.py`; always computable, basis of
patch anchoring and the per-document reversion rule). Chunking is **write-once per version**:
`CHUNKER_VERSION` "3" with version-scoped ids (`make_chunk_id_v3`); pre-M7b `document_id_v2`
rows are reused verbatim, never recomputed, so `findings.matched_chunk_id` survives; the
assessment manifest records `chunker_version`/`chunk_id_scheme` **per document version** (a
mixed v2/v3 corpus is never described by one global claim). **Anchor primitive**
`find_all_exact_anchors(text, anchor_quote) -> list[Span]` is raw literal equality — no NFC,
no casefold, no whitespace folding (the deliberate opposite of the read-side
`pipeline/verifier.py`) — returning every occurrence including overlapping; the write gate
accepts an anchor only when it returns **exactly one** span on page 1 within bounds
(`MIN_ANCHOR_LEN=20`), else `ABSTAINED` (taxonomy `anchor_not_found|anchor_ambiguous|
schema_invalid|llm_error|rate_limited|draft_interrupted`; an ABSTAINED proposal persists NO
resolved span). TXT/MD get the patch flow (server-owned `RemediationContext` + staleness pins
`input_action_review_count/input_plan_id/input_case_evidence_revision`; a DRAFTING lease on
the proposal row itself — the case PLANNING lease is structurally unusable on IN_PROGRESS
cases; ≤2 attempts with one repair); PDF/DOCX get a labelled Markdown `RemediationArtifact`
only — the patch/artifact flow **can never create a PDF/DOCX version**; only an explicit
human superseding re-upload can, which may cite `document_versions.source_artifact_id` to
close the corrective-action loop. **Retrieval is version-aware with PostgreSQL as the sole
current-state authority** (no mutable Qdrant payload projection): one `{document:
current_version_id}` snapshot per hybrid-search attempt feeds the vector filter
(`document_version_id` MatchAny), the BM25 corpus AND hydration, so RRF never fuses two
corpus states; a mid-search activation retries the whole attempt once, a second flip raises
`CorpusChangedError` (search/chat → retryable 409 with nothing persisted; triage/planner →
`ABSTAINED(retrieval_error)`; assessments shielded by the run guard). The **human-edited
final text is the only text applied**, inside a token-fenced two-phase activation: Tx A
(lock order org[run_guard]→case→document→versions) validates the staleness pins + base
checksum, applies the op at the resolved span, serializes exact UTF-8, and creates a
`PENDING_INDEX` candidate + pages + chunks + `patch_decisions` (UNIQUE proposal_id) +
activation lease; indexing is lock-free with token-fenced heartbeats; Tx B (every candidate
mutation fenced by `activation_token`) rechecks no-assessment-RUNNING (temporary conflict:
keep PENDING_INDEX, clear token), authority (`ABANDONED(stale_action|authority_lost)`), a CAS
on `current_version_id`/base-ACTIVE (`ABANDONED(stale_base)`) and org-wide current
source_checksum (`ABANDONED(checksum_conflict)`), then flips base→SUPERSEDED (flushed first
vs the one-ACTIVE partial unique)→candidate→ACTIVE + mirrors + `version_indexed`/
`version_activated` document events. Duplicate decisions are idempotent status reads
(200 active / 202 pending / typed 409), never opaque conflicts; recovery takes over the token
(fencing a stale worker) and re-drives idempotently; **ABANDONED is terminal and does NOT
reserve its `text_checksum`** (partial unique `WHERE state <> 'ABANDONED'`) so a fresh
authorized proposal reproducing the same correct content can still activate. Superseded
versions/pages/chunks are **never deleted** (findings keep citing their exact text; the
delete guard refuses on any version history or patch/artifact lineage). This is
**intentional, not an oversight**: `DELETE /documents/{id}` returns a clean 409 once a
document has version history or is referenced by a patch proposal/artifact, and the DB
backstops it (`document_versions.source_artifact_id` is `ON DELETE RESTRICT`, so a cited
artifact cannot be removed out from under its version) — never CASCADE/SET NULL, which would
silently drop the action→artifact→file→version audit chain. There is deliberately no
org-delete endpoint. Legitimate erasure (GDPR, a wrongly-uploaded file) would be a **separate,
explicitly audited purge workflow**, not a silent cascade — out of scope for now. Two audit streams:
case-scoped `remediation_events` (patch_*/artifact_*/version_superseded_by_upload) and the
new append-only `document_version_events` (generic lifecycle, sequence under the document
lock — `version_indexed` recorded only in the locked activation/recovery tx after Qdrant
success). LLM provenance stays in `remediation_attempts` (stages `patch`/`artifact`) +
`remediation_llm_calls`. **Post-deploy after 0014: run `/index` per organization** — points
must gain the `document_version_id` payload (a point lacking it fails closed until
re-upserted). Anchor contract corpus: `eval/m7b/anchor_cases.json` +
`scripts/eval_patch.py` (deterministic, 100%-or-unsafe, run under pytest). The former
M7/M8 stretch milestones are now **M8/M9** — old milestone numbers in commit history predate
this renumbering. M3 semantics: `VERIFIED`
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

# retrieval quality gates (needs live postgres+qdrant and the indexed corpus;
# use the clean eval org — the demo "Lumen AI" org has an extra upload and fails
# the six-document checksum baseline. Host runs also need
# FASTEMBED_CACHE_DIR="C:\Users\Yassine El Gares\.cache\fastembed" — HF downloads
# are SSL-blocked on this machine; the model was copied out of the Docker volume)
backend/.venv/Scripts/python scripts/retrieval_sanity.py --org "Lumen AI (eval M6)"

# full stack — frontend :5173, API :8000/docs, postgres host-port 5433, qdrant :6333
docker compose up --build -d

# local backend dev (services in Docker, app on the host)
docker compose up -d postgres qdrant
cd backend && .venv/Scripts/uvicorn app.main:app --reload

# frontend
cd frontend && npm run dev        # dev server, proxies /api
cd frontend && npm run test       # Vitest + Testing Library behaviour tests
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
Mainline is corpus **v1.3.0** (M8): each KB requirement carries a control `weight` (1|2|3,
validator-enforced) — but M8 reporting resolves weights through the immutable policy registry
`backend/app/services/scoring_policy.py` (m8-1), never the live KB, so history stays reproducible.
The published M6 result stays frozen at v1.2.0 (`m6-freeze` tag).

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
