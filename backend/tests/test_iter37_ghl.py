"""Iteration 37 — Group F: GoHighLevel (GHL) outbound integration tests.

Covers:
  - /api/admin/ghl/status — does not leak URL, only host
  - /api/admin/ghl/test — 503 when not configured / 200 + sentinel when on
  - /api/admin/ghl/push-buyer — 400/404/503 negative paths
  - Live push end-to-end via mock server (pinball + appsumo)
  - Failure handling (activity log `ghl_push_failed`)
  - Custom auth header propagation

The test orchestrates env mutation + supervisor restart + a tiny mock HTTP
server in `mock_ghl_server.py`. After the suite finishes, env is restored.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import jwt
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Backend script runs from /app/backend/tests, frontend env lives in /app/frontend/.env
    env_path = Path("/app/frontend/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

ENV_FILE = Path("/app/backend/.env")
MOCK_PORT = 9989
MOCK_OUT = "/tmp/ghl_test_99.json"
ADMIN_EMAIL = "drcharitycampbell@gmail.com"
JWT_SECRET = "2a8f1ec39cd5b67a9e1d04ee2c7c3b6d4f0e2a9b8c5d7e3f1a6c9b4d8e2f0a7c"


# --------------------------- helpers ---------------------------

def _read_env() -> dict[str, str]:
    out = {}
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _write_env(updates: dict[str, str]):
    lines = ENV_FILE.read_text().splitlines()
    keys_seen = set()
    new_lines = []
    for line in lines:
        if "=" in line and not line.startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}")
                keys_seen.add(k)
                continue
        new_lines.append(line)
    for k, v in updates.items():
        if k not in keys_seen:
            new_lines.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(new_lines) + "\n")


def _restart_backend():
    subprocess.run(["sudo", "supervisorctl", "restart", "backend"], capture_output=True)
    # wait for backend up
    for _ in range(30):
        try:
            r = requests.get(f"{BASE_URL}/api/health", timeout=2)
            if r.status_code in (200, 404):
                # backend is responsive (health may not exist)
                pass
            # try a known endpoint
            r2 = requests.get(f"{BASE_URL}/api/", timeout=2)
            if r2.status_code < 500:
                time.sleep(0.5)
                return
        except Exception:
            time.sleep(0.5)
    time.sleep(2)


def _admin_jwt() -> str:
    return jwt.encode(
        {"email": ADMIN_EMAIL, "isAdmin": True, "entitlements": ["base", "shorts", "studio"]},
        JWT_SECRET,
        algorithm="HS256",
    )


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_admin_jwt()}", "Content-Type": "application/json"}


# --------------------------- mock server fixture ---------------------------

@pytest.fixture(scope="module")
def mock_server():
    """Spin up the tiny echo mock on port 9989 -> /tmp/ghl_test_99.json."""
    Path(MOCK_OUT).unlink(missing_ok=True)
    proc = subprocess.Popen(
        ["python3", "/app/backend/tests/mock_ghl_server.py", str(MOCK_PORT), MOCK_OUT],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(0.8)
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except Exception:
        proc.kill()


@pytest.fixture(scope="module")
def db():
    client = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    return client[os.environ.get("DB_NAME", "f48_studio")]


# --------------------------- 1) Unconfigured state tests ---------------------------

class TestGhlUnconfigured:
    """Initial state: GHL_WEBHOOK_URL is empty."""

    def setup_method(self):
        env = _read_env()
        if env.get("GHL_WEBHOOK_URL"):
            _write_env({"GHL_WEBHOOK_URL": "", "GHL_WEBHOOK_AUTH_HEADER": ""})
            _restart_backend()

    def test_status_when_unconfigured(self):
        r = requests.get(f"{BASE_URL}/api/admin/ghl/status", headers=_auth_headers(), timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["configured"] is False
        assert data["url_host"] is None
        assert data["auth_header_set"] is False
        # ensure no URL leak
        assert "GHL_WEBHOOK_URL" not in r.text

    def test_test_endpoint_503_when_unconfigured(self):
        r = requests.post(f"{BASE_URL}/api/admin/ghl/test", headers=_auth_headers(), timeout=10)
        assert r.status_code == 503
        assert "GHL_WEBHOOK_URL not configured" in r.text

    def test_push_buyer_503_when_unconfigured(self, db):
        # need an existing buyer email
        b = db.buyers.find_one({})
        email = (b or {}).get("email") or ADMIN_EMAIL
        r = requests.post(
            f"{BASE_URL}/api/admin/ghl/push-buyer",
            headers=_auth_headers(), json={"email": email}, timeout=10,
        )
        assert r.status_code == 503

    def test_push_buyer_400_when_missing_email(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/ghl/push-buyer",
            headers=_auth_headers(), json={}, timeout=10,
        )
        assert r.status_code == 400


# --------------------------- 2) Configured live push tests ---------------------------

class TestGhlConfiguredLive:
    """Switches env to point to mock server and exercises real outbound."""

    @classmethod
    def setup_class(cls):
        _write_env({
            "GHL_WEBHOOK_URL": f"http://127.0.0.1:{MOCK_PORT}/inbound",
            "GHL_WEBHOOK_AUTH_HEADER": "",
        })
        _restart_backend()

    @classmethod
    def teardown_class(cls):
        _write_env({"GHL_WEBHOOK_URL": "", "GHL_WEBHOOK_AUTH_HEADER": ""})
        _restart_backend()

    def test_status_when_configured(self, mock_server):
        r = requests.get(f"{BASE_URL}/api/admin/ghl/status", headers=_auth_headers(), timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["configured"] is True
        assert d["url_host"] == f"127.0.0.1:{MOCK_PORT}"
        assert d["auth_header_set"] is False

    def test_ghl_test_sentinel(self, mock_server):
        Path(MOCK_OUT).unlink(missing_ok=True)
        r = requests.post(f"{BASE_URL}/api/admin/ghl/test", headers=_auth_headers(), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["result"]["status"] == "ok"
        assert d["result"]["http_status"] == 202
        time.sleep(0.3)
        captured = json.loads(Path(MOCK_OUT).read_text())
        body = captured["body"]
        assert body["email"] == "ghl-test@f2f48.local"
        assert body["source"] == "manual"
        assert "f2f48-customer" in body["tags"]
        assert "tier:test" in body["tags"]

    def test_pinball_flow_pushes_to_ghl(self, mock_server, db):
        Path(MOCK_OUT).unlink(missing_ok=True)
        # Use a fresh unique email to ensure newly_granted fires
        email = f"TEST_pinball_{int(time.time())}@example.com"
        # remove if exists
        db.buyers.delete_one({"email": email})
        # call test pinball webhook through the admin sandbox endpoint
        r = requests.post(
            f"{BASE_URL}/api/admin/pinball/test-webhook",
            headers=_auth_headers(),
            json={"email": email},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        # GHL push is fire-and-forget — give it a moment
        time.sleep(1.5)
        assert Path(MOCK_OUT).exists(), "mock server did not receive pinball payload"
        captured = json.loads(Path(MOCK_OUT).read_text())
        body = captured["body"]
        assert body["source"] == "pinball_purchase"
        assert body["tier_id"] in {"t1", "t2", "t3", "t4"}
        meta = body["metadata"]
        assert "order_id" in meta
        assert meta.get("product") in ("base", "shorts", "studio")
        assert isinstance(meta.get("newly_granted"), list)
        assert isinstance(meta.get("spend_cents"), int)
        # cleanup
        db.buyers.delete_one({"email": email})

    def test_license_redemption_pushes_to_ghl(self, mock_server, db):
        Path(MOCK_OUT).unlink(missing_ok=True)
        code = f"GHLTEST{int(time.time())}"
        db.redemption_codes.delete_one({"_id": code})
        db.redemption_codes.insert_one({
            "_id": code,
            "tier": "t2",
            "source": "appsumo",
            "status": "available",
            "batch_id": "TEST_BATCH_37",
        })
        r = requests.post(
            f"{BASE_URL}/api/licenses/redeem",
            headers=_auth_headers(),
            json={"code": code},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        time.sleep(1.5)
        assert Path(MOCK_OUT).exists()
        body = json.loads(Path(MOCK_OUT).read_text())["body"]
        assert body["source"] == "appsumo_redemption"
        assert body["tier_id"] == "t2"
        assert body["tier_label"] == "Creator"
        meta = body["metadata"]
        assert meta["code"] == code
        assert meta["batch_id"] == "TEST_BATCH_37"
        assert meta["license_source"] == "appsumo"
        # cleanup
        db.redemption_codes.delete_one({"_id": code})

    def test_push_buyer_endpoint_404_for_nonexistent(self, mock_server):
        r = requests.post(
            f"{BASE_URL}/api/admin/ghl/push-buyer",
            headers=_auth_headers(),
            json={"email": "TEST_nobody_xyz@example.com"},
            timeout=10,
        )
        assert r.status_code == 404


# --------------------------- 3) Failure path tests ---------------------------

class TestGhlFailureLogged:
    """Point GHL at a black-hole URL; verify activity log records failure
    and that the originating event still succeeds."""

    @classmethod
    def setup_class(cls):
        _write_env({
            "GHL_WEBHOOK_URL": "http://127.0.0.1:1/blackhole",
            "GHL_WEBHOOK_AUTH_HEADER": "",
        })
        _restart_backend()

    @classmethod
    def teardown_class(cls):
        _write_env({"GHL_WEBHOOK_URL": "", "GHL_WEBHOOK_AUTH_HEADER": ""})
        _restart_backend()

    def test_failure_logged_to_activity(self, db):
        # call /admin/ghl/test which actually awaits push (so failure is logged sync)
        before = db.activity.count_documents({"type": "ghl_push_failed"})
        r = requests.post(f"{BASE_URL}/api/admin/ghl/test", headers=_auth_headers(), timeout=15)
        # status will be 200 because /admin/ghl/test returns result dict even on failure
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["result"]["status"] in ("error", "failed")
        time.sleep(0.5)
        after = db.activity.count_documents({"type": "ghl_push_failed"})
        assert after > before, "expected activity log row type=ghl_push_failed"

    def test_redeem_succeeds_even_when_ghl_fails(self, db):
        code = f"GHLFAIL{int(time.time())}"
        db.redemption_codes.delete_one({"_id": code})
        db.redemption_codes.insert_one({
            "_id": code,
            "tier": "t1",
            "source": "appsumo",
            "status": "available",
            "batch_id": "FAIL_BATCH",
        })
        r = requests.post(
            f"{BASE_URL}/api/licenses/redeem",
            headers=_auth_headers(),
            json={"code": code},
            timeout=15,
        )
        assert r.status_code == 200, "redeem MUST succeed even if GHL down"
        assert r.json()["ok"] is True
        db.redemption_codes.delete_one({"_id": code})


# --------------------------- 4) Custom auth header tests ---------------------------

class TestGhlAuthHeader:
    @classmethod
    def setup_class(cls):
        _write_env({
            "GHL_WEBHOOK_URL": f"http://127.0.0.1:{MOCK_PORT}/inbound",
            "GHL_WEBHOOK_AUTH_HEADER": "X-F2F48-Secret: test-abc",
        })
        _restart_backend()

    @classmethod
    def teardown_class(cls):
        _write_env({"GHL_WEBHOOK_URL": "", "GHL_WEBHOOK_AUTH_HEADER": ""})
        _restart_backend()

    def test_custom_auth_header_propagates(self, mock_server):
        Path(MOCK_OUT).unlink(missing_ok=True)
        r = requests.post(f"{BASE_URL}/api/admin/ghl/test", headers=_auth_headers(), timeout=15)
        assert r.status_code == 200, r.text
        time.sleep(0.5)
        captured = json.loads(Path(MOCK_OUT).read_text())
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        assert headers.get("x-f2f48-secret") == "test-abc"

    def test_status_reflects_auth_header(self):
        r = requests.get(f"{BASE_URL}/api/admin/ghl/status", headers=_auth_headers(), timeout=10)
        assert r.status_code == 200
        assert r.json()["auth_header_set"] is True
