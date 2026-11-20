# CHANGE SUMMARY — Issue #1: Enforce Minimum Length & Whitespace Trimming on Issue Title

Date: 2026-11-20 (UTC) · Branch: `feat/issue-1-title-validation` · Application: **IssueTrack Lite**

## Scope

Enforce a minimum issue-title length (3 non-whitespace characters after
stripping leading/trailing whitespace) on issue **create** and **update** so
that tasks cannot be accidentally created with single-character typos or
whitespace-only strings. No other API behavior or product scope was changed.

## Validation rules enforced

| # | Rule | Result |
|---|------|--------|
| 1 | Valid titles (e.g. `Fix login bug`, `API`, `abc`) | Accepted, HTTP 201 (create) / 200 (update) |
| 2 | Empty title (`""`) | Rejected, HTTP 422 `VALIDATION_ERROR` |
| 3 | Whitespace-only title (`"   "`) | Rejected, HTTP 422 `VALIDATION_ERROR` |
| 4 | Title with < 3 characters (`"ab"`) | Rejected, HTTP 422 `VALIDATION_ERROR` |
| 5 | Padded short title (`"  x  "`) | Rejected, HTTP 422 `VALIDATION_ERROR` (leading/trailing whitespace also rejected per existing `validate_str` non-blank rule) |
| 6 | Titles >= 3 chars continue to be accepted | Unchanged behavior preserved |

Endpoints affected:

- `POST /api/workspaces/{workspace_id}/issues`
- `PATCH /api/workspaces/{workspace_id}/issues/{issue_id}`

## Code change

`app/api.py` — minimum-length rule for the `title` field:

- New module-level constant `MIN_ISSUE_TITLE = 3` (next to the existing
  `MAX_ISSUE_TITLE = 200`), so the threshold is explicit and reusable.
- `create_issue`: the `title` validation call was widened from
  `validate_str(payload.title, "title", 1, MAX_ISSUE_TITLE)` to
  `validate_str(payload.title, "title", MIN_ISSUE_TITLE, MAX_ISSUE_TITLE)`.
- `patch_issue`: same widening for the PATCH path, so updates are held to the
  same rule as creates.

The actual enforcement already lives in the shared domain helper
`app/domain.py::validate_str(value, field, min_len, max_len, ...)`, which:

- rejects leading/trailing whitespace (`value != value.strip()`),
- rejects blank/whitespace-only values (`value.strip() == ""`),
- enforces `min_len <= len(value) <= max_len`.

Because the endpoint code already routed through `validate_str`, the only
change needed was widening the `min_len` argument from `1` to `3` (via the
named `MIN_ISSUE_TITLE` constant) at both call sites — no changes to
`app/domain.py`, `app/schemas.py`, or any DB layer were required.

## Test evidence

- `tests/test_unit_domain.py` — new
  `TestValidators::test_issue_title_min_length_rule`: asserts
  `MIN_ISSUE_TITLE == 3`; valid titles (`Fix login bug`, `API`, `abc`) pass
  `validate_str` with the new bounds; `""`, `"   "`, `"ab"`, `"  x  "` are
  all rejected with `Validation`.
- `tests/test_api_integration.py` — new
  `test_issue_title_min_length_validation`: end-to-end coverage over both
  affected endpoints, verifying HTTP 201/200 acceptance for valid titles and
  HTTP 422 `VALIDATION_ERROR` for each rejected case, plus confirmation that
  a rejected PATCH leaves the original title unchanged.
- Existing tests in `tests/test_api_integration.py` that happened to use
  sub-3-character placeholder titles (`"x"`, `"t"`, `"t2"`) in unrelated
  assertions (archived-project 409 check, default-field checks, unknown-project
  404 check, bad-`due_date`/`type`/`priority` 422 checks, past-date 201 check,
  activity-vocabulary test, strict `due_date` test) were updated to valid
  >=3-character titles (`"arched-write"`, `"tst"`, `"new-title"`) so those
  tests exercise exactly the fields they were written to test, without being
  short-circuited by the new title rule. No test assertions about the
  *tested fields* were weakened.
- Full regression run: **66 passed, 0 failed**
  (`python -m pytest tests/ -q`).

## Commits

| SHA | Message |
|-----|---------|
| (this PR) | `feat(issue-1): enforce minimum issue title length of 3 non-whitespace chars` |

## Release candidate status

All 6 validation rules verified at the unit and API-integration level; full
regression suite green (66/66); no unrelated behavior changes.
