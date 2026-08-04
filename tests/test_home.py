"""Tests for the home page walking skeleton."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import connect, init_db
from app.main import create_app


def make_client(tmp_path) -> TestClient:
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))
    init_db(conn)
    app = create_app(conn)
    return TestClient(app)


def test_home_renders_zero_state_counts(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/")

    assert resp.status_code == 200
    body = resp.text
    # Zero-state: no words captured yet.
    assert 'data-testid="due-today"' in body
    assert 'data-testid="total-words"' in body
    # Both counts should read zero.
    import re

    due = re.search(r'data-testid="due-today"[^>]*>\s*(\d+)', body)
    total = re.search(r'data-testid="total-words"[^>]*>\s*(\d+)', body)
    assert due and due.group(1) == "0"
    assert total and total.group(1) == "0"


def test_home_includes_htmx(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/")
    assert "htmx" in resp.text.lower()
