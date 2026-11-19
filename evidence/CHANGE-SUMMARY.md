# CHANGE SUMMARY — Stage C: Strict `due_date` Validation

Date: 2026-11-19 (UTC) · Branch: `master` · Application: **IssueTrack Lite**

## Scope

Harden `due_date` validation on issue **create** and **update** so the field
accepts only `null` or a real Gregorian calendar date in the exact
`YYYY-MM-DD` format. No other API behavior or product scope was changed.

## Validation rules enforced

| # | Rule | Result |
|---|------|--------|
| 1 | Valid date-only values (`2028-02-29` leap day, `2026-05-15`) | Accepted, HTTP 201/200 |
| 2 | `null` | Accepted |
| 3 | Invalid layouts (`01-01-2030`, `2030/01/01`, `2030-1-1`) | Rejected, HTTP 422 `VALIDATION_ERROR` |
| 4 | Impossible calendar dates (`2027-02-29`, `2026-13-01`, `2026-04-31`) | Rejected, HTTP 422 |
| 5 | Timestamps (`2030-01-01T00:00:00Z`, `2026-11-20 12:00:00`) | Rejected, HTTP 422 |
| 6 | Past dates allowed; updates persist | Unchanged |
| 7 | Dashboard overdue rule (due-today NOT overdue, UTC) | Unchanged |
| 8 | No unrelated API changes | Confirmed |

## Code change (W-3)

`app/domain.py` — `validate_date_only()`:

- Precompiled module-level `_DATE_ONLY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")`
  used with `fullmatch`, replacing the inline per-call `re` import.
- `datetime.date.fromisoformat(value)` guards calendar validity
  (rejects `2027-02-29`, `2026-13-01`, `2026-04-31`).
- Explicit `isinstance(value, str)` check rejects non-string values and
  whitespace-padded strings (`" 2030-01-01 "`).
- Endpoints already routed through this validator (`app/api.py`
  `create_issue` line ~571, `update_issue` line ~661) — no endpoint edits
  were needed.

Dashboard `_overdue()` rule untouched: `due_date < utc_today()` strictly;
due-today is NOT overdue (verified in tests and against a live fresh-DB
server: `overdue_count == 1`, only the seeded past-due OPEN issue listed).

## Test evidence (W-1, committed in `c6a199c`)

- `tests/test_unit_domain.py` — 10 date-validation unit tests:
  leap-year accept/reject, layout rejects, timestamp rejects, impossible
  calendar dates, `null`, whitespace, non-string types, century bounds.
- `tests/test_api_integration.py` — end-to-end 422 coverage on
  `POST /workspaces/{id}/issues` and `PATCH /workspaces/{id}/issues/{id}`
  plus a dashboard regression test asserting the overdue rule.
- Full regression run: **64 passed, 0 failed** (`python -m pytest tests/ -q`,
  63.6 s).

## Live verification (W-4)

Against running servers (ports 42169 and 48542):

- All 13 due-date cases (valid/leap/null/3 bad layouts/3 impossible/
  2 timestamps/patch+GET persistence) returned the expected status codes.
- Fresh-DB dashboard check: `overdue_count == 1`, seed "Seeded Bug: login
  flake" (due yesterday, OPEN) in `overdue_issue_ids`; "Seeded today-due"
  (due today, OPEN) **not** in `overdue_issue_ids`.

## Commits

| SHA | Message |
|-----|---------|
| `c6a199c` | `test(stage-c): comprehensive due_date strict validation tests (W-1)` |
| `774cca8` | `feat(stage-c): strict Gregorian date-only due_date validator (W-3)` |
| (W-4) | `docs(stage-c): change summary with test + live verification evidence` |

## Release candidate status

All 8 validation rules verified; full regression green; no unrelated
behavior changes. Release candidate verified.
