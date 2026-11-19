# Functional Requirements and Acceptance Criteria
Version: 0.2.0 — normative. MUST/MUST NOT are binding.

Input limits, enum defaults, API conventions and error semantics referenced
below are defined in `06-API-CONTRACT-REFERENCE.md`. Every FR maps to at least
one automated external test or a documented manual check (see traceability in
the evaluation record).

## Authentication & profile

| ID | Requirement | Acceptance criteria |
|---|---|---|
| FR-001 | Register with valid email/password per contract limits. | AC-001: valid registration creates exactly one user; duplicate email rejected with a generic error and no duplicate account created. |
| FR-002 | Authenticate registered users via the contract login endpoint. | AC-002: valid credentials return a bearer token and user; invalid credentials and unknown email return the identical generic failure. |
| FR-003 | Logout invalidates the current session. | AC-003: the previously valid token cannot access protected resources after logout; other concurrent sessions of the same user remain valid. |
| FR-004 | User views own profile; edits own display name only. | AC-004: own profile is readable and display-name updates persist; a manipulated user ID cannot edit another user's profile. |

## Workspace & membership

| ID | Requirement | Acceptance criteria |
|---|---|---|
| FR-010 | Create workspace; creator becomes first Admin. | AC-010: exactly one initial ADMIN membership for the creator. |
| FR-011 | User may belong to multiple workspaces. | AC-011: switching workspace selection shows only the selected workspace's data. |
| FR-012 | Admin adds an existing registered user by email with a role. | AC-012: existing user added once with the given role; unknown email rejected generically and no account created. |
| FR-013 | Admin changes membership role (ADMIN↔MEMBER). | AC-013: the change takes effect on the affected user's next authorized request. |
| FR-014 | Admin removes a member, except the last Admin. | AC-014: normal removal succeeds; removing or demoting the last Admin is rejected and changes nothing, including under concurrent attempts. |
| FR-015 | Workspace data is restricted to current members. | AC-015: a non-member cannot read or mutate workspace, project, issue, comment, activity, or dashboard data via URL, API, or payload tampering. |
| FR-016 | Members list is visible with role-safe fields. | AC-016: Admin sees display name, email, role; Member sees display name and role without email. |
| FR-017 | Member removal auto-unassigns and audits. | AC-017: issues assigned to the removed member in that workspace have assignee null afterwards; removal and per-issue unassignment appear in activity. |
| FR-018 | Removal/role-change effects are immediate. | AC-018: a removed member is denied on their next request; a demoted Admin loses admin-only abilities on their next request; a promoted Member gains them. |

## Projects

| ID | Requirement | Acceptance criteria |
|---|---|---|
| FR-020 | Members list/view projects including archived ones. | AC-020: active and archived projects are listed with their archive state visible. |
| FR-021 | Members create projects in the selected workspace. | AC-021: project belongs to the selected workspace only. |
| FR-022 | Admin edits project metadata and archives. | AC-022: Admin succeeds; Member cannot edit metadata or archive. |
| FR-023 | Archived projects are read-only. | AC-023: project records, issues, and history stay readable; issue writes and comment creation are rejected. |
| FR-024 | Admin unarchives projects. | AC-024: Admin unarchive succeeds and restores writes; Member unarchive is denied. |
| FR-025 | Archived projects are excluded from dashboard aggregates. | AC-025: issues in archived projects count toward no dashboard total and never count as overdue. |

## Issues

| ID | Requirement | Acceptance criteria |
|---|---|---|
| FR-030 | Members create BUG/TASK issues in active projects. | AC-030: valid issue is created with defaults OPEN and MEDIUM. |
| FR-031 | Members view non-deleted issues of accessible workspace. | AC-031: list shows only non-deleted issues of the selected workspace; no cross-workspace rows. |
| FR-032 | Members update issue fields. | AC-032: valid updates persist; updated_at changes; activity records the update. |
| FR-033 | Assignee must be a current member of the issue's workspace. | AC-033: cross-workspace/non-member assignment is rejected; valid assignment and clearing (null) succeed. |
| FR-034 | Only Admin deletes issues. | AC-034: Member deletion denied; Admin deletion audited; deleted issue absent from list/detail/dashboard. |
| FR-035 | Due date is optional, date-only; past allowed. | AC-035: null due date is not overdue; a past due date on an open issue is overdue per the approved rule. |
| FR-036 | Issue list supports filters and pagination. | AC-036: status, priority, assignee, and overdue filters each return exactly the matching set; pagination envelope is correct and pages do not overlap. |
| FR-037 | Status transitions are free among the four statuses. | AC-037: any status may change to any status (16 ordered pairs), including CLOSED→OPEN and self-transitions. |
| FR-038 | Issue updates emit canonical activity events. | AC-038: status-only change → ISSUE_STATUS_CHANGED; assignee set/clear → ISSUE_ASSIGNED/ISSUE_UNASSIGNED; other field changes → ISSUE_UPDATED. |
| FR-039 | Deleted issues behave as absent. | AC-039: detail 404, absent from lists and every dashboard aggregate, commenting on them rejected, ISSUE_DELETED activity recorded. |

## Comments & activity

| ID | Requirement | Acceptance criteria |
|---|---|---|
| FR-040 | Members comment on non-deleted issues in active projects. | AC-040: comment author and timestamp are shown; comment on deleted issue or archived project rejected. |
| FR-041 | Material business actions are recorded. | AC-041: each action type in the product spec produces an activity event with actor, canonical action, target type/id, workspace, timestamp. |
| FR-042 | Activity is append-only via application interfaces. | AC-042: no user can edit or delete activity events through UI or API. |
| FR-043 | Activity is visible to current workspace members. | AC-043: members read the feed; non-members cannot, even by direct URL; feed is paginated newest-first. |
| FR-044 | Activity actions use the canonical vocabulary. | AC-044: emitted action names match exactly the contract's 16-name vocabulary. |

## Dashboard

| ID | Requirement | Acceptance criteria |
|---|---|---|
| FR-050 | Dashboard groups non-deleted, non-archived-project issue totals by status and by priority separately. | AC-050: a seeded dataset yields exact per-status and per-priority totals; deleted and archived-project issues excluded. |
| FR-051 | Dashboard shows overdue issues per the approved rule. | AC-051: overdue iff due_date < current UTC date AND status not RESOLVED/CLOSED AND not deleted AND project not archived; today is not overdue; boundaries hold at midnight UTC. |
| FR-052 | Dashboard is scoped to the selected workspace. | AC-052: switching selection changes all counts/lists; no cross-workspace data appears. |
| FR-053 | Dashboard overdue results are consistent with the overdue filter. | AC-053: the dashboard's overdue ids equal the issue list's overdue=true filter results for the same workspace. |

## Validation & UX

| ID | Requirement | Acceptance criteria |
|---|---|---|
| FR-060 | Server validates all inputs per contract limits. | AC-060: missing/oversized required fields, invalid enums, malformed dates and IDs are rejected with the contract validation error. |
| FR-061 | Errors are safe and understandable. | AC-061: no stack trace, secret, token, password hash, or internal configuration is ever exposed. |
| FR-062 | Primary flows are keyboard accessible. | AC-062: keyboard-only login, create issue, change status, comment; accessible labels and visible focus. |
