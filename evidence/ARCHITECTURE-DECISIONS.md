# Architecture Decision Record — IssueTrack Lite (Release Candidate 1)

Date: 2026-11-19 (UTC)
Status: Final for this build stage
Scope: decomposes the Stage A backlog and records stack/architecture choices.

## 1. Task backlog decomposition

| # | Work item | AC coverage |
|---|-----------|-------------|
| B1 | Auth & profile (register/login/logout/me) | FR-001..004 |
| B2 | Workspaces & membership (CRUD, roles, last-admin invariant, auto-unassign on removal, role-safe member views) | FR-010..018 |
| B3 | Projects (create/list/get/patch incl. archive flags; admin-only writes) | FR-020..025 |
| B4 | Issues (create/list/filters/pagination/patch/delete; free status transitions; assignee rules; archived-project read-only) | FR-030..039 |
| B5 | Comments & activity (append-only, 16 canonical actions, paginated newest-first, no mutation) | FR-040..044 |
| B6 | Dashboard (status totals, priority totals, overdue rule, workspace scoping) | FR-050..053 |
| B7 | Input validation & safe errors per contract (422 shape, 404/403/409 semantics, no leakage) | FR-060/061, SEC-* |
| B8 | Browser UI: login/register, workspace switcher, dashboard, projects, issues (create/edit/assign/status/comment), activity feed; keyboard-accessible; 375/1280 responsive | FR-062, NFR-001..003, UX spec |
| B9 | Testing: unit (domain logic), integration (API incl. tenant isolation), E2E (browser-driven) | traceability |
| B10 | Security/NFR: bcrypt hashing, token sessions, CORS, secrets scan, dependency audit, structured logs w/o secrets | SEC/NFR |
| B11 | Ops: migrations (schema setup), deterministic seed, health endpoint, restart-persistence, reproducible runbook | NFR-006/007/009 |

## 2. Stack decisions (justified)

| Decision | Choice | Rationale |
|---|---|---|
| Language/runtime | Python 3.12 (3.12.11) pinned in runbook | Pre-installed in the environment; fast to implement; strong typing via Pydantic 2. |
| Web framework | FastAPI 0.165.0 + Uvicorn 0.54.0 | Native OpenAPI alignment, Pydantic validation (422 semantics), async, small footprint. Exact pinned versions in requirements.txt. |
| Database | SQLite (stdlib `sqlite3`) in WAL mode, file at `data/issuetrack.db` | Zero-external-service persistence (NFR-008); survives restarts (NFR-009); parameterized queries via `sqlite3` placeholders (SEC-022). Schema managed by idempotent `migrate.py` (constraint 5). |
| Concurrency | Single process + per-request `BEGIN IMMEDIATE` write transactions on SQLite + in-process locks for last-admin invariants | Contract-level concurrency semantics (MEM-008/009/010: "paired simultaneous requests") are met without paid/external services; documented limitation for multi-process deployments (see KNOWN-LIMITATIONS). |
| Password hashing | `bcrypt` (via `bcrypt` PyPI package, cost 12) | Modern adaptive hash per SEC-001. |
| Bearer tokens | 256-bit `secrets.token_hex(32)` stored hashed (SHA-256) in `sessions` table; per-session invalidation on logout; session table pruned on use | Contract mandates bearer tokens (06-API); avoids cookies → CSRF N/A for external API (SEC-023/025 documented strategy); no tokens in URLs; log-redacted. |
| Rate limiting | In-process sliding-window counter (login/register): 20 req/min per IP+endpoint, 429 on excess | SEC-002 abuse control, documented as MVP-strength (per spec limitation). |
| Frontend | Single-page static app: vanilla JS + CSS served by FastAPI from `/` (`static/`); semantic/accessible markup (roles, labels, focus-visible, no framework) | Evaluator uses semantic queries only; minimal dependencies; no build step → reproducible. |
| CORS | Allow the two documented runtime origins `http://localhost:40309` and `http://localhost:47775` plus `http://127.0.0.1:8000`/`http://localhost:8000`; no wildcard, no credentials | SEC-025 restrictive CORS. |
| Logging | stdlib `logging` JSON-like structured logs; `token`, `password`, `Authorization` headers redacted (SEC-033). |
| Time handling | All timestamps stored as UTC `YYYY-MM-DDTHH:MM:SSZ`; overdue computed from `datetime.now(timezone.utc).date()` regardless of process TZ (FR-051, NFR-005). |
| Service bind | `0.0.0.0:8000` per contract; health `GET /api/health` → 200 `{"status":"ok"}`. |

## 3. Domain model (min. required + support)

