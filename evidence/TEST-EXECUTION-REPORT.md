# TEST-EXECUTION-REPORT.md

Application: **IssueTrack Lite** v0.2.0-rc1
Date: 2026-11-19 (UTC)
Test runner: `pytest` 9.2.0
Test directory: `/workspace/tests/`

---

## 1. Executive summary

| Metric | Value |
|---|---|
| Total tests in suite | **56** |
| Passed | **56** |
| Failed | **0** |
| Skipped | **0** |
| xfailed | **0** |
| xpassed | **0** |
| Errors | **0** |
| Wall-clock (cold, `python3 -m pytest -q`) | ~32 s |

**Verdict: 100 % pass. No skipped tests. No silently excluded test cases.**

## 2. Test inventory

### 2.1 `tests/test_unit_domain.py` — 22 tests

| Test class / function | Coverage area |
|---|---|
| `TestOverdueRule` (6 tests) | `app/domain.py` overdue predicate: past date is overdue; today's date is **not** overdue; RESOLVED/CLOSED never overdue regardless of date; null due date never overdue |
| `TestEventSelection` (5 tests) | `app/domain.py` canonical event selection: status-only change → `ISSUE_STATUS_CHANGED`; assignee-only (set) → `ISSUE_ASSIGNED`; assignee-only (clear) → `ISSUE_UNASSIGNED`; any other field → `ISSUE_UPDATED` |
| `TestAll16Transitions` (1 test, parameterised 16) | All 16 ordered status pairs including CLOSED→OPEN and all self-transitions |
| `TestValidators` (7 tests) | `app/domain.py` `validate_str`, `validate_enum`, `validate_date_only`, `validate_id_ref`: boundary lengths, invalid enum, malformed date, oversized ID, null handling |
| `test_pagination_math` | Page/page_size → total_pages boundary cases |
| `test_member_view_role_safe_fields` | Member view: ADMIN requester gets `email`; MEMBER requester does not |
| `test_canonical_vocabulary` | All 16 action names are emitted exactly once in the closed set |
| `test_timestamp_format` | `utcnow_iso()` produces `YYYY-MM-DDTHH:MM:SSZ` with no microseconds |

### 2.2 `tests/test_api_integration.py` — 34 tests

These use a `TestClient` (in-process ASGI) backed by a **fresh SQLite file** per test (fixture `env`), with `auto_seed=False` so no seed data leaks into assertions.

**Authentication and profile**

| Test | Requirement |
|---|---|
| `test_register_returns_user_only` | FR-001, AC-001 — valid registration; response contains only `{id, email, display_name}` |
| `test_register_semantic_validation` | FR-060 — oversized email, short password, oversized display_name each → 422 with contract-shaped `details` |
| `test_register_unique_email_case_insensitive` | FR-001, AC-001 — `Admin@Example.com` vs `admin@example.com` duplicate → 422, no second row |
| `test_malformed_json_body_400` | Contract — malformed JSON body → 400 `VALIDATION_ERROR` |
| `test_login_success_and_unknown_email` | FR-002, AC-002 — valid login → 200 `{token, user}`; unknown email → 401 `AUTHENTICATION_FAILED` |
| `test_login_wrong_password_same_body` | AC-002 — wrong-password body **identical** to unknown-email body (no user enumeration) |
| `test_login_rate_limit_429` | SEC-002 — 21st login attempt within 60 s → 429 |
| `test_logout_returns_204_and_blocks_reuse` | FR-003, AC-003 — logout → 204; reusing the token → 401 |
| `test_me_requires_auth` | SEC-010 — unauthenticated `GET /api/me` → 401 |
| `test_profile_update` | FR-004, AC-004 — display-name update persists; another user's ID cannot be patched |

**Workspaces and membership**

| Test | Requirement |
|---|---|
| `test_workspace_create_and_list` | FR-010, AC-010 — creator gets `role:ADMIN`; `GET /api/workspaces` lists it |
| `test_workspace_name_validation` | FR-060 — empty/oversized workspace name → 422 |
| `test_add_member_flow` | FR-012, AC-012 — admin adds existing user; unknown email → 422, no account created |
| `test_member_role_management` | FR-013, AC-013 — role change takes effect on the affected user's next request |
| `test_last_admin_invariant` | FR-014, AC-014, SEC-015 — removing/demoting the last admin → 409; workspace retains ≥1 admin |
| `test_member_email_hidden_from_non_admin` | FR-016, AC-016 — MEMBER requester's `GET /members` response contains no `email` field |
| `test_member_remove_flow` | FR-017, FR-018, AC-017/018 — removal → 204; removed member's next request → 401/403; unassign audit event present |
| `test_member_removal_unassigns_issues` | FR-017, AC-017 — issues assigned to removed member have `assignee_id=null` after removal |

**Projects**

| Test | Requirement |
|---|---|
| `test_project_lifecycle` | FR-020…FR-025 — create, list (archived visible), admin edit, archive read-only, unarchive restores writes; member cannot edit |

**Issues**

