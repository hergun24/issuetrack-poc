"""REST/JSON API implementing 06-API-CONTRACT-REFERENCE.md exactly."""

import re
from typing import Optional

from fastapi import APIRouter, Query, Request

from .db import DB
from .domain import (
    add_activity, admin_count, auth_failed, create_session, forbidden,
    find_valid_session, is_member, membership_role,
    revoke_session, validate_date_only, validate_enum, validate_id_ref,
    validate_str,
)
from .errors import ApiError, Detail, not_found, rate_limited, Validation
from .ops import logger
from .schemas import (
    CommentCreate, IssueCreate, IssuePatch, LoginRequest, MemberAdd, MemberRolePatch,
    ProjectCreate, ProjectPatch, RegisterRequest, UpdateMeRequest, WorkspaceCreate,
)
from .security import hash_password, verify_password


def _auth_limiter(request: Request):
    # Per-app limiter instance: each create_app() call stores its own limiter
    # in app.state (see app/main.py).  This keeps rate-limit state isolated
    # between app instances (important for tests that create multiple apps in
    # one process) and allows create_app(disable_ratelimit=True) to install a
    # passthrough without mutating shared module state.
    return request.app.state.auth_limiter


router = APIRouter(prefix="/api")

STATUSES = ("OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED")
PRIORITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
TYPES = ("BUG", "TASK")
ROLES = ("ADMIN", "MEMBER")

MAX_ISSUE_TITLE = 200
MIN_ISSUE_TITLE = 3
MAX_DESC = 5000
MAX_PROJECT_DESC = 2000
MAX_COMMENT_BODY = 2000

OVERDUE_STATUS_EXCLUDED = {"RESOLVED", "CLOSED"}


def utc_today() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


# --------------------------------------------------------------------------
# Dependency scaffolding

def get_db(request: Request) -> DB:
    return request.app.state.db


def client_key(request: Request, kind: str) -> str:
    ip = request.client.host if request.client else "?"
    return f"{kind}:{ip}"


# --------------------------------------------------------------------------
# Serializers

def user_out(row) -> dict:
    return {"id": row["id"], "email": row["email"], "display_name": row["display_name"]}


