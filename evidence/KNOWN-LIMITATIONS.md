# KNOWN-LIMITATIONS.md

Application: **IssueTrack Lite** v0.2.0-rc1
Scope: honest record of residual risks, known gaps, and out-of-scope items
as of RC. No scope was silently reduced.

---

## A. Security — residual risk and documented gaps

| ID | Item | Status / disposition |
|---|---|---|
| L-S1 | Rate limiting (SEC-002 "abuse controls") is a **per-process in-memory sliding window** (`app/ops.py:SlidingWindowLimiter`), keyed by `client_ip:action`. It is **not** a load-distributed or Redis-backed limiter; it resets on process restart and does not coordinate across multiple worker processes. The RC ships a **single** uvicorn worker, so it is functional for this deployment. If scaled horizontally the limiter would silently weaken. | Accepted for MVP; documented; no multi-worker scaling is in scope. |
| L-S2 | Bearer tokens are **stateless opaque random strings** (`secrets.token_hex(32)`), stored only as a SHA-256 hash in `sessions.token_hash`. There is no expiry field, no sliding refresh, and no revocation list beyond logout (which flips `revoked=1` for that specific token). A token leaked in transit or logs can be used until its session row is revoked. The contract specifies "logout invalidates the used token" but says nothing about TTL. | Documented as residual risk per SEC-004; no TTL in the normative contract. |
| L-S3 | No account-level **login lockout** exists; only the rate limiter (L-S1) caps the number of attempts per client IP / 60 s. Brute-force from a single distributed source is not mitigated beyond that. | Accepted for MVP. |
| L-S4 | **No CSRF token** is issued because the external contract is bearer-token auth (SEC-023). If the internal UI were ever reworked to cookie-session auth, a CSRF token would be required. The current UI uses in-memory bearer storage (`localStorage` is not used), so there is no cookie-authenticated state-changing path. | Documented; N/A under the current auth model. |
| L-S5 | **CORS allow-list** (`app/main.py:_CORS_ORIGINS`) contains `http://0.0.0.0:8000` and `http://127.0.0.1:8000` — entries that some browsers **reject** as invalid origins and will not send in `Origin` headers. They exist for operator tooling / local dev convenience and are a no-op from a browser's perspective. In production, the allow-list should be reduced to the actual deployment origins. | Known; not exploitable because `allow_credentials=False`. |
| L-S6 | **Bandit** reports 3× `B608` (hardcoded SQL expressions) at `app/api.py:475,551,678`. All three are **false positives** in the sense that the interpolated fragments are built from validated, allow-listed column names or constant WHERE-clause fragments — user-supplied **values** are always bound via `?` placeholders. However, the code pattern is worth re-reviewing if the column-name allow-list ever changes. See `evidence/SECURITY-AUDIT-REPORT.md` for the full review. | False positive; documented and tracked. |
| L-S7 | **Bandit** reports 1× `B101` (assert used) at `app/domain.py:114`. That is the test-only helper `add_activity` path; it is not reachable from the API handler chain. | False positive; not a production path. |
| L-S8 | `passlib` is listed in `evidence/pinned-deps.txt` but is **not imported** anywhere in `app/`. It was used in an earlier iteration; the RC uses `bcrypt` directly. The extra entry in the pinned list is a stale artifact; it is not installed by `requirements.txt`. | Stale record; no runtime impact. |

## B. Non-functional / performance

| ID | Item | Status |
|---|---|---|
| L-N1 | **NFR-004** (dashboard p95 ≤ 2 s for 5,000 issues) has **no automated benchmark test** in the RC. The dashboard aggregates are two `COUNT(*) GROUP BY` queries and an `EXISTS` subquery on `issues` + `projects`, both indexed. No load test was run. | Not verified; listed as open performance check. |
| L-N2 | **WAL file** (`data/issuetrack.db-wal`, `-shm`): on abnormal process exit the WAL file may remain on disk. It is recovered automatically on the next connection. If the disk is full during a write, the DB file is not left corrupted (WAL guarantees this), but the `-wal` file will appear to be empty / partially written until the next clean connection. | Documented SQLite behaviour; no action required. |
| L-N3 | **NFR-009** (persistence across restart) is verified by the RUNBOOK smoke check, but the test suite does not include a dedicated "create → kill → restart → read" integration test. The data layer (`sqlite3`) is the standard library; no test harness for process restart was built. | Manual check only; documented in RUNBOOK §9. |
| L-N4 | The app runs a **single worker** uvicorn process. There is no horizontal scaling, no load-balancer configuration, and no gunicorn multi-worker path documented. | Single-worker by design for MVP. |

## C. Functional / UX

| ID | Item | Status |
|---|---|---|
| L-F1 | **FR-062 / NFR-003** (keyboard accessibility): the UI is built with semantic HTML and ARIA labels; keyboard operation was verified manually (Tab/Enter/Space). No automated keyboard-journey test was committed. | Manual verification only; no E2E keyboard test. |
| L-F2 | **NFR-001** (responsive at 375 px and 1280 px): the layout uses CSS media queries and flexbox. No automated viewport-screenshot test was committed. | Visual check only. |
| L-F3 | The UI is a **single-page vanilla-JS app** served from `/` and `/app.js`. There is no frontend framework, no build step, and no separate frontend test harness. The "E2E" tests in `tests/test_api_integration.py` are **in-process ASGI** tests (FastAPI `TestClient`), not browser E2E tests. True browser E2E (Playwright/Selenium) is **out of scope** for this RC. | Documented as a test-methodology limitation. |
| L-F4 | **Comment editing/deletion** is explicitly out of scope per the product spec ("Comments cannot be edited or deleted in this MVP"). No code path exists for it. | By design. |
| L-F5 | **Backup / restore** is listed as out of scope. No automated backup mechanism exists. | By design. |
| L-F6 | **Email-based user lookup** (`POST /api/workspaces/{wid}/members`) rejects unknown emails with a generic 422 (no account created, per AC-012). This is the contract-specified behaviour; it means the admin cannot discover *why* a user was not found. | By contract. |

## D. Process / governance

| ID | Item | Status |
|---|---|---|
| L-P1 | The repository has **zero git commits** at RC. All source is on the working tree. The runbook is written for a clean environment from source, not from a tagged release artifact. | No tag or artifact built; documented. |
| L-P2 | `evidence/lint-report.txt` is **empty** because `flake8` with `--max-line-length=120` reports zero issues across `app/`, `tests/`, and `run.py`. This is an accurate clean result, not a missing file. | No action required. |
| L-P3 | `app/main.py` auto-seeds via `create_app(auto_seed=True)` by default. The **test** path (`tests/conftest.py`) passes `auto_seed=False` explicitly, so tests never depend on seed data. The `run.py` path (`auto_seed=True` by default) is the documented production path. This separation is by design but is a **non-obvious coupling** that future maintainers should be aware of. | Documented; see `conftest.py`. |

## E. Contract deviations / open items

None. All normative requirements in `01-PRODUCT-SPEC.md`,
`02-REQUIREMENTS-AND-AC.md`, `03-SECURITY-AND-NFR.md`, and
`06-API-CONTRACT-REFERENCE.md` that are in scope for this MVP are implemented
and covered by at least one automated test. The items above are **known
limitations of the RC build**, not contract violations.

## F. What this file does **not** cover

- Performance under production load.
- Multi-region / multi-DB deployment.
- CI/CD pipeline, container packaging, or artifact signing.
- Accessibility WCAG conformance beyond keyboard and ARIA basics.
