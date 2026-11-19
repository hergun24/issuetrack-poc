# Code Review Disposition Record — IssueTrack Lite (Release Candidate)

Date: 2026-11-19
Scope: `app/`, `run.py`, `tests/`, `static/`
Method: manual review + automated static analysis (`flake8` 7.5.0, `bandit` 1.9.4)

---

## 1. Automated lint results (flake8, max-line-length 120)

Command: `flake8 --max-line-length 120 app/ run.py tests/`

**Final result: 0 findings.** All findings below were remediated in-tree.

### Findings raised and fixed

| ID | Finding | Files | Disposition |
|----|---------|-------|-------------|
| LN-01 | `F811` redefinition of `ApiError`/`Detail` — duplicated `from .errors import` line | `app/__init__.py` | **FIXED** — removed duplicate import line |
| LN-02 | `F401` unused imports (`threading`, `Depends`, `BaseModel`, `list_activity`, `setup_logging`) | `app/api.py` | **FIXED** — pruned to used symbols |
| LN-03 | `E402`/`E305`/`E306` — import not at top of file; missing blank lines after the `_auth_limiter()` helper and before nested `def _bad()` | `app/api.py` | **FIXED** — imports hoisted, PEP8 blank-line spacing restored |
| LN-04 | `F821` undefined `Optional` and `revoke_session` (accidentally removed with LN-02 pruning) | `app/api.py` | **FIXED** — both re-added to the import block; verified by test suite |
| LN-05 | `E501` lines > 120 chars (3× in `patch_issue` enum-default ternaries) | `app/api.py` | **FIXED** — rewritten as explicit `if payload.x is not None:` blocks (also improves readability) |
| LN-06 | `E501` line > 120 chars (404/405 message ternary) | `app/main.py` | **FIXED** — hoisted into local `msg` variable |
| LN-07 | `F401` unused imports (`secrets`, `Optional`, `fastapi`, `Response`) | `app/main.py` | **FIXED** — pruned |
| LN-08 | `F401` unused `SlidingWindowLimiter as _lim` alias + `E306` before nested `_Passthrough` class | `app/main.py` | **FIXED** — single local import, class hoisted out of the `if` |
| LN-09 | `F401` unused `typing.Optional` | `app/db.py` | **FIXED** — pruned |
| LN-10 | `E302` missing 2 blank lines before `add_activity` | `app/domain.py` | **FIXED** |
| LN-11 | `E501` long INSERT SQL and long `COUNT(*)` SQL | `app/domain.py` | **FIXED** — string-if-concatenation wrap / argument wrap |
| LN-12 | `E302` missing 2 blank lines before `class SlidingWindowLimiter` | `app/ops.py` | **FIXED** |
| LN-13 | `E501` long `DB_PATH = os.environ.get(...)` one-liner | `app/seed.py`, `run.py` | **FIXED** — extracted `_HERE` constant |
| LN-14 | `E127` over-indented continuation | `tests/test_api_integration.py` | **FIXED** |
| LN-15 | `F841` unused locals `cid`, `iss3` | `tests/test_api_integration.py` | **FIXED** — removed dead assignments |
| LN-16 | `E501` > 120 char assert line (comments count) | `tests/test_api_integration.py` | **FIXED** — split into `got = ...` + assert |
| LN-17 | `F541` f-string without placeholders | `tests/test_api_integration.py` | **FIXED** — dropped redundant `f` prefix |
| LN-18 | `E401` multiple imports on one line (`import asyncio, json`) | `tests/test_api_integration.py` | **FIXED** — `json` added as a top-level import (it is genuinely used by `test_500_shape_never_leaks_details`) |
| LN-19 | `F401` unused `import app.api as api` | `tests/test_unit_domain.py` | **FIXED** — pruned |

### Residual / accepted (no action required)

* `# noqa: E402` comments in `app/seed.py` and `run.py` are intentional: those modules insert the repo root on `sys.path` before importing `app.*`, so the import cannot be at the very top of the file. Suppressed locally rather than globally.

---

## 2. Bandit security linter findings and dispositions

Command: `bandit -r app/ run.py -f txt`
**Totals: 5 findings — 0 HIGH, 4 MEDIUM, 1 LOW.**

