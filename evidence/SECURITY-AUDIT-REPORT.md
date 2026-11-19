# Security Audit Report — IssueTrack Lite (Release Candidate)

Date: 2026-11-19
Audited artefacts: `app/`, `static/`, `run.py`, `tests/`, dependency set
Inputs: `03-SECURITY-AND-NFR.md`, `04-TECHNICAL-CONSTRAINTS.md`

---

## 1. Audit scope and method

1. Static analysis: `bandit` 1.9.4 over `app/` + `run.py` (raw report: `evidence/bandit-report.txt`).
2. Lint: `flake8` 7.5.0 (report: `evidence/lint-report.txt`) — 0 findings after remediation.
3. Secrets scan: pattern-based scan of all source for key/credential literals (method documented in `CODE-REVIEW-DISPOSITION.md` §3).
4. Dependency audit: `pip-audit` over the installed environment (104 packages).
5. Manual review against `03-SECURITY-AND-NFR.md` controls (auth, tenancy, invariants, abuse control).

---

## 2. Findings and dispositions (bandit)

5 total: **0 HIGH, 4 MEDIUM, 1 LOW**. Full rationales in `CODE-REVIEW-DISPOSITION.md` §2:

| ID | Bandit | Location | Severity | Disposition |
|----|--------|----------|----------|-------------|
| BD-01 | B104 bind-to-all-interfaces | `run.py:19` | MEDIUM | **Accepted** — `0.0.0.0:8000` is a *normative* contract requirement. Deployment note recorded. |
| BD-02 | B608 dynamic SQL | `app/api.py:678` | MEDIUM | **False positive** — interpolated identifiers are hard-coded allow-lists; values parameterised. |
| BD-03 | B608 dynamic SQL | `app/api.py:475` | MEDIUM | **False positive** — same mechanism (projects UPDATE). |
| BD-04 | B608 dynamic SQL | `app/api.py:551` | MEDIUM | **False positive** — WHERE fragments are literal SQL; filter values bound via `?`. |
| BD-05 | B101 assert | `app/domain.py:114` | LOW | **Retained** — internal closed-set invariant (16-action vocabulary), not user-input validation. |

**Conclusion: no exploitable SQL-injection vector** (all queries parameterise user data; see also §4).

---

## 3. Secrets audit

| Check | Result |
|-------|--------|
| Hard-coded API keys / bearer tokens / private keys in source | **None found** |
| Plaintext passwords at rest | **None.** All user passwords stored as `bcrypt` hashes, cost 12 (`app/security.py`). |
| Session tokens at rest | **Hashed.** Opaque token (`secrets.token_hex(32)`, 256-bit CSPRNG) — only the SHA-256 hash is persisted. Raw token never stored, logged, or echoed in error bodies. |
| Demo seed credentials (`admin12345`, `member12345` in `app/seed.py`) | **Known and intentional** — required by the seeding spec. Documented; **must be rotated/removed for non-demo deployment** (see `KNOWN-LIMITATIONS.md`). |
| Secrets in `static/` UI code | **None.** UI communicates with the API via `Authorization: Bearer <token>` only. |
| Logging of sensitive data | `setup_logging()` in `app/ops.py` logs events without credential fields; the 500 handler returns a fixed generic body and never echoes exception text (`test_500_shape_never_leaks_details` verifies the "secret-internal-value" probe is absent). |

---

## 4. Authentication / authorisation review

| Control | Evidence |
|---------|----------|
| Password storage | `hash_password()` → bcrypt cost 12; `verify_password()` → `checkpw`. Constant-length compare for token hashes via `hmac.compare_digest`. |
| Session model | Opaque bearer tokens (256-bit CSPRNG), SHA-256-hashed at rest, revocable per-session via `POST /api/auth/logout`. No JWT / no client-side decoding. No TTL — tokens remain valid until explicitly revoked (documented residual risk in KNOWN-LIMITATIONS L-S2). |
| Abuse control (SEC-002) | Per-key sliding-window limiter (20 events / 60 s) on `POST /api/register` and `POST /api/login`, keyed by client address. **Per-app instance** stored on `app.state` (not a shared module global) so multi-app test processes do not share state — verified by `test_login_rate_limit_429`. |
| Tenant isolation | Every issue/project/comment/activity query is scoped by `workspace_id`; membership enforced via `is_member()`; cross-workspace access returns 404 (verified by `test_unknown_resources_404` and integration tests). |
| Last-admin invariant | Deletion/demotion paths check `admin_count()`; the last admin cannot be removed or demoted (integration coverage: `test_members`/invariant tests). |
| CORS | Explicit origin allow-list (`_CORS_ORIGINS` in `app/main.py`), **no wildcard**, `allow_credentials=False`, method-allow-listed. |
| Error leakage | Contract error shape `{error:{code,message,details?}}`; 500 returns a fixed generic message — internals never leak (`test_500_shape_never_leaks_details`). |
| SQL injection | All user data goes through `?` placeholders. The three f-string query sites are identifier/fragment interpolation only (allow-lists / literal fragments) — see §2. |
| Input validation | `validate_str/validate_enum/validate_date_only/validate_id_ref` with contract-shaped 422s; `RequestValidationError` handler normalises FastAPI/pydantic 422 bodies to the contract shape. |

---

## 5. Dependency audit

`pip-audit`: **No known vulnerabilities found** (104 packages). Pinned versions in `evidence/pinned-deps.txt`.

Residual notes:
* `passlib 1.7.4` (unmaintained upstream) is imported but **not on the security-critical path** — `app/security.py` uses `bcrypt` directly. Recommend dropping the import post-RC (tracked in `KNOWN-LIMITATIONS.md`).
* `fastapi 0.165.0` / `starlette 1.10.0` emit a `StarletteDeprecationWarning` about `httpx` TestClient under test only; no runtime impact, no known CVE.

---

## 6. Accepted risks / deployment notes

1. **B104 / 0.0.0.0 binding** — required by the contract for this sandbox. For any deployment outside a network-isolated container, put the service behind a TLS-terminating reverse proxy and bind to the loopback interface of that host.
2. **In-memory rate-limiter state** resets on process restart (documented MVP limitation; not a security bypass, it weakens abuse control only after restart).
3. **Demo seed credentials** — rotate or delete before any non-demo use.
4. **SQLite WAL file** (`data/issuetrack.db*`) must be excluded from any filesystem-level backup that crosses trust boundaries; treat it as credential material (it contains password/token hashes).

---

## 7. Verdict

**PASS** — no HIGH-severity findings, no secrets in source, no vulnerable dependencies, all 56 tests green after remediation. Accepted items are contract-mandated (0.0.0.0) or low-residual-risk (asserts on a closed-set invariant), and are tracked in `KNOWN-LIMITATIONS.md` / `CODE-REVIEW-DISPOSITION.md`.