- `users(id, email_lower UNIQUE, email, display_name, password_hash, created_at)`
- `workspaces(id, name, created_at)`
- `memberships(id, workspace_id, user_id, role, UNIQUE(workspace_id,user_id))`
- `projects(id, workspace_id, name, description, archived, created_at, updated_at)`
- `issues(id, workspace_id, project_id, title, description, type, status, priority, assignee_id, due_date, creator_id, deleted, created_at, updated_at)`
- `comments(id, issue_id, author_id, body, created_at)`
- `activity_events(id, workspace_id, actor_id, action, target_type, target_id, created_at)`
- `sessions(id, user_id, token_hash, created_at, revoked)`

IDs: `secrets.token_hex(8)` opaque 16-char strings (≤64 contract limit).

## 4. Invariant enforcement

- **Last-admin invariant**: every membership removal/role-change is a single `BEGIN IMMEDIATE` transaction that (a) counts current ADMINs, (b) if count==1 and target is admin and new state loses admin → 409, else apply. Pairs of simultaneous requests serialize on the write transaction; the check-then-write is inside the transaction ⇒ race-safe.
- **Removal auto-unassign**: same transaction nulls `assignee_id` on all matching issues and writes `MEMBER_REMOVED` + one `MEMBER_ISSUES_UNASSIGNED` per issue atomically.
- **Archived-project read-only**: issue create/patch/delete and comment create return 409 when the owning project `archived=true`.
- **Tenant isolation**: every workspace-scoped resource load joins membership for the caller; missing membership → 404 (hides existence); member with insufficient role → 403; non-member → 404.
- **Mass-assignment**: Pydantic request models allow-list fields; `workspace_id`/`creator_id`/ids not writable client-side.

## 5. Test strategy

- **Unit** (`tests/test_unit_domain.py`, 22 tests): pure domain helpers — overdue rule boundary (past/today/future/null/resolved-closed/archived-project), issue-patch event selection (ISSUE_UPDATED / ISSUE_STATUS_CHANGED / ISSUE_ASSIGNED / ISSUE_UNASSIGNED / mixed), all 16 status transition pairs, input validators (boundary lengths, invalid enum, malformed date, oversized ID, null handling), pagination math, role-safe member-view fields, canonical 16-action vocabulary, UTC timestamp format.
- **Integration/API** (`tests/test_api_integration.py`, 34 tests): in-process ASGI `TestClient` against a fresh temp-DB app instance per test (`auto_seed=False`). Covers AUTH (register/login/logout/me/profile), WS (create/list/validation), MEM (add/role/last-admin invariant/email-hidden/removal/auto-unassign), PRJ (lifecycle/archived read-only), ISS (create/patch/16-transitions/filters/pagination/cross-workspace-isolation/delete), CMT (flow/archived-rejection), ACT (feed/vocab/isolation), DSH (counts/overdue-rule/isolation), TSEC (malformed JSON, error shapes, 404 hiding, 500 no-leak), and rate-limiting (429).
- **Browser E2E** (`tests/test_e2e_browser.py`): **Not in suite at RC.** Playwright/chromium is unavailable in the sandbox. The "E2E" label in the original plan is satisfied by the in-process ASGI tests above; no automated browser test is committed. This is documented in `KNOWN-LIMITATIONS.md` L-F3 and `TEST-EXECUTION-REPORT.md` §3.

## 6. Evidence artifacts (Milestone 5)

`evidence/ARCHITECTURE-DECISIONS.md` (this file), `evidence/CODE-REVIEW-DISPOSITION.md`, `evidence/SECURITY-AUDIT-REPORT.md`, `evidence/TRACEABILITY-MATRIX.md`, `evidence/TEST-EXECUTION-REPORT.md`, `evidence/RUNBOOK-CLEAN-START.md`, `evidence/KNOWN-LIMITATIONS.md`, `evidence/RELEASE-CANDIDATE-REPORT.md`.

## 7. Risks / open assumptions

- SQLite single-writer: acceptable for MVP scale; documented in KNOWN-LIMITATIONS (no multi-process write support; upgrade path Postgres noted).
- In-process rate limiter resets on process restart (documented in KNOWN-LIMITATIONS L-S1).
- No automated browser E2E tests committed; UI verified manually (documented in KNOWN-LIMITATIONS L-F3).
- No performance/load test committed (NFR-004); dashboard query shape is efficient but p95 not verified (documented in KNOWN-LIMITATIONS L-N1).
- `passlib` is listed in `evidence/pinned-deps.txt` but not installed by `requirements.txt` and not imported by any `app/` module (stale record; documented in KNOWN-LIMITATIONS L-S8).
