"""API integration tests: exercise the REST contract end-to-end via TestClient.

Aligns with 06-API-CONTRACT-REFERENCE.md:
- 400 VALIDATION_ERROR only for malformed JSON body
- 422 VALIDATION_ERROR for semantic validation (limits, enums, formats, relations)
- 401 AUTHENTICATION_FAILED identical body for unknown email / wrong password
- 403 FORBIDDEN when a member lacks admin role
- 404 hides cross-workspace existence; 409 for last-admin / archived-project writes
"""

import datetime
import json

import pytest

from conftest import auth, make_client, register_and_login, unique_suffix

TODAY = str(datetime.date.today())
PAST = str(datetime.date.today() - datetime.timedelta(days=1))
FUTURE = str(datetime.date.today() + datetime.timedelta(days=1))

VALIDATION = 422  # semantic validation status


@pytest.fixture()
def env():
    client, app, db_path = make_client()
    return {"client": client, "app": app, "db_path": db_path}


@pytest.fixture()
def admin(env):
    token, email = register_and_login(env["client"], display_name="Admin A")
    env["admin"] = (token, email)
    return env["admin"]


@pytest.fixture()
def member(env):
    token, email = register_and_login(env["client"], display_name="Member M")
    env["member"] = (token, email)
    return env["member"]


@pytest.fixture()
def workspace(env, admin):
    r = env["client"].post("/api/workspaces", json={"name": f"Int WS {unique_suffix()}"}, headers=auth(admin[0]))
    assert r.status_code == 201, r.text
    env["ws"] = r.json()
    return env["ws"]


def add_member(env, ws, admin_tok, target_email, role="MEMBER"):
    r = env["client"].post(f"/api/workspaces/{ws['id']}/members",
                           json={"email": target_email, "role": role}, headers=auth(admin_tok))
    assert r.status_code == 201, r.text
    return r.json()


