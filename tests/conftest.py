"""Shared test fixtures: fresh DB + TestClient per module."""

import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


def make_client(tmp_path: str = None, disable_ratelimit: bool = True, auto_seed: bool = False):
    db_path = os.path.join(tmp_path or tempfile.mkdtemp(prefix="it-test-"), "test.db")
    app = create_app(db_path, disable_ratelimit=disable_ratelimit, auto_seed=auto_seed)
    return TestClient(app, raise_server_exceptions=False), app, db_path


def unique_suffix() -> str:
    return uuid.uuid4().hex[:6]


def register_and_login(client, email=None, password="password123", display_name="Test User"):
    email = email or f"user-{unique_suffix()}@example.com"
    r = client.post("/api/auth/register", json={"email": email, "password": password, "display_name": display_name})
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    return token, email


def auth(token):
    return {"Authorization": f"Bearer {token}"}
