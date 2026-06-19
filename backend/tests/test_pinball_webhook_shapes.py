"""Regression tests for the lenient Pinball webhook payload extractors.

Pinball workflows fire the same semantic data under different shapes
depending on the workflow node (raw checkout, OTO, replay, etc.). The
legacy Netlify handler accepted 6 email paths + 4 items paths; we mirror
that tolerance so workflows that worked on Netlify keep working on
Emergent without any Pinball-side reconfiguration.

This was the bug behind: "the webhook to emergent isn't working" with
"Status - 400, Error Message - {detail: Missing data.customer.email}".
"""

import os
import time
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
ADMIN_EMAIL = "drcharitycampbell@gmail.com"
TIMEOUT = 30


def _admin_token() -> str:
    r = requests.post(f"{BASE}/auth/check", json={"email": ADMIN_EMAIL, "cookies": ""}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["token"]


def _admin_delete(email: str, token: str) -> None:
    requests.delete(f"{BASE}/admin/buyers/{email}", headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)


def _webhook_url() -> str:
    # Read the live token from the env so this test mirrors production.
    with open("/app/backend/.env") as f:
        for line in f:
            if line.startswith("PINBALL_WEBHOOK_TOKEN="):
                return f"{BASE}/pinball/order-completed?token={line.split('=', 1)[1].strip()}"
    raise RuntimeError("PINBALL_WEBHOOK_TOKEN not in /app/backend/.env")


def _fresh_email(tag: str) -> str:
    return f"pytest-pinball-{tag}-{int(time.time() * 1000)}@example.invalid"


# Default product map: 01ks3pmetahzgx2mfg7q5crs0j → base
BASE_PRODUCT_ID = "01ks3pmetahzgx2mfg7q5crs0j"


def test_shape_a_data_customer_email_data_items():
    """Original Pinball v2 shape: data.customer.email + data.items."""
    token = _admin_token()
    email = _fresh_email("a")
    try:
        r = requests.post(_webhook_url(), json={
            "data": {
                "customer": {"email": email},
                "items": [{"id": "li-a", "product_id": BASE_PRODUCT_ID, "amount": 700}],
            },
        }, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["granted"] == 1
        assert body["results"][0]["entitlement"] == "base"
    finally:
        _admin_delete(email, token)


def test_shape_b_root_customer_email_root_items():
    """Pinball OTO shape: customer.email at root + items at root."""
    token = _admin_token()
    email = _fresh_email("b")
    try:
        r = requests.post(_webhook_url(), json={
            "customer": {"email": email},
            "items": [{"id": "li-b", "product_id": BASE_PRODUCT_ID, "amount": 700}],
        }, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert r.json()["granted"] == 1
    finally:
        _admin_delete(email, token)


def test_shape_c_email_root_order_items():
    """Legacy GHL shape: email at root + order.items."""
    token = _admin_token()
    email = _fresh_email("c")
    try:
        r = requests.post(_webhook_url(), json={
            "email": email,
            "order": {"id": "ord-c", "items": [{"id": "li-c", "product_id": BASE_PRODUCT_ID, "amount": 700}]},
        }, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert r.json()["granted"] == 1
    finally:
        _admin_delete(email, token)


def test_shape_d_data_email_data_items():
    """Sometimes Pinball flattens: data.email + data.items (no customer wrapper)."""
    token = _admin_token()
    email = _fresh_email("d")
    try:
        r = requests.post(_webhook_url(), json={
            "data": {
                "email": email,
                "items": [{"id": "li-d", "product_id": BASE_PRODUCT_ID, "amount": 700}],
            },
        }, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert r.json()["granted"] == 1
    finally:
        _admin_delete(email, token)


def test_missing_email_returns_400():
    """Payload with no recognizable email anywhere → clean 400."""
    r = requests.post(_webhook_url(), json={
        "data": {"items": [{"id": "li-x", "product_id": "bad", "amount": 700}]},
    }, timeout=TIMEOUT)
    assert r.status_code == 400
    assert "email" in r.json()["detail"].lower()


def test_missing_items_returns_400():
    """Payload with valid email but no items array → clean 400."""
    r = requests.post(_webhook_url(), json={
        "customer": {"email": "x@y.invalid"},
    }, timeout=TIMEOUT)
    assert r.status_code == 400
    assert "items" in r.json()["detail"].lower()


def test_wrong_token_returns_401():
    """Wrong token → 401 (token gate is the first line of defense)."""
    bad_url = f"{BASE}/pinball/order-completed?token=WRONG_TOKEN"
    r = requests.post(bad_url, json={
        "customer": {"email": "x@y.invalid"},
        "items": [{"id": "li", "product_id": BASE_PRODUCT_ID, "amount": 700}],
    }, timeout=TIMEOUT)
    assert r.status_code == 401


def test_granted_buyer_can_sign_in_immediately():
    """End-to-end: Pinball webhook grants → buyer can sign in via the
    new db.buyers auth branch with the right entitlement."""
    token = _admin_token()
    email = _fresh_email("e2e")
    try:
        r = requests.post(_webhook_url(), json={
            "customer": {"email": email},
            "items": [{"id": "li-e2e", "product_id": BASE_PRODUCT_ID, "amount": 700}],
        }, timeout=TIMEOUT)
        assert r.status_code == 200

        signin = requests.post(f"{BASE}/auth/check", json={"email": email, "cookies": ""}, timeout=TIMEOUT)
        assert signin.status_code == 200, signin.text
        assert "base" in signin.json()["user"]["entitlements"]
    finally:
        _admin_delete(email, token)