def user_id_for(env, token):
    r = env["client"].get("/api/me", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _m_email(c, tok):
    return c.get("/api/me", headers=auth(tok)).json()["email"]


def _make_project(c, tok, ws, name=None, desc=None):
    # Unique name per workspace to keep parallel tests from colliding.
    body = {"name": name or f"proj-{unique_suffix()}"}
    if desc is not None:
        body["description"] = desc
    r = c.post(f"/api/workspaces/{ws['id']}/projects", json=body, headers=auth(tok))
    assert r.status_code == 201, r.text
    return r.json()


def _make_issue(c, tok, ws, proj, **extra):
    """IssueCreate has no `status` field per contract (defaults to OPEN);
    pop a `status` kwarg and PATCH it post-create when caller asks for a
    non-default status."""
    wanted_status = extra.pop("status", None)
    body = {"title": f"issue-{unique_suffix()}", "project_id": proj["id"],
            "type": "TASK", "priority": "MEDIUM"}
    body.update(extra)
    r = c.post(f"/api/workspaces/{ws['id']}/issues", json=body, headers=auth(tok))
    assert r.status_code == 201, r.text
    issue = r.json()
    if wanted_status is not None and issue.get("status") != wanted_status:
        r = c.patch(f"/api/workspaces/{ws['id']}/issues/{issue['id']}",
                    json={"status": wanted_status}, headers=auth(tok))
        assert r.status_code == 200, r.text
        issue = r.json()
    return issue


# ---------------- health ----------------

def test_health(env):
    r = env["client"].get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ---------------- auth ----------------

def test_register_returns_user_only(env):
    c = env["client"]
    email = f"reg-{unique_suffix()}@x.com"
    r = c.post("/api/auth/register", json={"email": email, "password": "password123", "display_name": "R"})
    assert r.status_code == 201
    body = r.json()
    assert set(body.keys()) == {"id", "email", "display_name"}
    assert body["email"] == email and body["display_name"] == "R"


def test_register_semantic_validation(env):
    c = env["client"]
    # short password + empty display_name (valid email) -> 422 with field details
    r = c.post("/api/auth/register", json={"email": "ok@x.com", "password": "short", "display_name": ""})
    assert r.status_code == VALIDATION
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert "password" in fields and "display_name" in fields

    # too-long display name -> 422
    r = c.post("/api/auth/register", json={"email": "ok@x.com", "password": "password123", "display_name": "x" * 101})
    assert r.status_code == VALIDATION


def test_register_unique_email_case_insensitive(env):
    c = env["client"]
    r = c.post("/api/auth/register", json={"email": "same@x.com", "password": "password123", "display_name": "A"})
    assert r.status_code == 201
    r = c.post("/api/auth/register", json={"email": "SAME@X.COM", "password": "password123", "display_name": "B"})
    assert r.status_code == VALIDATION
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    # no duplicate account was created: re-login with A\'s password works
    assert c.post("/api/auth/login", json={"email": "same@x.com", "password": "password123"}).status_code == 200


def test_malformed_json_body_400(env):
    c = env["client"]
    r = c.post("/api/auth/register", content=b"{bad json",
               headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_login_success_and_unknown_email(env):
    c = env["client"]
    tok, email = register_and_login(c)
    r = c.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"token", "user"}
    assert set(body["user"].keys()) == {"id", "email", "display_name"}

    r = c.post("/api/auth/login", json={"email": f"nobody-{unique_suffix()}@x.com", "password": "password123"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTHENTICATION_FAILED"
    assert r.json()["error"]["message"] == "Invalid credentials."


def test_login_wrong_password_same_body(env):
    c = env["client"]
    tok, email = register_and_login(c)
    r = c.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTHENTICATION_FAILED"
    assert r.json()["error"]["message"] == "Invalid credentials."


def test_login_rate_limit_429():
    client, _, _ = make_client(disable_ratelimit=False)
    suffix = unique_suffix()
    last = 0
    for _ in range(50):
        last = client.post("/api/auth/login",
                           json={"email": f"n{suffix}@x.com", "password": "password123"}).status_code
        if last == 429:
            break
    assert last == 429, f"never hit rate limit; last={last}"


def test_logout_returns_204_and_blocks_reuse(env, admin):
    c = env["client"]
    r = c.post("/api/auth/logout", headers=auth(admin[0]))
    assert r.status_code == 204
    r = c.get("/api/me", headers=auth(admin[0]))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    r = c.post("/api/auth/logout", headers=auth(admin[0]))
    assert r.status_code == 401


def test_me_requires_auth(env, admin):
    c, tok = env["client"], admin[0]
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/me", headers=auth("bad-token")).status_code == 401
    r = c.get("/api/me", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401
    r = c.get("/api/me", headers=auth(tok))
    assert r.status_code == 200
    assert set(r.json().keys()) == {"id", "email", "display_name"}


def test_profile_update(env, admin):
    c, tok = env["client"], admin[0]
    r = c.patch("/api/me", json={"display_name": "Renamed"}, headers=auth(tok))
    assert r.status_code == 200
    assert r.json()["display_name"] == "Renamed"
    r = c.patch("/api/me", json={"display_name": ""}, headers=auth(tok))
    assert r.status_code == VALIDATION
    # email is not writable via /me (extra field -> 400 body-shape error)
    r = c.patch("/api/me", json={"display_name": "R2", "email": "new@x.com"}, headers=auth(tok))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------- workspaces / membership ----------------

def test_workspace_create_and_list(env, admin):
    c, tok = env["client"], admin[0]
    r = c.post("/api/workspaces", json={"name": "WS Alpha"}, headers=auth(tok))
    assert r.status_code == 201
    ws = r.json()
    assert set(ws.keys()) == {"id", "name", "role"} and ws["role"] == "ADMIN"
    r = c.get("/api/workspaces", headers=auth(tok))
    assert r.status_code == 200
    assert any(w["id"] == ws["id"] and w["role"] == "ADMIN" for w in r.json()["items"])
    # creator auto-admin membership
    r = c.get(f"/api/workspaces/{ws['id']}/members", headers=auth(tok))
    assert r.status_code == 200
    assert r.json()["items"][0]["role"] == "ADMIN"


def test_workspace_name_validation(env, admin):
    c, tok = env["client"], admin[0]
    for bad in ["", "   ", "x" * 101]:
        r = c.post("/api/workspaces", json={"name": bad}, headers=auth(tok))
        assert r.status_code == VALIDATION, f"name={bad!r} -> {r.status_code} {r.text}"


def test_add_member_flow(env, admin, member, workspace):
    c, ws, admin_tok, member_tok = env["client"], workspace, admin[0], member[0]
    r = c.post(f"/api/workspaces/{ws['id']}/members",
               json={"email": member[1], "role": "MEMBER"}, headers=auth(admin_tok))
    assert r.status_code == 201, r.text
    # duplicate member -> 422
    r = c.post(f"/api/workspaces/{ws['id']}/members",
               json={"email": member[1], "role": "MEMBER"}, headers=auth(admin_tok))
    assert r.status_code == VALIDATION
    # non-admin cannot add -> 403
    r = c.post(f"/api/workspaces/{ws['id']}/members",
               json={"email": "stranger@x.com", "role": "MEMBER"}, headers=auth(member_tok))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"
    # unknown email -> 422 (generic; no account created)
    r = c.post(f"/api/workspaces/{ws['id']}/members",
               json={"email": f"unk-{unique_suffix()}@x.com", "role": "MEMBER"}, headers=auth(admin_tok))
    assert r.status_code == VALIDATION
    # invalid role enum -> 422
    r = c.post(f"/api/workspaces/{ws['id']}/members",
               json={"email": member[1], "role": "SUPER"}, headers=auth(admin_tok))
    assert r.status_code == VALIDATION


def test_member_role_management(env, admin, member, workspace):
    c, ws, admin_tok, member_tok = env["client"], workspace, admin[0], member[0]
    mrow = add_member(env, ws, admin_tok, member[1])
    mid = mrow["user_id"]
    r = c.patch(f"/api/workspaces/{ws['id']}/members/{mid}", json={"role": "ADMIN"}, headers=auth(admin_tok))
    assert r.status_code == 200
    assert r.json()["role"] == "ADMIN"
    # demote back to MEMBER so member_tok is non-admin again, then 403 on role mgmt
    r2 = c.patch(f"/api/workspaces/{ws['id']}/members/{mid}", json={"role": "MEMBER"}, headers=auth(admin_tok))
    assert r2.status_code == 200
    # non-admin caller (member_tok, now MEMBER role) cannot manage roles -> 403
    r = c.patch(f"/api/workspaces/{ws['id']}/members/{mid}", json={"role": "ADMIN"}, headers=auth(member_tok))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"
    # unknown user id -> 404
    r = c.patch(f"/api/workspaces/{ws['id']}/members/ghost-id", json={"role": "ADMIN"}, headers=auth(admin_tok))
    assert r.status_code == 404


def test_last_admin_invariant(env, admin, workspace):
    c, ws, admin_tok = env["client"], workspace, admin[0]
    me_id = user_id_for(env, admin_tok)
    r = c.patch(f"/api/workspaces/{ws['id']}/members/{me_id}", json={"role": "MEMBER"}, headers=auth(admin_tok))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"
    r = c.delete(f"/api/workspaces/{ws['id']}/members/{me_id}", headers=auth(admin_tok))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"


def test_member_email_hidden_from_non_admin(env, admin, member, workspace):
    c, ws, admin_tok, member_tok = env["client"], workspace, admin[0], member[0]
    add_member(env, ws, admin_tok, member[1])
    r = c.get(f"/api/workspaces/{ws['id']}/members", headers=auth(member_tok))
    assert r.status_code == 200
    for m in r.json()["items"]:
        assert m.get("email") is None, f"email leaked to non-admin: {m}"
    r = c.get(f"/api/workspaces/{ws['id']}/members", headers=auth(admin_tok))
    emails = {m.get("email") for m in r.json()["items"]}
    assert admin[1] in emails and member[1] in emails


def test_member_remove_flow(env, admin, member, workspace):
    c, ws, admin_tok, member_tok = env["client"], workspace, admin[0], member[0]
    add_member(env, ws, admin_tok, member[1])
    mid = user_id_for(env, member_tok)
    r = c.delete(f"/api/workspaces/{ws['id']}/members/{mid}", headers=auth(admin_tok))
    assert r.status_code == 204
    # removed member -> 404 on second delete
    r = c.delete(f"/api/workspaces/{ws['id']}/members/{mid}", headers=auth(admin_tok))
    assert r.status_code == 404


def test_member_removal_unassigns_issues(env, admin, workspace):
    c, ws, admin_tok = env["client"], workspace, admin[0]
    m_tok, m_email = register_and_login(c, display_name="M2")
    add_member(env, ws, admin_tok, m_email)
    mid = user_id_for(env, m_tok)
    proj = _make_project(c, admin_tok, ws)
    iss = _make_issue(c, admin_tok, ws, proj, assignee_id=mid)
    assert iss["assignee_id"] == mid
    r = c.delete(f"/api/workspaces/{ws['id']}/members/{mid}", headers=auth(admin_tok))
    assert r.status_code == 204
    r = c.get(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", headers=auth(admin_tok))
    assert r.json()["assignee_id"] is None
    acts = [a["action"] for a in
            c.get(f"/api/workspaces/{ws['id']}/activity?page=1&page_size=100", headers=auth(admin_tok)).json()["items"]]
    assert "MEMBER_ISSUES_UNASSIGNED" in acts and "MEMBER_REMOVED" in acts


# ---------------- projects ----------------

def test_project_lifecycle(env, admin, workspace):
    c, tok = env["client"], admin[0]
    ws = workspace
    p = _make_project(c, tok, ws, name="P1", desc="hello")
    assert p["description"] == "hello" and p["archived"] is False
    assert set(p.keys()) >= {"id", "workspace_id", "name", "description", "archived", "created_at", "updated_at"}
    r = c.get(f"/api/workspaces/{ws['id']}/projects/{p['id']}", headers=auth(tok))
    assert r.status_code == 200
    # name validation on update
    r = c.patch(f"/api/workspaces/{ws['id']}/projects/{p['id']}", json={"name": "   "}, headers=auth(tok))
    assert r.status_code == VALIDATION

    # archive -> issue writes -> 409
    p2 = _make_project(c, tok, ws, name="P2")
    r = c.patch(f"/api/workspaces/{ws['id']}/projects/{p2['id']}", json={"archived": True}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["archived"] is True
    r = c.post(f"/api/workspaces/{ws['id']}/issues",
               json={"title": "x", "project_id": p2["id"]}, headers=auth(tok))
    assert r.status_code == 409
    r = c.patch(f"/api/workspaces/{ws['id']}/projects/{p2['id']}", json={"archived": False}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["archived"] is False

    # non-admin cannot patch projects -> 403
    m_tok, _ = register_and_login(c, display_name="P")
    add_member(env, ws, tok, _m_email(c, m_tok))
    r = c.patch(f"/api/workspaces/{ws['id']}/projects/{p['id']}", json={"name": "Hack"}, headers=auth(m_tok))
    assert r.status_code == 403


# ---------------- issues ----------------

def test_issue_create_and_get(env, admin, workspace):
    c, ws, tok = env["client"], workspace, admin[0]
    proj = _make_project(c, tok, ws)
    iss = _make_issue(c, tok, ws, proj, due_date=PAST, description="d")
    assert iss["status"] == "OPEN" and iss["type"] == "TASK"
    assert iss["assignee_id"] is None and iss["due_date"] == PAST
    r = c.get(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", headers=auth(tok))
    assert r.status_code == 200 and r.json()["title"] == iss["title"]
    # defaults
    iss2 = c.post(f"/api/workspaces/{ws['id']}/issues",
                  json={"title": "t", "project_id": proj["id"]}, headers=auth(tok)).json()
    assert iss2["type"] == "BUG" and iss2["priority"] == "MEDIUM" and iss2["status"] == "OPEN"
    # validation: empty title
    r = c.post(f"/api/workspaces/{ws['id']}/issues",
               json={"title": "", "project_id": proj["id"]}, headers=auth(tok))
    assert r.status_code == VALIDATION
    # unknown project -> 404
    r = c.post(f"/api/workspaces/{ws['id']}/issues",
               json={"title": "t", "project_id": "no-such-project"}, headers=auth(tok))
    assert r.status_code == 404
    # bad due_date -> 422
    for bad in ["2021-13-01", "2021-01-01T00:00:00Z", "01-01-2021"]:
        r = c.post(f"/api/workspaces/{ws['id']}/issues",
                   json={"title": "t", "project_id": proj["id"], "due_date": bad}, headers=auth(tok))
        assert r.status_code == VALIDATION, f"due_date={bad} -> {r.status_code}"
    # bad enum values -> 422
    r = c.post(f"/api/workspaces/{ws['id']}/issues",
               json={"title": "t", "project_id": proj["id"], "type": "EPIC"}, headers=auth(tok))
    assert r.status_code == VALIDATION
    r = c.post(f"/api/workspaces/{ws['id']}/issues",
               json={"title": "t", "project_id": proj["id"], "priority": "SUPER"}, headers=auth(tok))
    assert r.status_code == VALIDATION
    # past due dates are valid
    r = c.post(f"/api/workspaces/{ws['id']}/issues",
               json={"title": "t", "project_id": proj["id"], "due_date": PAST}, headers=auth(tok))
    assert r.status_code == 201


def test_issue_patch_events_and_rules(env, admin, workspace, member):
    c, ws, tok = env["client"], workspace, admin[0]
    add_member(env, ws, tok, member[1])
    mid = user_id_for(env, member[0])
    proj = _make_project(c, tok, ws)
    iss = _make_issue(c, tok, ws, proj)

    def all_actions():
        items, pageno = [], 1
        while True:
            page = c.get(f"/api/workspaces/{ws['id']}/activity?page={pageno}&page_size=100",
                         headers=auth(tok)).json()
            items.extend(page["items"])
            if pageno >= page["total_pages"]:
                break
            pageno += 1
        return [a["action"] for a in items]  # newest first

    def actions_since(total_before):
        """All actions recorded after `total_before` total_items existed,
        oldest -> newest order."""
        acts = all_actions()
        new_acts = acts[:total_before]  # the `total_before` newest rows
        return list(reversed(new_acts))

    # baseline
    n0 = c.get(f"/api/workspaces/{ws['id']}/activity?page=1&page_size=1",
               headers=auth(tok)).json()["total_items"]

    # assignee-only change -> ISSUE_ASSIGNED
    r = c.patch(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", json={"assignee_id": mid}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["assignee_id"] == mid
    assert actions_since(n0)[-1] == "ISSUE_ASSIGNED"

    # assignee clear -> ISSUE_UNASSIGNED
    r = c.patch(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", json={"assignee_id": None}, headers=auth(tok))
    assert r.json()["assignee_id"] is None
    assert actions_since(n0)[-1] == "ISSUE_UNASSIGNED"

    # status-only -> ISSUE_STATUS_CHANGED
    r = c.patch(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", json={"status": "IN_PROGRESS"}, headers=auth(tok))
    assert actions_since(n0)[-1] == "ISSUE_STATUS_CHANGED"

    # other-field change -> ISSUE_UPDATED
    r = c.patch(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", json={"title": "renamed"}, headers=auth(tok))
    assert actions_since(n0)[-1] == "ISSUE_UPDATED"

    # no-op -> no new event
    n1 = c.get(f"/api/workspaces/{ws['id']}/activity?page=1&page_size=100", headers=auth(tok)).json()["total_items"]
    r = c.patch(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", json={"title": "renamed"}, headers=auth(tok))
    assert r.status_code == 200
    n2 = c.get(f"/api/workspaces/{ws['id']}/activity?page=1&page_size=100", headers=auth(tok)).json()["total_items"]
    assert n2 == n1

    # all 16 status transitions valid
    for target in ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED", "OPEN"]:
        r = c.patch(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", json={"status": target}, headers=auth(tok))
        assert r.status_code == 200 and r.json()["status"] == target

    # assign non-member -> 422
    x_tok, x_email = register_and_login(c, display_name="X")
    x_id = user_id_for(env, x_tok)
    r = c.patch(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", json={"assignee_id": x_id}, headers=auth(tok))
    assert r.status_code == VALIDATION and r.json()["error"]["code"] == "VALIDATION_ERROR"

    # archived project -> issue writes 409
    p2 = _make_project(c, tok, ws, name="Arch")
    iss2 = _make_issue(c, tok, ws, p2)
    c.patch(f"/api/workspaces/{ws['id']}/projects/{p2['id']}", json={"archived": True}, headers=auth(tok))
    assert c.patch(f"/api/workspaces/{ws['id']}/issues/{iss2['id']}", json={"status": "CLOSED"},
                   headers=auth(tok)).status_code == 409
    assert c.post(f"/api/workspaces/{ws['id']}/issues/{iss2['id']}/comments", json={"body": "hi"},
                  headers=auth(tok)).status_code == 409
    # but issue detail still readable
    assert c.get(f"/api/workspaces/{ws['id']}/issues/{iss2['id']}", headers=auth(tok)).status_code == 200


def test_issue_list_filters_and_pagination(env, admin, workspace):
    c, ws, tok = env["client"], workspace, admin[0]
    proj = _make_project(c, tok, ws)
    for i in range(12):
        _make_issue(c, tok, ws, proj, title=f"pg-{i}",
                    due_date=PAST if i % 2 == 0 else None,
                    priority=["LOW", "MEDIUM", "HIGH", "CRITICAL"][i % 4])
    r = c.get(f"/api/workspaces/{ws['id']}/issues?page=1&page_size=5", headers=auth(tok))
    assert r.status_code == 200
    j = r.json()
    assert j["total_items"] == 12 and j["page_size"] == 5 and j["total_pages"] == 3
    assert len(j["items"]) == 5

    r = c.get(f"/api/workspaces/{ws['id']}/issues?priority=HIGH&page=1&page_size=100", headers=auth(tok))
    items = r.json()["items"]
    assert len(items) == 3 and all(i["priority"] == "HIGH" for i in items)

    r = c.get(f"/api/workspaces/{ws['id']}/issues?overdue=true&page=1&page_size=100", headers=auth(tok))
    items = r.json()["items"]
    assert len(items) == 6 and all(i["due_date"] == PAST and i["status"] not in ("RESOLVED", "CLOSED") for i in items)

    r = c.get(f"/api/workspaces/{ws['id']}/issues?overdue=false&page=1&page_size=100", headers=auth(tok))
    assert r.json()["total_items"] == 6

    # out-of-range page -> empty items, still 200
    r = c.get(f"/api/workspaces/{ws['id']}/issues?page=99&page_size=5", headers=auth(tok))
    assert r.status_code == 200 and r.json()["items"] == [] and r.json()["total_items"] == 12

    # invalid page/page_size -> 422
    for q in ["page=0", "page_size=0", "page=abc", "page_size=101"]:
        r = c.get(f"/api/workspaces/{ws['id']}/issues?{q}", headers=auth(tok))
        assert r.status_code in (400, VALIDATION), f"{q} -> {r.status_code} {r.text}"

    # invalid enum filter -> 422
    r = c.get(f"/api/workspaces/{ws['id']}/issues?status=WEIRD", headers=auth(tok))
    assert r.status_code in (400, VALIDATION)

    # defaults: page=1, page_size=20
    r = c.get(f"/api/workspaces/{ws['id']}/issues", headers=auth(tok))
    assert r.json()["page"] == 1 and r.json()["page_size"] == 20

    # tenant isolation: other workspace empty
    other = c.post("/api/workspaces", json={"name": "Other"}, headers=auth(tok)).json()
    assert c.get(f"/api/workspaces/{other['id']}/issues", headers=auth(tok)).json()["total_items"] == 0


def test_issue_delete_tenant_scoped(env, admin, workspace):
    c, ws, tok = env["client"], workspace, admin[0]
    proj = _make_project(c, tok, ws)
    iss = _make_issue(c, tok, ws, proj)
    other = c.post("/api/workspaces", json={"name": "Elsewhere"}, headers=auth(tok)).json()
    # foreign workspace -> 404 (existence hidden)
    r = c.delete(f"/api/workspaces/{other['id']}/issues/{iss['id']}", headers=auth(tok))
    assert r.status_code == 404
    r = c.delete(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", headers=auth(tok))
    assert r.status_code == 204
    # deleted issue -> 404 on detail, gone from lists
    assert c.get(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", headers=auth(tok)).status_code == 404
    assert c.get(f"/api/workspaces/{ws['id']}/issues", headers=auth(tok)).json()["total_items"] == 0
    # delete again -> 404
    assert c.delete(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", headers=auth(tok)).status_code == 404
    # non-admin delete -> 403
    m_tok, _ = register_and_login(c, display_name="Del")
    add_member(env, ws, tok, _m_email(c, m_tok))
    proj2 = _make_project(c, tok, ws, name="P2")
    iss2 = _make_issue(c, tok, ws, proj2)
    assert c.delete(f"/api/workspaces/{ws['id']}/issues/{iss2['id']}", headers=auth(m_tok)).status_code == 403


def test_issue_cross_workspace_isolation(env, admin):
    c, tok = env["client"], admin[0]
    ws1 = c.post("/api/workspaces", json={"name": "W1"}, headers=auth(tok)).json()
    ws2 = c.post("/api/workspaces", json={"name": "W2"}, headers=auth(tok)).json()
    p1 = _make_project(c, tok, ws1)
    iss1 = _make_issue(c, tok, ws1, p1, title="secret-iss")
    assert c.get(f"/api/workspaces/{ws2['id']}/issues/{iss1['id']}", headers=auth(tok)).status_code == 404
    assert c.get(f"/api/workspaces/{ws2['id']}/issues", headers=auth(tok)).json()["total_items"] == 0
    assert c.get(f"/api/workspaces/{ws2['id']}/projects/{p1['id']}", headers=auth(tok)).status_code == 404


# ---------------- comments ----------------

def test_comments_flow(env, admin, workspace):
    c, ws, tok = env["client"], workspace, admin[0]
    proj = _make_project(c, tok, ws)
    iss = _make_issue(c, tok, ws, proj)
    r = c.post(f"/api/workspaces/{ws['id']}/issues/{iss['id']}/comments", json={"body": "first"}, headers=auth(tok))
    assert r.status_code == 201
    body = r.json()
    assert set(body.keys()) == {"id", "issue_id", "author_id", "body", "created_at"}
    r = c.get(f"/api/workspaces/{ws['id']}/issues/{iss['id']}/comments", headers=auth(tok))
    assert r.status_code == 200 and r.json()["total_items"] == 1
    assert r.json()["items"][0]["body"] == "first"
    # comment on another issue -> separate
    iss2 = _make_issue(c, tok, ws, proj)
    r = c.post(f"/api/workspaces/{ws['id']}/issues/{iss2['id']}/comments", json={"body": "x"}, headers=auth(tok))
    assert r.status_code == 201
    got = c.get(f"/api/workspaces/{ws['id']}/issues/{iss['id']}/comments",
                headers=auth(tok)).json()
    assert got["total_items"] == 1
    # empty body -> 422; too-long -> 422; max-length ok
    assert c.post(f"/api/workspaces/{ws['id']}/issues/{iss['id']}/comments",
                  json={"body": "   "}, headers=auth(tok)).status_code == VALIDATION
    assert c.post(f"/api/workspaces/{ws['id']}/issues/{iss['id']}/comments",
                  json={"body": "x" * 2001}, headers=auth(tok)).status_code == VALIDATION
    assert c.post(f"/api/workspaces/{ws['id']}/issues/{iss['id']}/comments",
                  json={"body": "x" * 2000}, headers=auth(tok)).status_code == 201
    # comment on deleted issue -> 404
    iss3 = _make_issue(c, tok, ws, proj)
    c.delete(f"/api/workspaces/{ws['id']}/issues/{iss3['id']}", headers=auth(tok))
    assert c.post(f"/api/workspaces/{ws['id']}/issues/{iss3['id']}/comments",
                  json={"body": "nope"}, headers=auth(tok)).status_code == 404


# ---------------- activity ----------------

def test_activity_flow(env, admin, workspace):
    c, ws, tok = env["client"], workspace, admin[0]
    proj = _make_project(c, tok, ws)
    iss = _make_issue(c, tok, ws, proj)
    c.patch(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", json={"status": "IN_PROGRESS"}, headers=auth(tok))
    c.post(f"/api/workspaces/{ws['id']}/issues/{iss['id']}/comments", json={"body": "c"}, headers=auth(tok))

    r = c.get(f"/api/workspaces/{ws['id']}/activity?page=1&page_size=100", headers=auth(tok))
    assert r.status_code == 200
    j = r.json()
    assert set(j.keys()) == {"items", "page", "page_size", "total_items", "total_pages"}
    acts = [a["action"] for a in j["items"]]
    for expected in ["WORKSPACE_CREATED", "PROJECT_CREATED", "ISSUE_CREATED",
                     "ISSUE_STATUS_CHANGED", "COMMENT_ADDED"]:
        assert expected in acts, f"missing {expected}"
    # newest first
    ts = [a["created_at"] for a in j["items"]]
    assert ts == sorted(ts, reverse=True)
    # item shape
    it = j["items"][0]
    assert set(it.keys()) == {"id", "workspace_id", "actor_id", "action",
                              "target_type", "target_id", "created_at"}
    # out of range page -> empty
    r = c.get(f"/api/workspaces/{ws['id']}/activity?page=99&page_size=2", headers=auth(tok))
    assert r.status_code == 200 and r.json()["items"] == []


def test_activity_vocab_all_sixteen(env, admin, workspace):
    c, ws, tok = env["client"], workspace, admin[0]
    proj = _make_project(c, tok, ws)
    m_tok, m_email = register_and_login(c, display_name="M3")
    add_member(env, ws, tok, m_email)
    mid = user_id_for(env, m_tok)
    iss = _make_issue(c, tok, ws, proj, assignee_id=mid)
    c.patch(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", json={"status": "IN_PROGRESS"}, headers=auth(tok))
    c.patch(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", json={"title": "t2"}, headers=auth(tok))
    c.patch(f"/api/workspaces/{ws['id']}/issues/{iss['id']}", json={"assignee_id": None}, headers=auth(tok))
    iss2 = _make_issue(c, tok, ws, proj)
    c.post(f"/api/workspaces/{ws['id']}/issues/{iss2['id']}/comments", json={"body": "cc"}, headers=auth(tok))
    c.delete(f"/api/workspaces/{ws['id']}/issues/{iss2['id']}", headers=auth(tok))
    p2 = _make_project(c, tok, ws, name="P2")
    c.patch(f"/api/workspaces/{ws['id']}/projects/{p2['id']}", json={"name": "P2r"}, headers=auth(tok))
    c.patch(f"/api/workspaces/{ws['id']}/projects/{p2['id']}", json={"archived": True}, headers=auth(tok))
    c.patch(f"/api/workspaces/{ws['id']}/projects/{p2['id']}", json={"archived": False}, headers=auth(tok))
    r = c.patch(f"/api/workspaces/{ws['id']}/members/{mid}", json={"role": "ADMIN"}, headers=auth(tok))
    assert r.status_code == 200
    r = c.patch(f"/api/workspaces/{ws['id']}/members/{mid}", json={"role": "MEMBER"}, headers=auth(tok))
    assert r.status_code == 200
    # member with assigned issues removed -> MEMBER_ISSUES_UNASSIGNED + MEMBER_REMOVED
    _make_issue(c, tok, ws, proj, assignee_id=mid)
    assert c.delete(f"/api/workspaces/{ws['id']}/members/{mid}", headers=auth(tok)).status_code == 204

    # page_size max is 100 per contract; page through workspace activity
    seen, pageno = [], 1
    while True:
        page = c.get(f"/api/workspaces/{ws['id']}/activity?page={pageno}&page_size=100",
                     headers=auth(tok)).json()
        assert "items" in page, page
        seen.extend(a["action"] for a in page["items"])
        if pageno >= page["total_pages"]:
            break
        pageno += 1
    actions = set(seen)
    expected = {"WORKSPACE_CREATED", "MEMBER_ADDED", "MEMBER_REMOVED", "MEMBER_ROLE_CHANGED",
                "MEMBER_ISSUES_UNASSIGNED", "PROJECT_CREATED", "PROJECT_UPDATED",
                "PROJECT_ARCHIVED", "PROJECT_UNARCHIVED", "ISSUE_CREATED", "ISSUE_UPDATED",
                "ISSUE_STATUS_CHANGED", "ISSUE_ASSIGNED", "ISSUE_UNASSIGNED",
                "ISSUE_DELETED", "COMMENT_ADDED"}
    assert expected - actions == set(), f"missing actions: {expected - actions}"
    # no non-canonical action leaked
    for a in actions:
        assert a in expected, f"non-canonical action: {a}"


# ---------------- dashboard ----------------

def test_dashboard_counts_and_overdue_rule(env, admin, workspace):
    c, ws, tok = env["client"], workspace, admin[0]
    p = _make_project(c, tok, ws, name="Live")
    p_arch = _make_project(c, tok, ws, name="Arch")
    # NOTE: p_arch is archived AFTER all issues are created so that issue
    # creation against p_arch does not hit the 409 "read-only" guard.

    # Create all issues while project is still active (per contract: writes
    # are rejected on archived projects, so we archive p_arch only AFTER its
    # issue is created).
    open_ = _make_issue(c, tok, ws, p, status="OPEN", priority="CRITICAL", due_date=PAST)
    _make_issue(c, tok, ws, p, status="OPEN", priority="HIGH", due_date=None)
    _make_issue(c, tok, ws, p, status="RESOLVED", priority="MEDIUM", due_date=PAST)
    _make_issue(c, tok, ws, p, status="CLOSED", priority="MEDIUM", due_date=PAST)
    _make_issue(c, tok, ws, p_arch, status="OPEN", priority="LOW", due_date=PAST)
    # Now mark p_arch archived so its issue is excluded from dashboard aggregates
    c.patch(f"/api/workspaces/{ws['id']}/projects/{p_arch['id']}", json={"archived": True}, headers=auth(tok))

    d = c.get(f"/api/workspaces/{ws['id']}/dashboard", headers=auth(tok)).json()
    assert d["status_totals"] == {"OPEN": 2, "IN_PROGRESS": 0, "RESOLVED": 1, "CLOSED": 1}
    assert d["priority_totals"] == {"LOW": 0, "MEDIUM": 2, "HIGH": 1, "CRITICAL": 1}
    assert d["overdue_count"] == 1
    assert d["overdue_issue_ids"] == [open_["id"]]

    # closing the overdue issue drops the count
    c.patch(f"/api/workspaces/{ws['id']}/issues/{open_['id']}", json={"status": "CLOSED"}, headers=auth(tok))
    d = c.get(f"/api/workspaces/{ws['id']}/dashboard", headers=auth(tok)).json()
    assert d["overdue_count"] == 0

    # due today is NOT overdue
    _make_issue(c, tok, ws, p, status="OPEN", priority="HIGH", due_date=TODAY)
    d = c.get(f"/api/workspaces/{ws['id']}/dashboard", headers=auth(tok)).json()
    assert d["overdue_count"] == 0

    # deleted issues vanish from totals
    alive = _make_issue(c, tok, ws, p, status="OPEN", priority="MEDIUM", due_date=PAST)
    d0 = c.get(f"/api/workspaces/{ws['id']}/dashboard", headers=auth(tok)).json()
    assert d0["overdue_count"] == 1
    c.delete(f"/api/workspaces/{ws['id']}/issues/{alive['id']}", headers=auth(tok))
    d1 = c.get(f"/api/workspaces/{ws['id']}/dashboard", headers=auth(tok)).json()
    assert d1["overdue_count"] == 0
    assert d1["status_totals"]["OPEN"] == d0["status_totals"]["OPEN"] - 1


def test_dashboard_isolation(env, admin):
    c, tok = env["client"], admin[0]
    ws1 = c.post("/api/workspaces", json={"name": "W1"}, headers=auth(tok)).json()
    ws2 = c.post("/api/workspaces", json={"name": "W2"}, headers=auth(tok)).json()
    p = _make_project(c, tok, ws1)
    _make_issue(c, tok, ws1, p, due_date=PAST)
    d1 = c.get(f"/api/workspaces/{ws1['id']}/dashboard", headers=auth(tok)).json()
    d2 = c.get(f"/api/workspaces/{ws2['id']}/dashboard", headers=auth(tok)).json()
    assert d1["overdue_count"] == 1
    assert d2["overdue_count"] == 0
    assert d2["status_totals"] == {"OPEN": 0, "IN_PROGRESS": 0, "RESOLVED": 0, "CLOSED": 0}
    assert d2["priority_totals"] == {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}


# ---------------- errors / misc ----------------

def test_unknown_endpoint_error_shape(env):
    r = env["client"].get("/api/definitely-not-real")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "NOT_FOUND", "message": "Resource not found."}}


def test_method_not_allowed_shape(env):
    r = env["client"].delete("/api/health")
    assert r.status_code in (404, 405)
    assert "error" in r.json()


def test_unknown_resources_404(env, admin):
    c, tok = env["client"], admin[0]
    ws = c.post("/api/workspaces", json={"name": "W"}, headers=auth(tok)).json()
    r = c.get(f"/api/workspaces/{ws['id']}/issues/ghost-issue-id", headers=auth(tok))
    assert r.status_code == 404
    r = c.get("/api/workspaces/ghost-ws-id/projects", headers=auth(tok))
    assert r.status_code == 404
    r = c.get(f"/api/workspaces/{ws['id']}/projects/ghost-pid", headers=auth(tok))
    assert r.status_code == 404


def test_500_shape_never_leaks_details():
    """Verify the global Exception handler returns the 500 shape without leaking internals."""
    client, app, _ = make_client()
    import asyncio
    from starlette.datastructures import URL

    handler = None
    for exc_type, fn in list(app.exception_handlers.items()):
        if exc_type is Exception:
            handler = fn
            break
    assert handler is not None, "global Exception handler not registered"

    class FakeReq:
        url = URL("http://t/api/x")

    loop = asyncio.new_event_loop()
    try:
        resp = loop.run_until_complete(handler(FakeReq(), RuntimeError("secret-internal-value")))
    finally:
        loop.close()

    body = resp.body
    if hasattr(body, "read"):
        body = body.read()
    parsed = json.loads(body)
    assert parsed == {"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}}
    assert "secret-internal-value" not in json.dumps(parsed)
