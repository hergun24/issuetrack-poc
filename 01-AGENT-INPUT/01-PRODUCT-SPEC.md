# IssueTrack Lite — Product Specification
Version: 0.2.0

## Vision
IssueTrack Lite is a small-team web app to record, assign, discuss, track, and
resolve project issues (Bugs and Tasks). It exercises authentication, tenant
isolation, authorization, CRUD, state transitions, auditability, dashboard
aggregation, testing, and operational readiness without enterprise extras.

## Users and concepts
- **User:** authenticated identity; may belong to multiple workspaces.
- **Workspace:** tenant boundary.
- **Membership:** user/workspace association with role ADMIN or MEMBER, scoped to that workspace.
- **Workspace Admin:** manages members and projects and can perform normal issue work.
- **Workspace Member:** works on projects, creates/updates issues, assigns issues to eligible members, comments, views workspace information.
- **Project:** belongs to exactly one workspace; cannot move between workspaces.
- **Issue:** belongs to exactly one project; type BUG or TASK.
- **Comment:** user-authored message attached to an issue; cannot be edited or deleted in this MVP.
- **Activity event:** append-only record of a material business action.

## MVP capabilities

### Authentication/profile
Register with email/password, login/logout, view and update own display name.
Password reset, social login, MFA, and email verification are excluded.

### Workspace/membership
An authenticated user can create a workspace and becomes its first Admin.
Admin can add an already-registered user by email and assign a role
(ADMIN or MEMBER). Unknown email is rejected; no account is silently created.
A user may belong to multiple workspaces.

**Membership rules (normative):**
- Removing a member automatically unassigns all issues assigned to that member
  in that workspace (assignee becomes null). The removal and each resulting
  unassignment are recorded in the activity history.
- Role changes take effect on the next authorized request of the affected user.
- A removed or demoted user loses the corresponding access on their next request.
- The last Admin of a workspace cannot be removed or demoted unless another
  Admin has already been established; this protection must hold under
  concurrent requests — no race may leave a workspace without an Admin.

### Projects
Members can list, view, and create projects. Admins can edit project metadata
and archive/unarchive projects.
**Project rules (normative):**
- Archived projects remain readable (project and its issues/history).
- Archived projects are read-only: no issue creation, update, or deletion, and
  no comment creation.
- Admin may unarchive a project; writes become possible again.
- A project's workspace association can never be moved.

### Issues
Members can create, view, and update issues in active projects. Fields: title,
description, type (BUG/TASK), status, priority, optional assignee, optional due
date, creator, created/updated timestamps. Defaults: status OPEN, priority
MEDIUM. Assignee must be a current member of the same workspace.

**Status rules (normative):** valid statuses are OPEN, IN_PROGRESS, RESOLVED,
CLOSED. Transitions are free between any of these four statuses; skipping
statuses and reopening (including CLOSED→OPEN) are allowed. No transition
graph is imposed.

Only Admin can delete issues; deletion is audited and deleted issues disappear
from ordinary lists and dashboard totals.

### Issue list
The issue list is scoped to the selected workspace, shows non-deleted issues,
supports filters by status, priority, assignee, and overdue, and supports basic
pagination.

### Comments/activity
Members can comment on non-deleted issues in active projects. Comments cannot
be edited or deleted in this MVP.
The activity history records: workspace creation, membership added/removed/
role changed, membership-removal unassignments, project created/updated/
archived/unarchived, issue created/updated/status-changed/assigned/unassigned/
deleted, comment created. Activity includes actor, canonical action name,
target type/id, workspace id, timestamp. Activity is visible to current
workspace members and immutable through application interfaces.

### Dashboard
The workspace-scoped dashboard shows **two separate aggregate groupings** —
issue totals grouped by status and issue totals grouped by priority — plus
overdue issues. It is not a status-by-priority cross-tab.

**Date and overdue rules (normative):**
- Due date is a date-only value (YYYY-MM-DD), not a timestamp. Past due dates
  are allowed at creation. Null due date is allowed.
- Workspace timezone is UTC and is not configurable in this MVP.
- An issue is overdue **exactly when**:
  `due_date < current UTC date` AND status is neither RESOLVED nor CLOSED
  AND the issue is not deleted AND its project is not archived AND it belongs
  to the selected workspace.
- A due date equal to the current UTC date is **not** overdue.
- Dashboard totals and overdue results are scoped to the selected workspace.

## Member information visibility
Admin sees member display name, email, and role. Member sees the display name
and role needed to collaborate — not email. Exact response fields are defined
in the API contract.

## Primary journeys
1. Register/login → create workspace → dashboard.
2. Admin adds existing user → member selects workspace → only that workspace's data appears.
3. Member creates project → creates/assigns issue.
4. Member changes issue → canonical activity event appears in the workspace activity feed.
5. Member comments → author and timestamp appear.
6. Admin archives project → records readable, writes blocked; admin unarchives → writes restored.
7. User switches workspace → only selected workspace data appears.

## UX
Provide loading/empty/success/error states, field validation, confirmation for
destructive actions, visible textual status/priority (not color alone),
keyboard navigation, accessible labels, and responsive browser layout at 375px
and 1280px.

## Out of scope
Billing, chat/presence, attachments, external notifications, integrations/
webhooks, AI assistant, custom roles, project-level permissions, time
tracking, sprint planning, exports, custom fields, localization, native mobile
apps, workspace self-leave, backup/restore (documented limitation).

## Success
A user can create an account and workspace, collaborate with another
registered member on projects and issues, see accurate workspace dashboard
aggregates, and cannot access another workspace without membership. The
published acceptance criteria and the external evaluation must pass.