def project_out(row) -> dict:
    return {
        "id": row["id"], "workspace_id": row["workspace_id"], "name": row["name"],
        "description": row["description"], "archived": bool(row["archived"]),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def issue_out(row) -> dict:
    return {
        "id": row["id"], "workspace_id": row["workspace_id"], "project_id": row["project_id"],
        "title": row["title"], "description": row["description"], "type": row["type"],
        "status": row["status"], "priority": row["priority"],
        "assignee_id": row["assignee_id"], "due_date": row["due_date"],
        "creator_id": row["creator_id"], "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def member_out(row, include_email: bool) -> dict:
    out = {"user_id": row["user_id"], "display_name": row["display_name"], "role": row["role"]}
    if include_email:
        out["email"] = row["email"]
    return out


def page(items, page, page_size, total_items) -> dict:
    return {
        "items": list(items), "page": page, "page_size": page_size,
        "total_items": total_items, "total_pages": max(1, -(-total_items // page_size)),
    }


# --------------------------------------------------------------------------
# Health

@router.get("/health")
def health():
    return {"status": "ok"}


# --------------------------------------------------------------------------
# Version

@router.get("/version")
def version():
    return {"app": "IssueTrack Lite", "version": "0.2.4", "status": "active"}


# --------------------------------------------------------------------------
# Authentication

@router.post("/auth/register", status_code=201)
def register(payload: RegisterRequest, request: Request):
    if not _auth_limiter(request).allow(client_key(request, "register")):
        raise rate_limited()
    # collect all field-level validation failures at once (AC: details list)
    problems = []
    email = _validate_email(payload.email, collect=problems)
    password = _validate_password(payload.password, collect=problems)
    display_name = validate_str(payload.display_name, "display_name", 1, 100,
                                collect=problems)
    if problems:
        raise Validation("Registration failed.", [Detail(d["field"], d["reason"]) for d in problems])
    db = get_db(request)
    with db.begin_write() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE email_lower=?", (email.lower(),)).fetchone()
        if existing:
            # generic duplicate rejection (no duplicate created, AC-001)
            raise Validation("Registration failed.")
        user_id = db.new_id()
        conn.execute(
            "INSERT INTO users (id, email, email_lower, display_name, password_hash, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (user_id, email, email.lower(), display_name, hash_password(password), db.utcnow_iso()))
        conn.execute("SELECT last_insert_rowid()")
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    logger.info("auth.register.ok", extra={"user_id": user_id})
    return user_out(row)


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request):
    if not _auth_limiter(request).allow(client_key(request, "login")):
        raise rate_limited()
    # identical timing/body for unknown email vs wrong password
    db = get_db(request)
    with db.begin_write() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email_lower=?", (payload.email.lower(),)).fetchone()
        ok = bool(row) and verify_password(payload.password, row["password_hash"])
        if not ok:
            raise auth_failed()
        token = create_session(conn, row["id"])
    logger.info("auth.login.ok", extra={"user_id": row["id"]})
    return {"token": token, "user": user_out(row)}


@router.post("/auth/logout", status_code=204)
def logout(request: Request):
    token = _require_token(request)
    db = get_db(request)
    with db.begin_write() as conn:
        sess = find_valid_session(conn, token)
        if sess is None:
            raise ApiError(401, "UNAUTHENTICATED", "Authentication required.")
        session_id, user_id = sess
        revoke_session(conn, session_id)
    logger.info("auth.logout", extra={"user_id": user_id})
    return None


@router.get("/me")
def get_me(request: Request):
    token = _require_token(request)
    db = get_db(request)
    conn = db.conn()
    sess = find_valid_session(conn, token)
    if sess is None:
        raise ApiError(401, "UNAUTHENTICATED", "Authentication required.")
    user_id = sess[1]
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        raise ApiError(401, "UNAUTHENTICATED", "Authentication required.")
    return user_out(row)


@router.patch("/me")
def update_me(payload: UpdateMeRequest, request: Request):
    token = _require_token(request)
    display_name = validate_str(payload.display_name, "display_name", 1, 100)
    db = get_db(request)
    with db.begin_write() as conn:
        sess = find_valid_session(conn, token)
        if sess is None:
            raise ApiError(401, "UNAUTHENTICATED", "Authentication required.")
        user_id = sess[1]
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise ApiError(401, "UNAUTHENTICATED", "Authentication required.")
        conn.execute("UPDATE users SET display_name=? WHERE id=?", (display_name, user_id))
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return user_out(row)


def _require_token(request: Request) -> str:
    auth = request.headers.get("authorization")
    if not auth:
        raise ApiError(401, "UNAUTHENTICATED", "Authentication required.")
    parts = auth.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise ApiError(401, "UNAUTHENTICATED", "Authentication required.")
    return parts[1].strip()


def _require_user(request: Request):
    """Returns (conn, user_id) after validating the bearer session."""
    token = _require_token(request)
    db = get_db(request)
    conn = db.conn()
    sess = find_valid_session(conn, token)
    if sess is None:
        raise ApiError(401, "UNAUTHENTICATED", "Authentication required.")
    _, user_id = sess
    row = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        raise ApiError(401, "UNAUTHENTICATED", "Authentication required.")
    return conn, user_id


def _validate_email(email, collect=None) -> str:
    import email as _email
    address = str(email).strip()

    def _bad(reason):
        if collect is not None:
            collect.append({"field": "email", "reason": reason})
            return address
        raise Validation("Registration failed.", [Detail("email", reason)])
    if len(address) > 254:
        return _bad("Must be at most 254 characters.")
    try:
        parsed = _email.utils.parseaddr(address)
        local = parsed[1] or address
    except Exception:
        return _bad("Invalid email.")
    if not re.fullmatch(r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)+", local):
        return _bad("Invalid email.")
    return local


def _validate_password(password: str, collect=None) -> str:
    if not isinstance(password, str) or not (8 <= len(password) <= 128):
        if collect is not None:
            collect.append({"field": "password", "reason": "Must be 8 to 128 characters."})
            return password
        raise Validation("Registration failed.", [
            Detail("password", "Must be 8 to 128 characters.")])
    return password


# --------------------------------------------------------------------------
# Workspaces

@router.get("/workspaces")
def list_workspaces(request: Request):
    conn, user_id = _require_user(request)
    rows = conn.execute(
        "SELECT w.id AS id, w.name AS name, m.role AS role FROM memberships m "
        "JOIN workspaces w ON w.id=m.workspace_id WHERE m.user_id=? ORDER BY w.name",
        (user_id,)).fetchall()
    return {"items": [{"id": r["id"], "name": r["name"], "role": r["role"]} for r in rows]}


@router.post("/workspaces", status_code=201)
def create_workspace(payload: WorkspaceCreate, request: Request):
    name = validate_str(payload.name, "name", 1, 100)
    conn, user_id = _require_user(request)
    db = get_db(request)
    with db.begin_write() as tx:
        ws_id = db.new_id()
        tx.execute("INSERT INTO workspaces (id, name, created_at) VALUES (?,?,?)",
                   (ws_id, name, db.utcnow_iso()))
        tx.execute("INSERT INTO memberships (workspace_id, user_id, role) VALUES (?,?, 'ADMIN')",
                   (ws_id, user_id))
        add_activity(tx, ws_id, user_id, "WORKSPACE_CREATED", "workspace", ws_id)
        row = tx.execute("SELECT * FROM workspaces WHERE id=?", (ws_id,)).fetchone()
    return {"id": row["id"], "name": row["name"], "role": "ADMIN"}


# --------------------------------------------------------------------------
# Workspace context helper

def _ws_ctx(request: Request, workspace_id: str, require_admin_role: bool = False):
    """Authenticate + membership check (+ admin role when required).

    Returns (conn, user_id, role). Non-member -> 404 (existence hidden).
    """
    conn, user_id = _require_user(request)
    role = membership_role(conn, workspace_id, user_id)
    if role is None:
        raise not_found()
    if require_admin_role and role != "ADMIN":
        raise forbidden("Admin role required.")
    return conn, user_id, role


# --------------------------------------------------------------------------
# Members

@router.get("/workspaces/{workspace_id}/members")
def list_members(workspace_id: str, request: Request):
    conn, user_id, role = _ws_ctx(request, workspace_id)
    rows = conn.execute(
        "SELECT m.user_id AS user_id, u.display_name AS display_name, m.role AS role, "
        "u.email AS email FROM memberships m JOIN users u ON u.id=m.user_id "
        "WHERE m.workspace_id=? ORDER BY u.display_name",
        (workspace_id,)).fetchall()
    return {"items": [member_out(r, include_email=(role == "ADMIN")) for r in rows]}


@router.post("/workspaces/{workspace_id}/members", status_code=201)
def add_member(workspace_id: str, payload: MemberAdd, request: Request):
    validate_enum(payload.role, ROLES, "role")
    conn, user_id, _ = _ws_ctx(request, workspace_id, require_admin_role=True)
    db = get_db(request)
    with db.begin_write() as tx:
        target = tx.execute(
            "SELECT id, email, display_name FROM users WHERE email_lower=?",
            (payload.email.lower(),)).fetchone()
        if target is None:
            raise Validation("Member could not be added.")  # generic, no account created
        existing = tx.execute(
            "SELECT 1 FROM memberships WHERE workspace_id=? AND user_id=?",
            (workspace_id, target["id"])).fetchone()
        if existing:
            raise Validation("Member could not be added.")
        tx.execute("INSERT INTO memberships (workspace_id, user_id, role) VALUES (?,?,?)",
                   (workspace_id, target["id"], payload.role))
        add_activity(tx, workspace_id, user_id, "MEMBER_ADDED", "user", target["id"])
        out = _member_row(tx, workspace_id, target["id"])
    return member_out(out, include_email=True)


@router.patch("/workspaces/{workspace_id}/members/{user_id}")
def change_member_role(workspace_id: str, user_id: str, payload: MemberRolePatch, request: Request):
    validate_enum(payload.role, ROLES, "role")
    conn, actor_id, _ = _ws_ctx(request, workspace_id, require_admin_role=True)
    db = get_db(request)
    with db.begin_write() as tx:
        target = tx.execute(
            "SELECT role FROM memberships WHERE workspace_id=? AND user_id=?",
            (workspace_id, user_id)).fetchone()
        if target is None:
            raise not_found()
        if payload.role == "MEMBER" and target["role"] == "ADMIN" and admin_count(tx, workspace_id) == 1:
            raise ApiError(409, "CONFLICT", "Workspace must retain at least one Admin.")
        tx.execute("UPDATE memberships SET role=? WHERE workspace_id=? AND user_id=?",
                   (payload.role, workspace_id, user_id))
        if payload.role != target["role"]:
            add_activity(tx, workspace_id, actor_id, "MEMBER_ROLE_CHANGED", "user", user_id)
        out = _member_row(tx, workspace_id, user_id)
    return member_out(out, include_email=True)


@router.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(workspace_id: str, user_id: str, request: Request):
    conn, actor_id, _ = _ws_ctx(request, workspace_id, require_admin_role=True)
    db = get_db(request)
    with db.begin_write() as tx:
        target = tx.execute(
            "SELECT role FROM memberships WHERE workspace_id=? AND user_id=?",
            (workspace_id, user_id)).fetchone()
        if target is None:
            raise not_found()
        if target["role"] == "ADMIN" and admin_count(tx, workspace_id) == 1:
            raise ApiError(409, "CONFLICT", "The last Admin cannot be removed.")
        # auto-unassign: issues assigned to the removed member in this workspace
        rows = tx.execute(
            "SELECT id FROM issues WHERE workspace_id=? AND assignee_id=? AND deleted=0",
            (workspace_id, user_id)).fetchall()
        for r in rows:
            tx.execute("UPDATE issues SET assignee_id=NULL, updated_at=? WHERE id=?",
                       (db.utcnow_iso(), r["id"]))
            add_activity(tx, workspace_id, actor_id, "MEMBER_ISSUES_UNASSIGNED", "issue", r["id"])
        tx.execute("DELETE FROM memberships WHERE workspace_id=? AND user_id=?",
                   (workspace_id, user_id))
        add_activity(tx, workspace_id, actor_id, "MEMBER_REMOVED", "user", user_id)
    logger.info("member.removed", extra={"workspace_id": workspace_id, "user_id": user_id})
    return None


def _member_row(conn, workspace_id, user_id):
    return conn.execute(
        "SELECT m.user_id AS user_id, u.display_name AS display_name, m.role AS role, "
        "u.email AS email FROM memberships m JOIN users u ON u.id=m.user_id "
        "WHERE m.workspace_id=? AND m.user_id=?",
        (workspace_id, user_id)).fetchone()


# --------------------------------------------------------------------------
# Projects

@router.get("/workspaces/{workspace_id}/projects")
def list_projects(workspace_id: str, request: Request):
    conn, _, _ = _ws_ctx(request, workspace_id)
    rows = conn.execute(
        "SELECT * FROM projects WHERE workspace_id=? ORDER BY created_at DESC, id DESC",
        (workspace_id,)).fetchall()
    return {"items": [project_out(r) for r in rows]}


@router.post("/workspaces/{workspace_id}/projects", status_code=201)
def create_project(workspace_id: str, payload: ProjectCreate, request: Request):
    name = validate_str(payload.name, "name", 1, 200)
    description = payload.description if payload.description is not None else None
    if description is not None and len(description) > MAX_PROJECT_DESC:
        raise Validation("Validation error.", [
            Detail("description", f"Must be at most {MAX_PROJECT_DESC} characters.")])
    conn, user_id, _ = _ws_ctx(request, workspace_id)
    db = get_db(request)
    with db.begin_write() as tx:
        pid = db.new_id()
        now = db.utcnow_iso()
        tx.execute(
            "INSERT INTO projects (id, workspace_id, name, description, archived, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (pid, workspace_id, name, description, 0, now, now))
        add_activity(tx, workspace_id, user_id, "PROJECT_CREATED", "project", pid)
        row = tx.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    return project_out(row)


@router.get("/workspaces/{workspace_id}/projects/{project_id}")
def get_project(workspace_id: str, project_id: str, request: Request):
    conn, _, _ = _ws_ctx(request, workspace_id)
    row = conn.execute(
        "SELECT * FROM projects WHERE id=? AND workspace_id=?", (project_id, workspace_id)).fetchone()
    if row is None:
        raise not_found()
    return project_out(row)


@router.patch("/workspaces/{workspace_id}/projects/{project_id}")
def patch_project(workspace_id: str, project_id: str, payload: ProjectPatch, request: Request):
    conn, actor_id, _ = _ws_ctx(request, workspace_id, require_admin_role=True)
    db = get_db(request)
    with db.begin_write() as tx:
        row = tx.execute("SELECT * FROM projects WHERE id=? AND workspace_id=?",
                         (project_id, workspace_id)).fetchone()
        if row is None:
            raise not_found()
        updates = {}
        if payload.name is not None:
            validate_str(payload.name, "name", 1, 200)
            updates["name"] = payload.name
        if payload.description is not None:
            if len(payload.description) > MAX_PROJECT_DESC:
                raise Validation("Validation error.", [
                    Detail("description", f"Must be at most {MAX_PROJECT_DESC} characters.")])
            updates["description"] = payload.description
        if payload.archived is not None:
            new_state = 1 if payload.archived else 0
            if new_state != row["archived"]:
                updates["archived"] = new_state
        if not updates:
            return project_out(row)
        now = db.utcnow_iso()
        updates["updated_at"] = now
        cols = ", ".join(f"{c}=?" for c in updates)
        tx.execute(f"UPDATE projects SET {cols} WHERE id=?",
                   (*updates.values(), project_id))
        if "archived" in updates:
            action = "PROJECT_ARCHIVED" if updates["archived"] == 1 else "PROJECT_UNARCHIVED"
            add_activity(tx, workspace_id, actor_id, action, "project", project_id)
        if set(updates) - {"archived", "updated_at"}:
            add_activity(tx, workspace_id, actor_id, "PROJECT_UPDATED", "project", project_id)
        row = tx.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return project_out(row)


# --------------------------------------------------------------------------
# Issues

def _pagination(page, page_size) -> tuple:
    def _int(value, name, lo, hi):
        if value is None:
            return None
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise Validation("Invalid pagination.", [Detail(name, "Must be an integer.")])
        if n < lo or n > hi:
            raise Validation("Invalid pagination.", [
                Detail(name, f"Must be between {lo} and {hi}.")])
        return n

    p = _int(page, "page", 1, 10_000) or 1
    ps = _int(page_size, "page_size", 1, 100) or 20
    return p, ps


def _overdue(due_date, status, project_archived) -> bool:
    """Approved overdue rule; due_date/archived are data, status is data."""
    if due_date is None:
        return False
    if status in OVERDUE_STATUS_EXCLUDED:
        return False
    if project_archived:
        return False
    # Overdue iff due date is strictly before today in UTC: a due date equal
    # to today's UTC date is not overdue until UTC midnight passes.
    return due_date < utc_today()


@router.get("/workspaces/{workspace_id}/issues")
def list_issues(workspace_id: str, request: Request,
                status: Optional[str] = None, priority: Optional[str] = None,
                assignee_id: Optional[str] = None, overdue: Optional[str] = None,
                page_no: Optional[str] = Query(None, alias="page"),
                page_size: Optional[str] = Query(None, alias="page_size")):
    conn, _, _ = _ws_ctx(request, workspace_id)
    if status is not None:
        validate_enum(status, STATUSES, "status")
    if priority is not None:
        validate_enum(priority, PRIORITIES, "priority")
    if assignee_id is not None:
        validate_id_ref(assignee_id, "assignee_id")
    overdue_flag = None
    if overdue is not None:
        if overdue not in ("true", "false"):
            raise Validation("Invalid filter.", [Detail("overdue", "Must be 'true' or 'false'.")])
        overdue_flag = overdue == "true"
    p, ps = _pagination(page_no, page_size)

    where = ["i.workspace_id=?", "i.deleted=0"]
    params: list = [workspace_id]
    if status:
        where.append("i.status=?")
        params.append(status)
    if priority:
        where.append("i.priority=?")
        params.append(priority)
    if assignee_id is not None:
        where.append("i.assignee_id=?")
        params.append(assignee_id)
    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""SELECT i.*, p.archived AS project_archived FROM issues i
            JOIN projects p ON p.id=i.project_id WHERE {where_sql}
            ORDER BY i.created_at DESC, i.id DESC""",
        (*params,)).fetchall()
    if overdue_flag is not None:
        rows = [r for r in rows if _overdue(r["due_date"], r["status"], bool(r["project_archived"])) == overdue_flag]
    total = len(rows)
    items = [issue_out(r) for r in rows[(p - 1) * ps: (p - 1) * ps + ps]]
    return page(items, p, ps, total)


@router.post("/workspaces/{workspace_id}/issues", status_code=201)
def create_issue(workspace_id: str, payload: IssueCreate, request: Request):
    project_id = validate_id_ref(payload.project_id, "project_id", allow_null=False)
    title = validate_str(payload.title, "title", MIN_ISSUE_TITLE, MAX_ISSUE_TITLE)
    description = _optional_desc(payload.description)
    itype = validate_enum(payload.type, TYPES, "type", required=False, default="BUG")
    priority = validate_enum(payload.priority, PRIORITIES, "priority", required=False, default="MEDIUM")
    due_date = validate_date_only(payload.due_date, "due_date")
    assignee_id = validate_id_ref(payload.assignee_id, "assignee_id")
    conn, user_id, _ = _ws_ctx(request, workspace_id)
    db = get_db(request)
    with db.begin_write() as tx:
        project = tx.execute("SELECT * FROM projects WHERE id=? AND workspace_id=?",
                             (project_id, workspace_id)).fetchone()
        if project is None:
            raise not_found()
        if project["archived"]:
            raise ApiError(409, "CONFLICT", "Project is archived and read-only.")
        if assignee_id is not None and not is_member(tx, workspace_id, assignee_id):
            raise Validation("Validation error.", [
                Detail("assignee_id", "Assignee must be a current member of this workspace.")])
        iid = db.new_id()
        now = db.utcnow_iso()
        tx.execute(
            "INSERT INTO issues (id, workspace_id, project_id, title, description, type, status,"
            " priority, assignee_id, due_date, creator_id, deleted, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (iid, workspace_id, project_id, title, description, itype, "OPEN", priority,
             assignee_id, due_date, user_id, 0, now, now))
        add_activity(tx, workspace_id, user_id, "ISSUE_CREATED", "issue", iid)
        if assignee_id is not None:
            add_activity(tx, workspace_id, user_id, "ISSUE_ASSIGNED", "issue", iid)
        row = tx.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone()
    return issue_out(row)


@router.get("/workspaces/{workspace_id}/issues/{issue_id}")
def get_issue(workspace_id: str, issue_id: str, request: Request):
    conn, _, _ = _ws_ctx(request, workspace_id)
    row = conn.execute(
        "SELECT * FROM issues WHERE id=? AND workspace_id=? AND deleted=0",
        (issue_id, workspace_id)).fetchone()
    if row is None:
        raise not_found()
    return issue_out(row)


@router.patch("/workspaces/{workspace_id}/issues/{issue_id}")
def patch_issue(workspace_id: str, issue_id: str, payload: IssuePatch, request: Request):
    conn, user_id, _ = _ws_ctx(request, workspace_id)
    db = get_db(request)
    with db.begin_write() as tx:
        row = tx.execute("SELECT * FROM issues WHERE id=? AND workspace_id=? AND deleted=0",
                         (issue_id, workspace_id)).fetchone()
        if row is None:
            raise not_found()
        project = tx.execute("SELECT archived FROM projects WHERE id=?",
                             (row["project_id"],)).fetchone()
        if project and project["archived"]:
            raise ApiError(409, "CONFLICT", "Project is archived and read-only.")

        provided = set(payload.model_fields_set)
        updates: dict = {}

        if "title" in provided:
            validate_str(payload.title, "title", MIN_ISSUE_TITLE, MAX_ISSUE_TITLE)
            if payload.title != row["title"]:
                updates["title"] = payload.title
        if "description" in provided:
            new_desc = _optional_desc(payload.description)
            if new_desc != row["description"]:
                updates["description"] = new_desc
        if "type" in provided:
            if payload.type is not None:
                new_type = validate_enum(payload.type, TYPES, "type", required=False,
                                         default="BUG")
            else:
                new_type = "BUG"
            if new_type != row["type"]:
                updates["type"] = new_type
        if "priority" in provided:
            if payload.priority is not None:
                new_priority = validate_enum(payload.priority, PRIORITIES, "priority",
                                             required=False, default="MEDIUM")
            else:
                new_priority = "MEDIUM"
            if new_priority != row["priority"]:
                updates["priority"] = new_priority
        if "status" in provided:
            if payload.status is not None:
                new_status = validate_enum(payload.status, STATUSES, "status",
                                           required=False, default="OPEN")
            else:
                new_status = "OPEN"
            if new_status != row["status"]:
                updates["status"] = new_status
        if "due_date" in provided:
            new_due = validate_date_only(payload.due_date, "due_date")
            if new_due != row["due_date"]:
                updates["due_date"] = new_due
        if "assignee_id" in provided:
            new_assignee = validate_id_ref(payload.assignee_id, "assignee_id")
            if new_assignee is not None and not is_member(tx, workspace_id, new_assignee):
                raise Validation("Validation error.", [
                    Detail("assignee_id", "Assignee must be a current member of this workspace.")])
            if new_assignee != row["assignee_id"]:
                updates["assignee_id"] = new_assignee

        # A PATCH that does not actually change any stored field value is a
        # no-op: no activity event is emitted and updated_at is untouched.
        if not updates:
            return issue_out(row)

        now = db.utcnow_iso()
        updates["updated_at"] = now
        cols = ", ".join(f"{c}=?" for c in updates)
        tx.execute(f"UPDATE issues SET {cols} WHERE id=?", (*updates.values(), issue_id))

        # Event selection: status-only -> STATUS_CHANGED; assignee-only ->
        # ASSIGNED/UNASSIGNED; any other field change -> UPDATED.
        status_changed = "status" in updates
        assignee_changed = "assignee_id" in updates
        other_changed = bool(set(updates) - {"status", "assignee_id", "updated_at"})
        if status_changed and not assignee_changed and not other_changed:
            add_activity(tx, workspace_id, user_id, "ISSUE_STATUS_CHANGED", "issue", issue_id)
        elif assignee_changed and not status_changed and not other_changed:
            action = "ISSUE_ASSIGNED" if updates["assignee_id"] is not None else "ISSUE_UNASSIGNED"
            add_activity(tx, workspace_id, user_id, action, "issue", issue_id)
        else:
            add_activity(tx, workspace_id, user_id, "ISSUE_UPDATED", "issue", issue_id)
        row = tx.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    return issue_out(row)


@router.delete("/workspaces/{workspace_id}/issues/{issue_id}", status_code=204)
def delete_issue(workspace_id: str, issue_id: str, request: Request):
    conn, user_id, _ = _ws_ctx(request, workspace_id, require_admin_role=True)
    db = get_db(request)
    with db.begin_write() as tx:
        row = tx.execute("SELECT * FROM issues WHERE id=? AND workspace_id=? AND deleted=0",
                         (issue_id, workspace_id)).fetchone()
        if row is None:
            raise not_found()
        now = db.utcnow_iso()
        tx.execute("UPDATE issues SET deleted=1, updated_at=? WHERE id=?", (now, issue_id))
        add_activity(tx, workspace_id, user_id, "ISSUE_DELETED", "issue", issue_id)
    logger.info("issue.deleted", extra={"workspace_id": workspace_id, "issue_id": issue_id})
    return None


def _optional_desc(description):
    if description is None:
        return None
    if not isinstance(description, str):
        raise Validation("Invalid field type.", [Detail("description", "Must be a string.")])
    stripped = description.strip()
    if not stripped:
        return None
    if len(stripped) > MAX_DESC:
        raise Validation("Validation error.", [
            Detail("description", f"Must be at most {MAX_DESC} characters.")])
    return stripped


# --------------------------------------------------------------------------
# Comments

@router.get("/workspaces/{workspace_id}/issues/{issue_id}/comments")
def list_comments(workspace_id: str, issue_id: str, request: Request,
                  page_no: Optional[str] = Query(None, alias="page"),
                  page_size: Optional[str] = Query(None, alias="page_size")):
    conn, _, _ = _ws_ctx(request, workspace_id)
    p, ps = _pagination(page_no, page_size)
    row = conn.execute("SELECT id FROM issues WHERE id=? AND workspace_id=? AND deleted=0",
                       (issue_id, workspace_id)).fetchone()
    if row is None:
        raise not_found()
    total = conn.execute("SELECT COUNT(*) AS n FROM comments WHERE issue_id=?",
                         (issue_id,)).fetchone()["n"]
    rows = conn.execute(
        "SELECT id, issue_id, author_id, body, created_at FROM comments WHERE issue_id=?"
        " ORDER BY created_at ASC, id ASC LIMIT ? OFFSET ?",
        (issue_id, ps, (p - 1) * ps)).fetchall()
    return page([dict(r) for r in rows], p, ps, total)


@router.post("/workspaces/{workspace_id}/issues/{issue_id}/comments", status_code=201)
def create_comment(workspace_id: str, issue_id: str, payload: CommentCreate, request: Request):
    body = validate_str(payload.body, "body", 1, MAX_COMMENT_BODY)
    conn, user_id, _ = _ws_ctx(request, workspace_id)
    db = get_db(request)
    with db.begin_write() as tx:
        issue = tx.execute("SELECT * FROM issues WHERE id=? AND workspace_id=? AND deleted=0",
                           (issue_id, workspace_id)).fetchone()
        if issue is None:
            raise not_found()
        project = tx.execute("SELECT archived FROM projects WHERE id=?",
                             (issue["project_id"],)).fetchone()
        if project and project["archived"]:
            raise ApiError(409, "CONFLICT", "Project is archived and read-only.")
        cid = db.new_id()
        tx.execute(
            "INSERT INTO comments (id, issue_id, author_id, body, created_at) VALUES (?,?,?,?,?)",
            (cid, issue_id, user_id, body, db.utcnow_iso()))
        add_activity(tx, workspace_id, user_id, "COMMENT_ADDED", "comment", cid)
        row = tx.execute(
            "SELECT id, issue_id, author_id, body, created_at FROM comments WHERE id=?", (cid,)).fetchone()
    return dict(row)


# --------------------------------------------------------------------------
# Activity

@router.get("/workspaces/{workspace_id}/activity")
def get_activity(workspace_id: str, request: Request,
                 page_no: Optional[str] = Query(None, alias="page"),
                 page_size: Optional[str] = Query(None, alias="page_size")):
    conn, _, _ = _ws_ctx(request, workspace_id)
    p, ps = _pagination(page_no, page_size)
    # NOTE: activity_events.id is a random hex PK, so the default
    # "created_at DESC, id DESC" sort is non-deterministic when rows share the
    # same second-precision timestamp (a frequent case under fast API calls).
    # Use the SQLite rowid (monotonic insertion order) as the deterministic
    # tie-breaker so "newest first" is always a true reverse of insertion order.
    from .domain import new_id  # noqa: F401
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM activity_events WHERE workspace_id=?",
        (workspace_id,)).fetchone()["n"]
    rows = conn.execute(
        """SELECT id, workspace_id, actor_id, action, target_type, target_id, created_at
           FROM activity_events WHERE workspace_id=?
           ORDER BY rowid DESC LIMIT ? OFFSET ?""",
        (workspace_id, ps, (p - 1) * ps)).fetchall()
    return {
        "items": [dict(r) for r in rows],
        "page": p, "page_size": ps,
        "total_items": total,
        "total_pages": max(1, -(-total // ps)),
    }


# --------------------------------------------------------------------------
# Dashboard

@router.get("/workspaces/{workspace_id}/dashboard")
def dashboard(workspace_id: str, request: Request):
    conn, _, _ = _ws_ctx(request, workspace_id)
    status_totals = {s: 0 for s in STATUSES}
    priority_totals = {p_: 0 for p_ in PRIORITIES}
    rows = conn.execute(
        "SELECT i.status AS status, i.priority AS priority, i.due_date AS due_date, i.id AS id "
        "FROM issues i JOIN projects p ON p.id=i.project_id "
        "WHERE i.workspace_id=? AND i.deleted=0 AND p.archived=0",
        (workspace_id,)).fetchall()
    for r in rows:
        status_totals[r["status"]] += 1
        priority_totals[r["priority"]] += 1
    overdue_ids = [r["id"] for r in rows if _overdue(r["due_date"], r["status"], False)]
    return {
        "status_totals": status_totals,
        "priority_totals": priority_totals,
        "overdue_count": len(overdue_ids),
        "overdue_issue_ids": overdue_ids,
    }
