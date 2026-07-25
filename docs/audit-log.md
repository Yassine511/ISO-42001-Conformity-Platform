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

## Audit of 2026-07-25 — pass 5 (repo state 7f4f674)

A fifth read-only pass over the whole repository, run against a verified clean
baseline (482 backend tests, 89 frontend tests, `tsc --noEmit` clean) so every
finding below is new rather than inherited. Eleven findings, all eleven now
fixed: F1-F4 in the burn-down below, F5-F11 in the follow-up under it.

### Fixed

| § | Finding | Fix |
|---|---------|-----|
| F1 | `_hash_token` used `.encode("ascii")` on an attacker-controlled string. A single byte ≥ 0x7F in the `int102_session` cookie 500'd **every authenticated route**, and a non-ASCII invitation path token 500'd both **unauthenticated** invitation routes. Not an auth bypass — a robustness defect | UTF-8 encoding (identical bytes for every `token_urlsafe` we mint, so no stored hash moved); the miss then falls through the normal 401/404 path. Regression test covers both surfaces plus hash stability |
| F2 | `build_reporting_scope` selected whole `Finding` rows, hydrating the `retrieved` / `audit_log` JSON payloads that no calculator reads. Every reporting endpoint builds a scope and **one dashboard render fires three of them** | `load_only` on the 12 columns `EffectiveFinding` carries; `_materialize_treatments` counts actions by two columns instead of whole rows. Test asserts on the emitted SQL (a dropped `load_only` is invisible in the returned data) and is mutation-checked |
| F3 | Lock order contradicted the invariant the code itself documents (`org → case → document → versions`): `supersede_upload` took the base **version** lock first, `recover_upload_activation` took the version before the document, and the `INDEX_FAILED` handler took a document lock with **no org lock at all** — while their twin `_activate_upload_candidate` used the declared order for the same rows | New `_lock_upload_scope` helper (the upload counterpart of `_lock_activation_scope`), used by all three. Not a live deadlock — the org lock fronted every multi-row path and serialized them — but the protocol's two halves must not disagree. Tests trace the real lock sequence through `Session.get(with_for_update=…)` and are mutation-checked against the old order |
| F4 | Six free-text fields persisted into unbounded `Text` columns with no `max_length`, five of them also copied verbatim into `remediation_events.payload` — append-only, no pruning path. With nginx allowing 21 MB bodies, one request could park that in the audit trail. Id lists were unbounded too, and `create_assessment` deduped with an O(n²) `list.count()` per element | `NOTE_MAX`/`SHORT_NOTE_MAX`/`ID_MAX` bounds across the request models; `Counter` for the dedup. New `tests/test_input_bounds.py` is a **guard**: it fails for any future request-model string field added without a bound, with an explicit exemption list (passwords only, which are never stored as given) |

### Follow-up — F5 to F11 closed (same day)

The remaining seven were fixed in a second sitting; the log keeps them as their
own section because they landed after the burn-down above, not with it.

| § | Finding | Fix |
|---|---------|-----|
| F5 | `resolvedTheme` was recomputed during render while the matchMedia listener toggled the `dark` class imperatively, so an OS theme change repainted the page but never re-rendered. `ThemeToggle` reads that value for its icon AND for the theme its next click sets — the icon went stale and the first click set the theme already showing, appearing to do nothing | The OS preference is state now, and the class effect is its only writer. The listener is also unconditional: the old one unsubscribed on any explicit choice, so a change during light/dark mode was lost. Context value memoized. Five tests, three of which fail against the old component; also confirmed in a real browser by flipping the emulated OS scheme with no reload |
| F6 | `navigator.clipboard` is secure-context only and this app ships on plain HTTP by design, so «Copier le lien» threw an unhandled rejection and gave no feedback at all on a link the UI states is shown exactly once | try/catch + a French message pointing at the readonly input, which is the actual recovery. Timeout now cleaned up on unmount. Test note: `userEvent.setup()` installs its own clipboard stub, so the override has to come after it |
| F7 | `unlink_finding` never passed `actor_label`, leaving `finding_unlinked` the one event in the case stream with no attribution | `actor_label` as a QUERY parameter — this is the only DELETE in the router, and a DELETE has no body for the `RemediationActorBody` its POST siblings use. Still optional, like every other attribution field |
| F8 | `scopeIds.split(",")` submitted `""` for a trailing comma, so the server answered «Exigence(s) inconnue(s) … : » with nothing after the colon | `.filter(Boolean)` |
| F9 | `frontend/Dockerfile` pins its base by digest, so react-router 8 raising its floor to Node >= 22.22.0 could outrun the pin silently — `npm ci` only WARNS on EBADENGINE | `engines` declared in package.json, an explicit floor assertion in the build stage that names the refresh command, and a new `frontend-docker` CI job that builds the image. **The pinned digest itself is still unverified here** (no Docker daemon on the audit host) — that CI job is what will answer it |
| F10 | The gate read `report.vulnerabilities ?? {}`, so an npm report-shape change would iterate nothing and print "OK" — it could not tell "no advisories" from "I did not understand the report" | Fails closed on a missing `vulnerabilities` object or a `metadata.vulnerabilities` tally that disagrees with the parsed entries. Mutation-checked against a renamed key and a miscount fixture |
| F11 | `list_patch_proposals` queried by `case_id` with no tenant guard, leaning on `proposal_view`'s per-row org check | `_get_case` before the query, like its artifact siblings. Closes the oracle too: a foreign case answered 404 with proposals and `[]` without |

### Verified clean (scoped to what was inspected)

Mechanical route-guard enumeration across all of `app/api/*.py` — no gap. No
LLM/Qdrant/embedding call inside an open transaction at any site read. Jinja
autoescape on with zero `|safe` in `report.html.j2`. All 20 migration
downgrades present and coherent. CI does run the Postgres-only suites, so the
local skips are not a coverage gap. The M7b panel split introduced no
stale-props-in-state.
