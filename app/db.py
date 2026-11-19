"""SQLite storage layer.

- stdlib sqlite3, WAL mode, parameterized queries only (SEC-022).
- File-based so data survives process restart (NFR-009).
- `begin_write()` starts `BEGIN IMMEDIATE` for check-then-write atomicity.
"""

import os
import sqlite3
import secrets
import threading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    email_lower TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('ADMIN','MEMBER')),
    PRIMARY KEY (workspace_id, user_id)
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS issues (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    type TEXT NOT NULL CHECK(type IN ('BUG','TASK')),
    status TEXT NOT NULL CHECK(status IN ('OPEN','IN_PROGRESS','RESOLVED','CLOSED')),
    priority TEXT NOT NULL CHECK(priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    assignee_id TEXT,
    due_date TEXT,
    creator_id TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    issue_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    revoked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memberships_user ON memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_projects_ws ON projects(workspace_id);
CREATE INDEX IF NOT EXISTS idx_issues_ws ON issues(workspace_id, deleted);
CREATE INDEX IF NOT EXISTS idx_issues_project ON issues(project_id);
CREATE INDEX IF NOT EXISTS idx_comments_issue ON comments(issue_id);
CREATE INDEX IF NOT EXISTS idx_activity_ws ON activity_events(workspace_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);
"""


class DB:
    """Thread-local SQLite connections with WAL."""

    def __init__(self, path: str):
        self.path = path
        local = threading.local()
        self._local = local
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = self.conn()
        conn.executescript(_SCHEMA)
        conn.commit()

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL;")
            c.execute("PRAGMA foreign_keys=ON;")
            c.execute("PRAGMA busy_timeout=30000;")
            self._local.conn = c
        return c

    # -- write-transaction helpers -----------------------------------------

    def begin_write(self):
        """Start an IMMEDIATE write transaction (held until commit/rollback).

        Callers MUST use as context: `with self.begin_write() as conn:`.
        """
        conn = self.conn()
        conn.execute("BEGIN IMMEDIATE")
        return _Txn(conn, self)

    def new_id(self) -> str:
        return secrets.token_hex(8)

    @staticmethod
    def utcnow_iso() -> str:
        """Contract timestamp: second precision, Z suffix, UTC."""
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def utc_today() -> str:
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


class _Txn:
    """Context manager holding a write transaction open."""

    def __init__(self, conn, db: DB):
        self.conn = conn
        self.db = db

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        return False
