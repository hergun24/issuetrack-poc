"""Deterministic seed-data mechanism (constraint 6).

Creates a small demo dataset: 1 admin user, 1 extra member, 1 workspace,
2 projects (one archived), issues across statuses/priorities (incl. a past
due-date and a today due-date to exercise the overdue boundary), and a
comment. Idempotent: refuses to seed a non-empty database unless --force.
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import DB  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.domain import add_activity  # noqa: E402

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("IT_DB_PATH", os.path.join(_HERE, "data", "issuetrack.db"))


def _find_user(conn, email):
    return conn.execute("SELECT id FROM users WHERE email_lower=?", (email.lower(),)).fetchone()


def _find_ws(conn, name):
    return conn.execute("SELECT id FROM workspaces WHERE name=?", (name,)).fetchone()


def seed(db: DB, force: bool = False):
    with db.begin_write() as tx:
        n_users = tx.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        if n_users > 0 and not force:
            print("Database already contains data. Use --force to overwrite seed users.")
            return 1

        admin = _find_user(tx, "admin@example.com")
        member = _find_user(tx, "member@example.com")

        # users
        if admin is None:
            admin_id = db.new_id()
            tx.execute("INSERT INTO users (id, email, email_lower, display_name, password_hash, created_at)"
                       " VALUES (?,?,?,?,?,?)",
                       (admin_id, "admin@example.com", "admin@example.com", "Admin User",
                        hash_password("admin12345"), db.utcnow_iso()))
            admin = {"id": admin_id}
        else:
            admin = {"id": admin["id"]}

        if member is None:
            member_id = db.new_id()
            tx.execute("INSERT INTO users (id, email, email_lower, display_name, password_hash, created_at)"
                       " VALUES (?,?,?,?,?,?)",
                       (member_id, "member@example.com", "member@example.com", "Member User",
                        hash_password("member12345"), db.utcnow_iso()))
            member = {"id": member_id}
        else:
            member = {"id": member["id"]}

        # workspace
        ws = _find_ws(tx, "Seed Workspace")
        if ws is None:
            ws_id = db.new_id()
            tx.execute("INSERT INTO workspaces (id, name, created_at) VALUES (?,?,?)",
                       (ws_id, "Seed Workspace", db.utcnow_iso()))
            tx.execute("INSERT INTO memberships (workspace_id, user_id, role) VALUES (?,?,?)",
                       (ws_id, admin["id"], "ADMIN"))
            add_activity(tx, ws_id, admin["id"], "WORKSPACE_CREATED", "workspace", ws_id)
            ws = {"id": ws_id}
        else:
            ws = {"id": ws["id"]}
        if not tx.execute("SELECT 1 FROM memberships WHERE workspace_id=? AND user_id=?",
                          (ws["id"], member["id"])).fetchone():
            tx.execute("INSERT INTO memberships (workspace_id, user_id, role) VALUES (?,?, 'MEMBER')",
                       (ws["id"], member["id"]))
            add_activity(tx, ws["id"], admin["id"], "MEMBER_ADDED", "user", member["id"])

        # projects
        prj = tx.execute("SELECT id FROM projects WHERE workspace_id=? AND name=?",
                         (ws["id"], "Seed Project")).fetchone()
        if prj is None:
            prj_id = db.new_id()
            tx.execute("INSERT INTO projects (id, workspace_id, name, description, archived, created_at, updated_at)"
                       " VALUES (?,?,?,?,?,?,?)",
                       (prj_id, ws["id"], "Seed Project", "Seeded demo project", 0, db.utcnow_iso(), db.utcnow_iso()))
            add_activity(tx, ws["id"], admin["id"], "PROJECT_CREATED", "project", prj_id)
            prj = {"id": prj_id}
        else:
            prj = {"id": prj["id"]}

        archived = tx.execute("SELECT id FROM projects WHERE workspace_id=? AND name=?",
                              (ws["id"], "Archived Archive")).fetchone()
        if archived is None:
            arch_id = db.new_id()
            tx.execute("INSERT INTO projects (id, workspace_id, name, description, archived, created_at, updated_at)"
                       " VALUES (?,?,?,?,1,?,?)",
                       (arch_id, ws["id"], "Archived Archive", "Read-only archive", db.utcnow_iso(), db.utcnow_iso()))
            add_activity(tx, ws["id"], admin["id"], "PROJECT_CREATED", "project", arch_id)
            add_activity(tx, ws["id"], admin["id"], "PROJECT_ARCHIVED", "project", arch_id)
            archived = {"id": arch_id}
        else:
            archived = {"id": archived["id"]}

        # issues
        import datetime
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)

        specs = [
            ("Seeded Bug: login flake", "BUG", "OPEN", "HIGH", str(yesterday), "past due -> overdue"),
            ("Seeded Task: polish UI", "TASK", "IN_PROGRESS", "MEDIUM", None, None),
            ("Seeded Task: docs", "TASK", "RESOLVED", "LOW", None, None),
            ("Seeded Bug: crash", "BUG", "CLOSED", "CRITICAL", None, None),
            ("Seeded today-due", "TASK", "OPEN", "MEDIUM", str(today), "today -> NOT overdue"),
        ]
        for i, (title, itype, status, prio, due, _note) in enumerate(specs):
            existing = tx.execute("SELECT id FROM issues WHERE workspace_id=? AND title=?",
                                  (ws["id"], title)).fetchone()
            if existing:
                continue
            iid = db.new_id()
            now = db.utcnow_iso()
            tx.execute(
                "INSERT INTO issues (id, workspace_id, project_id, title, description, type, status,"
                " priority, assignee_id, due_date, creator_id, deleted, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, ws["id"], prj["id"], title, f"Seeded issue #{i+1}", itype, status, prio,
                 member["id"] if i == 0 else None, due, admin["id"], 0, now, now))
            add_activity(tx, ws["id"], admin["id"], "ISSUE_CREATED", "issue", iid)

        # comment
        first_issue = tx.execute("SELECT id FROM issues WHERE workspace_id=? AND title=?",
                                 (ws["id"], "Seeded Bug: login flake")).fetchone()
        has_comment = tx.execute("SELECT 1 FROM comments WHERE issue_id=?", (first_issue["id"],)).fetchone()
        if not has_comment:
            cid = db.new_id()
            tx.execute("INSERT INTO comments (id, issue_id, author_id, body, created_at) VALUES (?,?,?,?,?)",
                       (cid, first_issue["id"], member["id"], "Seeded comment: repro steps attached.", db.utcnow_iso()))
            add_activity(tx, ws["id"], member["id"], "COMMENT_ADDED", "comment", cid)

    print(f"Seed complete. db={db.path}")
    print("Credentals (demo only): admin@example.com/admin12345, member@example.com/member12345")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-create seed users/workspace even if DB has data")
    args = parser.parse_args()
    db = DB(DB_PATH)
    sys.exit(seed(db, force=args.force))


if __name__ == "__main__":
    main()
