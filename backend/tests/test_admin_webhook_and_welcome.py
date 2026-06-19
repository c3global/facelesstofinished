"""Regression tests for admin test-webhook endpoint + pending_welcome flag.

Both shipped in iter 3.5n alongside the auth + Pinball extractor fixes.
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
    with open("/app/backend/.env") as f:
        for line in f:
            if line.startswith("PINBALL_WEBHOOK_TOKEN="):
                return f"{BASE}/pinball/order-completed?token={line.split('=', 1)[1].strip()}"
    raise RuntimeError("PINBALL_WEBHOOK_TOKEN not set")


class TestAdminTestWebhook:
    """Admin "Test webhook" button — POST /admin/pinball/test-webhook."""

    def test_requires_admin(self):
        """No bearer → 401 (or 403)."""
        r = requests.post(f"{BASE}/admin/pinball/test-webhook", json={}, timeout=TIMEOUT)
        assert r.status_code in (401, 403)

    def test_synthetic_grant_succeeds(self):
        """Default invocation creates a synthetic buyer with 'base' entitlement."""
        token = _admin_token()
        r = requests.post(
            f"{BASE}/admin/pinball/test-webhook",
            headers={"Authorization": f"Bearer {token}"},
            json={},
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["test_product"] == "base"
        assert body["test_email"].endswith("@faceless48.test")
        assert "message" in body
        # Cleanup the synthetic buyer
        _admin_delete(body["test_email"], token)

    def test_unknown_product_id_returns_400(self):
        """Bad product_id override → 400 with helpful detail."""
        token = _admin_token()
        r = requests.post(
            f"{BASE}/admin/pinball/test-webhook",
            headers={"Authorization": f"Bearer {token}"},
            json={"product_id": "not-a-real-product-id"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 400


class TestPendingWelcomeFlag:
    """Pinball webhook sets pending_welcome on newly-granted entitlements,
    auth_check reads + clears it on first sign-in, one-shot delivery."""

    def test_welcome_present_on_first_signin_after_webhook(self):
        token = _admin_token()
        email = f"pytest-welcome-{int(time.time() * 1000)}@example.invalid"
        try:
            # Step 1: Pinball webhook grants base entitlement
            r = requests.post(_webhook_url(), json={
                "customer": {"email": email},
                "items": [{"id": "li-w", "product_id": "01ks3pmetahzgx2mfg7q5crs0j", "amount": 700}],
            }, timeout=TIMEOUT)
            assert r.status_code == 200

            # Step 2: First sign-in carries the welcome payload
            s1 = requests.post(f"{BASE}/auth/check", json={"email": email, "cookies": ""}, timeout=TIMEOUT)
            assert s1.status_code == 200, s1.text
            assert "welcome" in s1.json(), "welcome payload missing on first sign-in"
            assert s1.json()["welcome"]["source"] == "pinball"
            assert "base" in s1.json()["welcome"]["entitlements"]

            # Step 3: Second sign-in does NOT carry it (one-shot)
            s2 = requests.post(f"{BASE}/auth/check", json={"email": email, "cookies": ""}, timeout=TIMEOUT)
            assert s2.status_code == 200
            assert "welcome" not in s2.json(), "welcome payload should be cleared after first sign-in"
        finally:
            _admin_delete(email, token)

    def test_admin_grant_no_welcome(self):
        """Admin-added buyers (not via Pinball) do NOT get the welcome flag —
        the toast is reserved for paying customers' first sign-in."""
        token = _admin_token()
        email = f"pytest-no-welcome-{int(time.time() * 1000)}@example.invalid"
        try:
            requests.post(
                f"{BASE}/admin/buyers/import",
                headers={"Authorization": f"Bearer {token}"},
                json={"buyers": [{"email": email, "entitlements": ["base"]}]},
                timeout=TIMEOUT,
            )
            r = requests.post(f"{BASE}/auth/check", json={"email": email, "cookies": ""}, timeout=TIMEOUT)
            assert r.status_code == 200
            assert "welcome" not in r.json(), "admin-added buyers should not get a welcome toast"
        finally:
            _admin_delete(email, token)
