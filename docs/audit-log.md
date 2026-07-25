# Audit log

Running record of code-review audits, what they found, and where each finding
landed. The original audit documents were working notes outside the repo; this
file is their durable trace. Newest entries last within each audit.

## Audit of 2026-07-25 (repo state 671ac09)

Full read-only review by the project author. Every finding below was
re-verified against the code before being acted on; none were fixed on faith.

### Pass 1 — correctness & auth (commits `5458d6d`, `9215644`, `c1620a0`)

| § | Finding | Outcome |
|---|---------|---------|
| 1.1 | Patcher held a DB transaction across the embedding call | Fixed |
| 1.2 | `correction_note` required-vs-nullable mismatch | Fixed |
| 1.3 | Nondeterministic PENDING coverage row in reporting | Fixed |
| 4.1 | Invitations could not be accepted by an existing account | Fixed (sign-in accept path) |
| 4.2 | No member management | Fixed (members/invitations endpoints + dialog) |
| — | `postcss` advisory | Bumped |

### Pass 2 — performance, security posture, UX (commits `009ab77` → `21846e5`)

| § | Finding | Outcome |
|---|---------|---------|
| 2.1 | Full ORM rows loaded where columns sufficed | Fixed (`load_only`) |
| 1.4 / 1.6 | Two minor correctness issues | Fixed |
| 4.3–4.5 | Inverted/misleading UI affordances | Fixed |
| 1.5 | Unknown-e-mail login skipped the bcrypt cost (timing oracle) | Fixed (dummy-hash compare) |
| 3.1 | `/api/kb/index` spammable | Single-flight lock (authz still needs the deliberately-absent role column) |
| 3.3 / 3.4 | Header hardening; HSTS deliberately omitted (plain-HTTP listener) | Fixed / documented |
| 5.1 | Concurrent startup migrations raced | PG advisory lock + `--workers 1` documented |
| 5.3 | Startup ordering issue | Fixed |
| 2.3 | LLM calls unbounded in wall-clock time | `llm_call_budget_seconds` (240 s) |
| 2.4 | Frontend retried 4xx | `ApiError` + no-retry-on-4xx |
| — | Dead code (vulture + knip) | Removed |

### Pass 3 — the remainder (commits `e35aa7d` → `14be7aa`)

- **Migration↔model cross-check** (`test_migration_head_matches_the_models`):
  upgrades a virgin Postgres through the whole chain and diffs against
  `Base.metadata`. Found **7 real drifts**: 4 under-declared circular FKs (now
  `use_alter=True`; `fk_documents_current_version` is **composite** —
  `(id, current_version_id) → (document_id, id)`) and 3 leftover backfill
  `server_default=''` (dropped by migration `0020`). Knock-on:
  `conftest.seed_parsed_document` set `current_version_id` in the same INSERT
  as the document — valid only against the weaker test schema; production
  Postgres always refused it.
- **§2.2** trust-panel telemetry now counts in SQL (`COUNT`/`GROUP BY` under a
  per-assessment manifest predicate — a flat id-set union is the bug, pinned
  by a mutation-checked test). Two single-column scans remain deliberately
  (JSON-array contents need dialect-specific unnesting).
- **§3.2** rate limiting on login / signup / invite-accept
  (`services/rate_limit.py`). The signup 409 still discloses account
  existence: structural without e-mail infrastructure; throttling bounds the
  oracle, the message stays clear. Documented in the README.
- **§6** file splits: `app/models/` package (33 tables pinned by a guard
  test), `src/api/` directory, `src/pages/remediation-case/` panels — import
  surfaces unchanged.
- **react-router 6→7** (7.18.1) + replacement of the blunt
  `npm audit --audit-level=high` with `scripts/audit-gate.mjs`.

### Verification pass before push (commits `3df023a`, `aa91839`)

Independent re-audit of pass 3 against the code. Two findings:

1. **X-Forwarded-For spoofing bypassed the new rate limiter** (the one real
   hole). nginx never set the header, so a client-supplied value passed
   through the proxy verbatim; `client_ip()` reads its first entry, so any
   caller could rotate the `(email, IP)` throttle key per request. The
   original justification — "forging rotates only half the key" — does not
   hold: rotating either half of the key is a fresh counter. **Fix**: nginx
   now sets `proxy_set_header X-Forwarded-For $remote_addr` (overwrite, never
   `$proxy_add_x_forwarded_for`, which appends after the spoofed value).
   Residual, accepted: a caller reaching the backend port directly can still
   forge it — in the compose deployment that port sits on the same host trust
   boundary as the published Postgres port.
2. **The "509 passed" backend run was shell-dependent.** A pre-existing flake:
   `test_chat_eval_generator` decoded the child's French stderr with the
   console locale while the child emitted UTF-8 — mojibake under plain
   PowerShell (cp1252), green elsewhere. **Fix**: both sides of the subprocess
   pipe pinned to UTF-8. Also refreshed a comment in `test_migrations.py` that
   the FK drift fix had made stale.

### Follow-up — audit-gate expiry redesign + react-router 8 (same day)

The react-router exception carried `reviewAfter: 2026-10-01`, i.e. CI would go
red on a calendar date regardless of whether anything had changed. Redesigned:
an exception now declares **`fixedIn`** (the version that fixes the advisory)
and the gate asks the npm registry on **every run** whether that version is
published, failing only the day action is possible; `reviewAfter` remains
solely for advisories with no known fix version, and an exception declaring
neither is itself a failure.

The mechanism paid for itself on its first live run: it flagged that
**react-router 8.3.0 had already been published** (2026-07-22). The pass-3
manual check had queried `react-router-dom` — a package v8 retires (v8 apps
import from `react-router` directly) — and concluded v8 didn't exist.
Upgraded: `react-router-dom@7.18.1` → `react-router@8.3.0`, 23 import sites +
the Vite vendor chunk rewritten, **zero remaining npm advisories**, exception
list now empty. Note: react-router 8 requires Node ≥ 22.22 (CI's
`node-version: "22"` resolves above that; local installs below it only warn).
