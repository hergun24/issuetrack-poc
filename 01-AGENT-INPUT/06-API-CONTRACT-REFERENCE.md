# API Contract Reference (Common REST/JSON Contract)
Version: 0.2.0 — normative for the external evaluation.

Your application MUST implement this exact HTTP/JSON API. The authoritative
machine-readable definition is OpenAPI 3.0.3 (identical content to this
document; it will be provided by the operator on request). All responses are
`application/json; charset=utf-8` unless the status is 204 (no body).

## Conventions
- **Base URL:** your server root; all paths below are relative to it.
- **Authentication:** `Authorization: Bearer <token>` on every endpoint except
  `/api/health`, register, and login. Obtain the token from login; logout
  invalidates it immediately (other sessions of the same user stay valid).
- **Workspace selection:** explicit path parameter — all workspace-scoped
  resources live under `/api/workspaces/{workspaceId}/...`.
- **IDs:** opaque strings (≤64 chars). Never assume a format.
- **Timestamps:** ISO-8601 UTC, second precision, `Z` suffix
  (`2026-11-15T07:30:00Z`).
- **Due dates:** date-only strings `YYYY-MM-DD` (or `null`). Not timestamps.
  Past dates are valid. Business timezone is UTC.
- **Enums:** issue type `BUG|TASK` (default `BUG` at creation); issue status
  `OPEN|IN_PROGRESS|RESOLVED|CLOSED` (default `OPEN`); priority
  `LOW|MEDIUM|HIGH|CRITICAL` (default `MEDIUM`); membership role
  `ADMIN|MEMBER`.
- **Input limits:** email ≤254 (case-insensitively unique, normalized to
  lowercase); password 8–128; display name 1–100; workspace name 1–100;
  project name 1–200; project/issue description ≤2000 / ≤5000; issue title
  1–200; comment body 1–2000.

## Error responses
Every error is `{"error": {"code": "<CODE>", "message": "<text>"}}`
(optional `details: [{field, reason}]` for validation).

| Status | Code | When |
|---|---|---|
| 400 | VALIDATION_ERROR | Malformed JSON body |
| 401 | UNAUTHENTICATED | Missing/invalid bearer token on a protected endpoint |
| 401 | AUTHENTICATION_FAILED | Login failure — identical body for unknown email and wrong password |
| 403 | FORBIDDEN | Authenticated member lacks the required role |
| 404 | NOT_FOUND | Unknown resource **or** resource of another workspace the caller is not a member of (existence is hidden) |
| 409 | CONFLICT | Last-Admin removal/demotion; write into archived project |
| 422 | VALIDATION_ERROR | Semantic validation failure (limits, enums, formats, relationships) |
| 500 | INTERNAL_ERROR | Unexpected failure (never leak details) |

## Pagination envelope
Lists (`issues`, `comments`, `activity`) use query parameters `page` (≥1,
default 1) and `page_size` (1–100, default 20) and respond:
`{"items": [...], "page": n, "page_size": n, "total_items": n, "total_pages": n}`.

## Endpoints

### Health
- `GET /api/health` → 200 `{"status":"ok"}` (no authentication; no other data).

### Authentication
- `POST /api/auth/register` `{email, password, display_name}` → 201 `{id, email, display_name}`.
  Duplicate email → generic 422 (no duplicate account created).
- `POST /api/auth/login` `{email, password}` → 200 `{token, user:{id,email,display_name}}`;
  failure → 401 AUTHENTICATION_FAILED (identical for unknown email / wrong password).
- `POST /api/auth/logout` (auth) → 204. The used token is invalid afterwards.

### Profile
- `GET /api/me` (auth) → 200 `{id, email, display_name}`.
- `PATCH /api/me` `{display_name}` → 200 user.

### Workspaces
- `GET /api/workspaces` (auth) → 200 `{items:[{id, name, role}]}` — workspaces
  the caller belongs to, with the caller's role. (Single page; not paginated.)
- `POST /api/workspaces` `{name}` → 201 `{id, name, role:"ADMIN"}` — creator is
  the first Admin.

### Members (workspace-scoped)
- `GET /api/workspaces/{wid}/members` → 200 `{items:[{user_id, display_name, role, email?}]}`.
  **Role-safe fields:** ADMIN requester also receives `email`; MEMBER
  requester does not.
- `POST /api/workspaces/{wid}/members` `{email, role}` (Admin) → 201 member
  view. Unknown email → generic 422 (no account created).
- `PATCH /api/workspaces/{wid}/members/{userId}` `{role}` (Admin) → 200.
  Demoting the last Admin → 409. Effective on the affected user's next request.
- `DELETE /api/workspaces/{wid}/members/{userId}` (Admin) → 204. The removed
  member's assigned issues in this workspace become unassigned; activity
  records MEMBER_REMOVED and one MEMBER_ISSUES_UNASSIGNED per affected issue.
  Removing the last Admin → 409.

