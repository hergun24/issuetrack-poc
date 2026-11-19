"""Reproduction test for INC-8492: issues due today must NOT be overdue."""

import datetime

from app.api import _overdue


def test_issue_due_today_is_not_overdue():
    """Hotfix requirement: due today (UTC) is NOT overdue until UTC midnight passes."""
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    assert _overdue(today, "OPEN", False) is False, \
        "Defect reproduced: issue due today is incorrectly flagged overdue"
    assert _overdue(today, "IN_PROGRESS", False) is False
    assert _overdue(today, "OPEN", True) is False

    # Past due date must still be overdue (regression guard)
    past = (datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=1)).isoformat()
    assert _overdue(past, "OPEN", False) is True


def test_dashboard_and_filter_consistency_today_due():
    """AC-053: dashboard overdue ids must equal overdue=true filter ids, incl. today-due issues."""
    import os
    import sys
    import tempfile
    sys.path.insert(0, os.getcwd())
    from conftest import make_client, register_and_login, auth
    client, _, _ = make_client()
    tok, _ = register_and_login(client)
    ws = client.post("/api/workspaces", json={"name": "W"}, headers=auth(tok)).json()
    proj = client.post(f"/api/workspaces/{ws['id']}/projects", json={"name": "P"}, headers=auth(tok)).json()
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    past = (datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=1)).isoformat()