| Test | Requirement |
|---|---|
| `test_issue_create_and_get` | FR-030, AC-030 — defaults `OPEN`/`MEDIUM`; correct `Issue` shape |
| `test_issue_patch_events_and_rules` | FR-032, FR-037, FR-038 — valid updates; all 16 status pairs; correct event type per rule |
| `test_issue_list_filters_and_pagination` | FR-036, AC-036 — status/priority/assignee/overdue filters each return the matching set; pagination envelope correct, no page overlap |
| `test_issue_delete_tenant_scoped` | FR-034, AC-034, FR-039 — admin delete → 204, `ISSUE_DELETED` event; deleted issue 404 on detail; absent from lists/dashboard; comments rejected |
| `test_issue_cross_workspace_isolation` | FR-033, AC-033, SEC-012 — cross-workspace assignee rejected 422; cross-workspace issue URL → 404 |

**Comments and activity**

| Test | Requirement |
|---|---|
| `test_comments_flow` | FR-040, AC-040 — comment on active issue → 201 `Comment`; comment on archived project issue → 409; on deleted issue → 404 |
| `test_activity_flow` | FR-041, FR-043, FR-044 — activity feed newest-first, paginated; non-member denied; all events carry `actor_id`, `workspace_id`, `created_at` |
| `test_activity_vocab_all_sixteen` | FR-044, AC-044 — all 16 canonical action names appear in the feed after the full interaction sequence |

**Dashboard**

| Test | Requirement |
|---|---|
| `test_dashboard_counts_and_overdue_rule` | FR-050, FR-051 — exact per-status/per-priority totals; overdue set matches the `overdue=true` filter; today's date is **not** overdue; deleted/archived-project issues excluded |
| `test_dashboard_isolation` | FR-052, FR-053 — switching workspace changes all counts; non-member gets 404 on dashboard |

**Error shape and contract compliance**

| Test | Requirement |
|---|---|
| `test_unknown_endpoint_error_shape` | SEC-024 — 404 body is `{error:{code, message}}`; no stack trace |
| `test_method_not_allowed_shape` | SEC-024 — 405 body is contract-shaped |
| `test_unknown_resources_404` | SEC-010, SEC-011, SEC-012 — unknown workspace/project/issue IDs all → 404 (existence hidden for cross-tenant) |
| `test_500_shape_never_leaks_details` | SEC-024 — deliberately injected internal error returns 500 with generic message; the "secret-internal-value" string is absent from the body |

## 3. Honest skip accounting

| Category | Skipped? | Rationale |
|---|---|---|
| **Browser E2E** (Playwright / Selenium) | **Not in suite** — no automated browser tests committed | UI E2E is out of scope for this RC (see `KNOWN-LIMITATIONS.md` L-F3). The "E2E" tests in `test_api_integration.py` are **in-process ASGI** tests via FastAPI `TestClient`, not browser tests. |
| **Load / performance** (NFR-004, p95 ≤ 2 s for 5,000 issues) | **Not in suite** | No benchmark harness built. Listed in `KNOWN-LIMITATIONS.md` L-N1. |
| **Process-restart persistence** (NFR-009) | **Manual check only** | RUNBOOK §9 documents the manual create→kill→restart→read sequence. No automated test for process-restart persistence. Listed in `KNOWN-LIMITATIONS.md` L-N3. |
| **Keyboard accessibility** (FR-062, NFR-003) | **Manual check only** | Keyboard operation verified manually; no automated keyboard-journey test. Listed in `KNOWN-LIMITATIONS.md` L-F1. |
| **Viewport screenshots** (NFR-001) | **Visual check only** | No automated screenshot test. Listed in `KNOWN-LIMITATIONS.md` L-F2. |
| **Timezone-invariance** (NFR-005) | **Covered** | `test_dashboard_counts_and_overdue_rule` asserts the UTC-date boundary. The test does **not** explicitly set a non-UTC `TZ` for the process; the invariant is enforced by `app/domain.py` always using `datetime.now(timezone.utc)` and `utcnow_iso()` — not tested under a non-UTC process timezone. |

No test in the suite uses `@pytest.mark.skip`, `pytest.skip()`, or `xfail`.
The 0-skip count in the summary is accurate.

## 4. Test isolation and environment notes

- Each test in `test_api_integration.py` receives a **fresh** `env` fixture
  (a new `TestClient` and a new SQLite file under a temporary directory).
  No test depends on another test's state.
- `tests/conftest.py` calls `create_app(db_path, auto_seed=False)` so seed
  data is never present in test databases. This is a deliberate design
  choice (L-P3 in `KNOWN-LIMITATIONS.md`): tests validate application
  behaviour in isolation; the production path (`run.py` → `create_app()`
  with `auto_seed=True`) is validated separately in the RUNBOOK smoke check.
- Rate-limit test (`test_login_rate_limit_429`) uses a dedicated `client`
  with `disable_ratelimit=False` and asserts that the 21st request in 60 s
  returns 429; all other tests use `disable_ratelimit=True` so they are not
  affected by the in-process limiter's state.

## 5. Reproduction

```bash
cd /workspace
python3 -m pytest -q
# 56 passed in ~32 s
```

For a verbose per-test listing:

```bash
python3 -m pytest -v
```