### Projects
- `GET /api/workspaces/{wid}/projects` → 200 `{items:[Project]}` — includes
  archived projects, each with `archived` flag.
- `POST /api/workspaces/{wid}/projects` `{name, description?}` → 201 `Project`.
- `GET /api/workspaces/{wid}/projects/{pid}` → 200 `Project` (archived readable).
- `PATCH /api/workspaces/{wid}/projects/{pid}` `{name?, description?, archived?}`
  (Admin) → 200. `archived:true` makes the project read-only; `archived:false`
  unarchives. A project's `workspace_id` is immutable (supplying it is ignored
  or rejected; never changes).

`Project` = `{id, workspace_id, name, description, archived, created_at, updated_at}`.

### Issues
- `GET /api/workspaces/{wid}/issues?status=&priority=&assignee_id=&overdue=&page=&page_size=`
  → 200 page of non-deleted issues of this workspace. Filters: exact enum for
  status/priority; exact id for assignee; `overdue=true|false` selects issues
  that are/are not overdue **under the full approved overdue rule** (see
  Dashboard).
- `POST /api/workspaces/{wid}/issues`
  `{project_id, title, description?, type?, priority?, assignee_id?, due_date?}`
  → 201 `Issue`. The project must exist in this workspace and be active (else
  422/409). Assignee must be a current member of this workspace (else 422).
- `GET /api/workspaces/{wid}/issues/{iid}` → 200 `Issue` (non-deleted only).
- `PATCH /api/workspaces/{wid}/issues/{iid}`
  `{title?, description?, type?, status?, priority?, assignee_id?, due_date?}`
  → 200 `Issue`. **Any status may transition to any status** (16 ordered
  pairs, incl. CLOSED→OPEN). `assignee_id: null` clears the assignee. Issues
  in archived projects are read-only (409).
- `DELETE /api/workspaces/{wid}/issues/{iid}` (Admin) → 204. Audited
  (ISSUE_DELETED); deleted issues return 404 on detail, vanish from lists and
  dashboard totals, and reject comments.

`Issue` = `{id, workspace_id, project_id, title, description, type, status,
priority, assignee_id|null, due_date|null, creator_id, created_at, updated_at}`.

### Comments
- `GET /api/workspaces/{wid}/issues/{iid}/comments?page=&page_size=` → 200 page.
- `POST /api/workspaces/{wid}/issues/{iid}/comments` `{body}` → 201 `Comment`
  (member; issue non-deleted; project active — else 404/409). Comments are
  immutable in this MVP.

`Comment` = `{id, issue_id, author_id, body, created_at}`.

### Activity
- `GET /api/workspaces/{wid}/activity?page=&page_size=` → 200 page, newest
  first, current members only. No mutation endpoints exist.

`ActivityEvent` = `{id, workspace_id, actor_id, action, target_type,
target_id, created_at}` with `target_type` one of
`workspace|user|project|issue|comment`.

**Canonical action vocabulary (exact strings):**
`WORKSPACE_CREATED`, `MEMBER_ADDED`, `MEMBER_REMOVED`, `MEMBER_ROLE_CHANGED`,
`MEMBER_ISSUES_UNASSIGNED`, `PROJECT_CREATED`, `PROJECT_UPDATED`,
`PROJECT_ARCHIVED`, `PROJECT_UNARCHIVED`, `ISSUE_CREATED`, `ISSUE_UPDATED`,
`ISSUE_STATUS_CHANGED`, `ISSUE_ASSIGNED`, `ISSUE_UNASSIGNED`, `ISSUE_DELETED`,
`COMMENT_ADDED`.

Event selection rule: a status-only change emits `ISSUE_STATUS_CHANGED`; an
assignee-only change emits `ISSUE_ASSIGNED` (set) or `ISSUE_UNASSIGNED`
(clear); any other field change emits `ISSUE_UPDATED`.

### Dashboard
- `GET /api/workspaces/{wid}/dashboard` → 200:
```json
{
  "status_totals": {"OPEN":0,"IN_PROGRESS":0,"RESOLVED":0,"CLOSED":0},
  "priority_totals": {"LOW":0,"MEDIUM":0,"HIGH":0,"CRITICAL":0},
  "overdue_count": 0,
  "overdue_issue_ids": []
}
```
- Totals count non-deleted issues in non-archived projects of this workspace
  across **all four statuses** and **all four priorities** — two separate
  groupings, not a cross-tab.
- **Overdue rule:** an issue is overdue exactly when
  `due_date < current UTC date` AND status ∉ {RESOLVED, CLOSED} AND not
  deleted AND project not archived AND workspace matches. A due date **equal**
  to the current UTC date is not overdue. A null due date is never overdue.
  Compute "current UTC date" from UTC regardless of server process timezone.
