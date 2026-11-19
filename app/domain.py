"""Domain service layer: workspace-agnostic business rules.

All functions take an opened DB connection (caller manages transaction)
and raise ApiError subclasses; API layer is a thin adapter.
"""

import datetime
import re

from typing import Optional

from .db import DB
from .errors import ApiError, Detail, auth_failed, conflict, forbidden, not_found, rate_limited, Validation
from .security import new_token, token_hash

__all__ = [
    "ApiError", "Detail", "Validation", "auth_failed", "conflict", "forbidden",
    "not_found", "rate_limited", "new_token", "token_hash", "CANONICAL_ACTIONS",
]

VALIDATION_EMAIL_UNIQUE = "Email is already registered."
VALIDATION_UNKNOWN_EMAIL = "Email is not recognized."

CANONICAL_ACTIONS = {
    "WORKSPACE_CREATED", "MEMBER_ADDED", "MEMBER_REMOVED", "MEMBER_ROLE_CHANGED",
    "MEMBER_ISSUES_UNASSIGNED", "PROJECT_CREATED", "PROJECT_UPDATED",
    "PROJECT_ARCHIVED", "PROJECT_UNARCHIVED", "ISSUE_CREATED", "ISSUE_UPDATED",
    "ISSUE_STATUS_CHANGED", "ISSUE_ASSIGNED", "ISSUE_UNASSIGNED",
    "ISSUE_DELETED", "COMMENT_ADDED",
}


def validate_enum(value, allowed, field_name, default=None, required=True):
    if value is None:
        if required:
            raise Validation("Missing required field.", [Detail(field_name, "Required.")])
        return default
    if not isinstance(value, str) or value not in allowed:
        raise Validation("Invalid value.", [Detail(field_name, f"Must be one of: {', '.join(allowed)}.")])
    return value


def validate_str(value, field_name, min_len, max_len, required=True, default="", collect=None):
    if collect is not None:
        if value is None:
            if required:
                collect.append({"field": field_name, "reason": "Required."})
                return default
            return default
        if not isinstance(value, str):
            collect.append({"field": field_name, "reason": "Must be a string."})
            return default
        if value != value.strip() or value.strip() == "":
            collect.append({"field": field_name, "reason": "Must be non-blank text."})
            return value.strip()
        if len(value) < min_len:
            collect.append({"field": field_name, "reason": f"Must be at least {min_len} characters."})
            return value
        if len(value) > max_len:
            collect.append({"field": field_name, "reason": f"Must be at most {max_len} characters."})
            return value
        return value
    if value is None:
        if required:
            raise Validation("Missing required field.", [Detail(field_name, "Required.")])
        return default
    if not isinstance(value, str):
        raise Validation("Invalid field type.", [Detail(field_name, "Must be a string.")])
    if value != value.strip() or value.strip() == "":
        raise Validation("Invalid text field.", [Detail(field_name, "Must be non-blank text.")])
    if len(value) < min_len:
        raise Validation("Field too short.", [Detail(field_name, f"Must be at least {min_len} characters.")])
    if len(value) > max_len:
        raise Validation("Field too long.", [Detail(field_name, f"Must be at most {max_len} characters.")])
    return value


_DATE_ONLY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def validate_date_only(value, field_name):
    """Strict Gregorian date-only validator: null or exact 'YYYY-MM-DD'.

    Accepts only `None` or a 10-character string matching the exact
    `YYYY-MM-DD` layout that is a real Gregorian calendar date
    (e.g. `2028-02-29` valid, `2027-02-29` rejected). Past dates are
    allowed. Timestamps, other layouts, whitespace, and non-string
    values are rejected with a 422 VALIDATION_ERROR.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not _DATE_ONLY_RE.fullmatch(value):
        raise Validation("Malformed date.", [Detail(field_name, "Must be 'YYYY-MM-DD' or null.")])
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        raise Validation("Malformed date.", [Detail(field_name, "Not a valid calendar date.")])
    return value


def validate_id_ref(value, field_name, allow_null=True):
    if value is None:
        if not allow_null:
            raise Validation("Missing required field.", [Detail(field_name, "Required.")])
        return None
    if not isinstance(value, str) or not value or len(value) > 64:
        raise Validation("Invalid identifier.", [Detail(field_name, "Must be an opaque string of 1-64 characters.")])
    return value


# --------------------------------------------------------------------------
# ID helper
def new_id() -> str:
    """Module-level ID generator (static-method wrapper over DB.new_id)."""
    import secrets
    return secrets.token_hex(8)

# --------------------------------------------------------------------------
# Activity


def add_activity(conn, workspace_id, actor_id, action, target_type, target_id):
    assert action in CANONICAL_ACTIONS, action
    row = conn.execute(
        "INSERT INTO activity_events"
        " (id, workspace_id, actor_id, action, target_type, target_id, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (new_id(), workspace_id, actor_id, action, target_type, target_id, DB.utcnow_iso()),
    ).lastrowid
    return row


def list_activity(conn, workspace_id, page, page_size):
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM activity_events WHERE workspace_id=?",
        (workspace_id,)).fetchone()["n"]
    items = conn.execute(
        """SELECT id, workspace_id, actor_id, action, target_type, target_id, created_at
           FROM activity_events WHERE workspace_id=?
           ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?""",
        (workspace_id, page_size, (page - 1) * page_size)).fetchall()
    return {
        "items": [dict(r) for r in items],
        "page": page, "page_size": page_size,
        "total_items": total,
        "total_pages": max(1, -(-total // page_size)),
    }


# --------------------------------------------------------------------------
# Sessions

def create_session(conn, user_id) -> str:
    token = new_token()
    conn.execute(
        "INSERT INTO sessions (id, user_id, token_hash, revoked, created_at) VALUES (?,?,?,?,?)",
        (new_id(), user_id, token_hash(token), 0, DB.utcnow_iso()))
    return token


def revoke_session(conn, session_id):
    conn.execute("UPDATE sessions SET revoked=1 WHERE id=? AND revoked=0", (session_id,))


def find_valid_session(conn, token: str):
    """Returns (session_id, user_id) or None. Revoked/unknown => None."""
    row = conn.execute("SELECT id, user_id, revoked FROM sessions WHERE token_hash=?",
                       (token_hash(token),)).fetchone()
    if row is None or row["revoked"]:
        return None
    return row["id"], row["user_id"]


# --------------------------------------------------------------------------
# Membership helpers (inside a write txn, called by API layer)

def is_member(conn, workspace_id, user_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM memberships WHERE workspace_id=? AND user_id=?",
        (workspace_id, user_id)).fetchone() is not None


def membership_role(conn, workspace_id, user_id) -> Optional[str]:
    row = conn.execute("SELECT role FROM memberships WHERE workspace_id=? AND user_id=?",
                       (workspace_id, user_id)).fetchone()
    return row["role"] if row else None


def require_member(conn, workspace_id, user_id):
    """404 for non-members (existence hidden) — contract 404 rule."""
    if not is_member(conn, workspace_id, user_id):
        raise not_found()


def require_admin(conn, workspace_id, user_id):
    role = membership_role(conn, workspace_id, user_id)
    if role is None:
        raise not_found()
    if role != "ADMIN":
        raise forbidden("Admin role required.")
    return role


def admin_count(conn, workspace_id) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM memberships WHERE workspace_id=? AND role='ADMIN'",
        (workspace_id,)).fetchone()["n"]
