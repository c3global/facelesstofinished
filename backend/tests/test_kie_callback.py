"""Tests for the KIE webhook callback route (HMAC verification, replay guard)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from routes.kie_callback import build_router, verify_kie_signature  # noqa: E402


# ---------- helpers ------------------------------------------------------


def _sign(task_id: str, timestamp: str, key: str) -> str:
    return base64.b64encode(
        hmac.new(key.encode(), f"{task_id}.{timestamp}".encode(), hashlib.sha256).digest()
    ).decode()


class _FakeCollection:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def update_one(self, filt, update, upsert=False):  # noqa: ARG002
        self.calls.append({"filter": filt, "update": update, "upsert": upsert})
        return None


class _FakeDB:
    def __init__(self) -> None:
        self.kie_tasks = _FakeCollection()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("KIE_WEBHOOK_HMAC_KEY", "test-hmac-secret")
    app = FastAPI()
    db = _FakeDB()
    app.include_router(build_router(db), prefix="/api")
    app.state._db = db  # expose to assertions
    return TestClient(app), db


# ---------- unit tests: signature helper --------------------------------


def test_verify_signature_success():
    ts = str(int(time.time()))
    task_id = "task_a"
    key = "s"
    sig = _sign(task_id, ts, key)
    assert verify_kie_signature(task_id, ts, sig, key) is True


def test_verify_signature_rejects_wrong_key():
    ts = str(int(time.time()))
    sig = _sign("task_a", ts, "s")
    assert verify_kie_signature("task_a", ts, sig, "different-key") is False


def test_verify_signature_rejects_missing_inputs():
    assert verify_kie_signature("", "1", "sig", "k") is False
    assert verify_kie_signature("t", "", "sig", "k") is False
    assert verify_kie_signature("t", "1", "", "k") is False
    assert verify_kie_signature("t", "1", "sig", "") is False


# ---------- webhook route tests -----------------------------------------


def test_webhook_rejects_missing_headers(client):
    c, _db = client
    r = c.post("/api/kie/webhook", json={"data": {"task_id": "x"}})
    assert r.status_code == 401


def test_webhook_rejects_stale_timestamp(client):
    c, _db = client
    old_ts = str(int(time.time()) - 10_000)
    sig = _sign("task_stale", old_ts, "test-hmac-secret")
    r = c.post(
        "/api/kie/webhook",
        json={"data": {"task_id": "task_stale", "state": "success"}},
        headers={"X-Webhook-Timestamp": old_ts, "X-Webhook-Signature": sig},
    )
    assert r.status_code == 401
    assert "stale" in r.json()["detail"]


def test_webhook_rejects_bad_signature(client):
    c, _db = client
    ts = str(int(time.time()))
    r = c.post(
        "/api/kie/webhook",
        json={"data": {"task_id": "task_bad", "state": "success"}},
        headers={"X-Webhook-Timestamp": ts, "X-Webhook-Signature": "not-a-real-signature"},
    )
    assert r.status_code == 401


def test_webhook_rejects_missing_data_block(client):
    c, _db = client
    ts = str(int(time.time()))
    sig = _sign("task_x", ts, "test-hmac-secret")
    r = c.post(
        "/api/kie/webhook",
        json={"nope": True},
        headers={"X-Webhook-Timestamp": ts, "X-Webhook-Signature": sig},
    )
    assert r.status_code == 400


def test_webhook_accepts_valid_and_persists(client):
    c, db = client
    ts = str(int(time.time()))
    task_id = "task_ok"
    sig = _sign(task_id, ts, "test-hmac-secret")
    r = c.post(
        "/api/kie/webhook",
        json={
            "code": 200,
            "data": {
                "task_id": task_id,
                "state": "success",
                "resultJson": '{"resultUrls":["https://ex/final.mp4"]}',
                "creditsConsumed": 42,
            },
        },
        headers={"X-Webhook-Timestamp": ts, "X-Webhook-Signature": sig},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert len(db.kie_tasks.calls) == 1
    call = db.kie_tasks.calls[0]
    assert call["filter"] == {"task_id": task_id}
    stored = call["update"]["$set"]
    assert stored["task_id"] == task_id
    assert stored["state"] == "success"
    assert stored["callback_data"]["creditsConsumed"] == 42


def test_webhook_returns_503_when_hmac_key_missing(monkeypatch):
    monkeypatch.delenv("KIE_WEBHOOK_HMAC_KEY", raising=False)
    app = FastAPI()
    app.include_router(build_router(_FakeDB()), prefix="/api")
    c = TestClient(app)
    r = c.post(
        "/api/kie/webhook",
        json={"data": {"task_id": "x"}},
        headers={"X-Webhook-Timestamp": str(int(time.time())), "X-Webhook-Signature": "sig"},
    )
    assert r.status_code == 503


def test_webhook_idempotent_on_duplicate_delivery(client):
    """Two identical deliveries should both succeed with the same upsert."""
    c, db = client
    ts = str(int(time.time()))
    task_id = "task_dup"
    sig = _sign(task_id, ts, "test-hmac-secret")
    body = {"code": 200, "data": {"task_id": task_id, "state": "success"}}
    headers = {"X-Webhook-Timestamp": ts, "X-Webhook-Signature": sig}
    r1 = c.post("/api/kie/webhook", json=body, headers=headers)
    r2 = c.post("/api/kie/webhook", json=body, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert len(db.kie_tasks.calls) == 2
    # Both writes target the same task_id; upsert semantics ensure the
    # second is a no-op state-wise even though we recorded 2 calls in the
    # fake.
    assert db.kie_tasks.calls[0]["filter"] == db.kie_tasks.calls[1]["filter"]