| ID | Bandit finding | Location | Severity | Disposition |
|----|----------------|----------|----------|-------------|
| BD-01 | `B104:hardcoded_bind_all_interfaces` — binding to all interfaces | `run.py:19` | MEDIUM | **ACCEPTED (by contract)**. The task specification *requires* the service to listen on `0.0.0.0:8000`. Binding is to the container-scoped address only; no production deployment instructions are given. Recorded as a deployment note in `KNOWN-LIMITATIONS.md`. |
| BD-02 | `B608:hardcoded_sql_expressions` — f-string in `tx.execute()` | `app/api.py:678` | MEDIUM | **FALSE POSITIVE**. The interpolated text is a *column-name list* built as `", ".join(f"{c}=?" for c in updates)`. Keys come only from a hard-coded, developer-authored allow-list (`name`, `description`, `archived`, `updated_at`, `status`, `priority`, `type`, `due_date`, `assignee_id`); no user-controlled string ever reaches the identifier position. All *values* are bound via `?` placeholders. No injection vector. |
| BD-03 | `B608:hardcoded_sql_expressions` — f-string in `tx.execute()` | `app/api.py:475` | MEDIUM | **FALSE POSITIVE**. Same mechanism as BD-02, on the `projects` UPDATE path. Only allow-listed identifiers are interpolated; all values parameterised. |
| BD-04 | `B608:hardcoded_sql_expressions` — f-string in `conn.execute()` | `app/api.py:551` | MEDIUM | **FALSE POSITIVE**. The interpolated `{where_sql}` is assembled only from literal, developer-authored SQL fragments (`"i.workspace_id=?"`, `"AND i.status=?"`, …) each paired with a `?` and an appended parameter. Filter *values* are never interpolated into the SQL text. |
| BD-05 | `B101:assert_used` — `assert action in CANONICAL_ACTIONS` | `app/domain.py:114` | LOW | **RETAINED (design decision)**. This is a defensive invariant on an internal call path: the 16-action vocabulary is a closed set, and every caller passes a literal. It documents and protects the contract-internal invariant against future typos. It is *not* used for input validation — user-supplied values are validated separately in `validate_enum()`, which returns contract-shaped errors. Behaviour under `python -O` is that this internal invariant check is skipped; no security impact because no untrusted input reaches `add_activity` other than via validated enum paths. |

**No HIGH severity findings. No `#nosec` suppressions were used** — dispositions above are reasoned in this document rather than silenced inline.

---

## 3. Secrets scan results

Pattern scan (API keys, private keys, bearer tokens, assigned-credential literals) across `app/`, `static/`, `run.py`, `tests/`:

* **No hard-coded secrets found.** No private keys, no API keys, no bearer tokens.
* Password literals present in the repo are **demo seed credentials only** (`admin12345`, `member12345` in `app/seed.py`). They are required by the seeding specification and are only ever stored as bcrypt hashes (cost 12) — the plaintext exists solely to populate the demo dataset. This is documented in `RUNBOOK-CLEAN-START.md` and `KNOWN-LIMITATIONS.md`; they must be rotated/removed for any non-demo deployment.
* Tokens: `secrets.token_hex(32)` (256 bits of CSPRNG entropy) at issue time; only the SHA-256 hash is persisted (`app/security.py`). Raw tokens are never logged or stored.

---

## 4. Dependency audit (pip-audit)

Command: `python3 -m pip_audit -d`
Result: **`No known vulnerabilities found`** (104 packages considered).

Pinned runtime dependency set is recorded in `evidence/pinned-deps.txt`:

```
bcrypt 5.0.0 / fastapi 0.165.0 / httpx 0.28.1 / passlib 1.7.4 /
pydantic 2.14.3 / pydantic_core 2.50.4 / pytest 9.2.0 / starlette 1.10.0 /
uvicorn 0.54.0
```

Residual dependency risk: `passlib 1.7.4` is imported but effectively unmaintained upstream. It is **not on the security-critical path** in this codebase — `app/security.py` calls `bcrypt` directly (`hashpw`/`checkpw` with `gensalt(rounds=12)`). Recommendation in `KNOWN-LIMITATIONS.md`: drop the `passlib` import entirely to remove the unmaintained transitive dependency. Not done in this RC to keep the change surface minimal, since it carries no vulnerability.

---

## 5. Review summary

* Lint: **0 findings remaining** (all 19 findings remediated).
* Bandit: **0 HIGH**, 4 MEDIUM + 1 LOW, all reasoned — 0 accepted-without-rationale, 0 silenced with `#nosec`.
* Secrets scan: **clean** (only intentional demo seed credentials).
* Dependency scan: **clean**, no known vulnerabilities.
* Functional verification after remediation: **56/56 tests pass** (`python3 -m pytest tests/ -q`).

**Release-candidate code-review verdict: PASS (with the accepted items above tracked in `KNOWN-LIMITATIONS.md`).**
