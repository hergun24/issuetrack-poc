# Incident Hotfix Disposition — INC-8492

| Field | Value |
|-------|-------|
| **Incident** | INC-8492 (HIGH PRIORITY) |
| **Component** | Backend API — Issue Due Date / Overdue Logic (`app/api.py`) |
| **Reported** | 2026-11-19 (UTC) |
| **Disposition date** | 2026-11-19 (UTC) |
| **Status** | **RESOLVED — hotfix applied, verified, zero regression** |
| **Changed file** | `app/api.py` (single function: `_overdue`) |
| **New test file** | `tests/test_inc8492.py` |

---

## 1. Triage Findings

**Symptom.** Users reported that on the production workspace dashboard the
"overdue" summary count is inconsistent with the issue list view when the
`overdue=true` filter is applied. Issues whose due date is set to **today's
date (UTC)** are incorrectly flagged as overdue in some views.

**Affected surfaces.** Both read paths consume the single pure helper
`_overdue()` in `app/api.py`:

- `GET /api/workspaces/{wid}/dashboard` → `overdue_count` / `overdue_issue_ids`
- `GET /api/workspaces/{wid}/issues?overdue=true|false` (issue list filter, AC-036)

Because both surfaces call the *same* helper, any boundary bug in that helper
shows up identically on both — which is exactly the "inconsistent with the
issue list view" symptom the users observed across views/times.

**Reproduction (pre-fix, on a fresh test DB).** Created one issue due *yesterday*
(UTC) and one issue due *today* (UTC), both `OPEN` in an active project:

```
$ python -m pytest tests/test_inc8492.py -q   # BEFORE hotfix
FAILED tests/test_inc8492.py::test_issue_due_today_is_not_overdue
AssertionError: Defect reproduced: issue due today is incorrectly flagged overdue
    _overdue('2026-11-19', 'OPEN', False) returned True   # expected False
2 failed, ...
```

Dashboard `overdue_count` came back as **2** instead of **1** — the today-due
issue was wrongly counted as overdue, producing the metric/filter discrepancy.

---

## 2. Root Cause Analysis

**Location.** `app/api.py`, function `_overdue()` (line ~507 pre-fix).

**Spec (normative).** Per `01-PRODUCT-SPEC.md` §"Date and overdue rules" and
`02-REQUIREMENTS-AND-AC.md` AC-051 / AC-035 / AC-053:

> An issue is overdue **exactly when**:
> `due_date < current UTC date` AND status not RESOLVED/CLOSED AND not deleted
> AND project not archived.
> A due date **equal** to the current UTC date is **not** overdue.
> (Boundaries must hold at UTC midnight.)

**Defect.** The implementation used an **inclusive** comparison:

```python
return due_date <= utc_today()
```

`utc_today()` returns the current UTC date as an ISO `YYYY-MM-DD` string;
`due_date` is stored as the same string format, so this is a correct
lexicographic date comparison. The only error is the operator: `<=` treats a
due date **equal to today** as overdue, which violates the spec on the
boundary. Every non-boundary case (past / future dates) behaves correctly,
so the bug is silent until an issue's due date lands on "today" — matching
the intermittent, date-dependent symptom in production.

**Why it's surgical.** `_overdue` is the single source of truth for the
overdue rule (used by dashboard and the `overdue=` filter), so fixing the
operator there corrects *all* affected views at once. No SQL, schema, or
other endpoint changes are required.

---

## 3. Hotfix (Surgical, Minimal)

**File:** `app/api.py` — inside `_overdue()` only.

**Diff (git):**

```diff
diff --git a/app/api.py b/app/api.py
index 4f42b59..0b9947f 100644
--- a/app/api.py
+++ b/app/api.py
@@ -512,7 +512,9 @@ def _overdue(due_date, status, project_archived) -> bool:
         return False
     if project_archived:
         return False
-    return due_date <= utc_today()
+    # Overdue iff due date is strictly before today in UTC: a due date equal
+    # to today's UTC date is not overdue until UTC midnight passes.
+    return due_date < utc_today()
```

- Removed the off-by-one on the boundary (`<=` → `<`).
- Added a two-line comment recording the "until UTC midnight passes" intent so
  the rule is self-documenting at the point of decision.
- **No other lines changed** in `app/api.py`. CRLF line endings preserved
  (verified via `git diff | cat -A`: diff is exactly 3 added / 1 removed
  content lines, no whitespace noise).

**Behavior after fix:**
- `due_date < today` and status not RESOLVED/CLOSED, project active, not deleted → **overdue**
- `due_date == today` (same UTC date) → **NOT overdue** (correct; flips only at UTC midnight)
- `due_date > today` → **NOT overdue**
- `due_date is None` / RESOLVED / CLOSED / archived project / deleted → **NOT overdue**

---

## 4. Test Evidence

### 4.1 Targeted reproduction tests (`tests/test_inc8492.py`)

| Test | Before hotfix | After hotfix |
|------|:---:|:---:|
| `test_issue_due_today_is_not_overdue` | **FAILED** | PASSED |
| `test_dashboard_and_filter_consistency_today_due` (AC-053) | **FAILED** (count=2 vs expected 1; filter/dashboard mismatch) | PASSED |

The consistency test asserts that for a workspace with one past-due issue and
one today-due issue:
- `GET /dashboard` → `overdue_count == 1`
- `GET /issues?overdue=true` → returns exactly that same 1 issue
- dashboard `overdue_issue_ids` == filter result ids (AC-053 invariant)

### 4.2 Full regression suite

```
$ python -m pytest tests/ -q
..........................................................               [100%]
58 passed, 1 warning in 40.40s
```

**All 58 tests pass. Zero regression.** This includes the pre-existing
overdue-rule unit tests (`tests/test_unit_domain.py::TestOverdueRule`,
including `test_today_due_is_not_overdue`) and the dashboard integration test
(`tests/test_api_integration.py::test_dashboard_counts_and_overdue_rule`).

> Note on the warning: one `StarletteDeprecationWarning` about httpx/
> httpx2 in `TestClient` — a pre-existing, unrelated dependency notice,
> not a test failure.

---

## 5. Verification & Close

- ✅ Root cause identified (off-by-one at the `<=` boundary in `_overdue`)
- ✅ Defect reproduced with failing tests pre-fix
- ✅ Surgical one-line hotfix applied (operator fix + comment only)
- ✅ Targeted tests pass post-fix
- ✅ Full suite: **58/58 passed, 0 failed**
- ✅ No other files or logic touched; no data/schema migration needed

**Conclusion.** The hotfix is **verified and clean**. `issues due today
(UTC)` are no longer flagged overdue; they become overdue only once UTC
midnight passes, satisfying AC-035 / AC-051 / AC-053. The dashboard summary
and the `overdue=` issue-list filter are now consistent on the boundary.
No follow-up actions required.

**Release note.** Ship the `app/api.py` change as a patch; no user-facing
config or migration. Deploy and confirm via the dashboard "overdue" count
matching the `overdue=true` filter for any workspace whose open issues include
due dates equal to the current UTC date.
