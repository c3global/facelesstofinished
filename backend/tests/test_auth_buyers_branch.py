"""Regression tests for the db.buyers-backed auth branch.

Customers granted access via Admin → Buyers UI (or the live Pinball webhook)
must be able to sign in via POST /api/auth/check. This was the bug behind
"Clients are having access issues even though in admin I've granted access
to the various entitlements." — auth_check used to skip db.buyers entirely.
"""

import os
import time
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
ADMIN_EMAIL = "drcharitycampbell@gmail.com"  # DEV_BYPASS / ADMIN_EMAILS
TIMEOUT = 30


def _admin_token() -> str:
    r = requests.post(f"{BASE}/auth/check", json={"email": ADMIN_EMAIL, "cookies": ""}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["token"]


def _check(email: str) -> requests.Response:
    return requests.post(f"{BASE}/auth/check", json={"email": email, "cookies": ""}, timeout=TIMEOUT)


def _admin_post(path: str, token: str, payload: dict) -> requests.Response:
    return requests.post(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=TIMEOUT)


def _admin_patch(path: str, token: str, payload: dict) -> requests.Response:
    return requests.patch(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=TIMEOUT)


def _admin_delete(path: str, token: str) -> requests.Response:
    return requests.delete(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)


def _fresh_email() -> str:
    return f"pytest-auth-{int(time.time() * 1000)}@example.invalid"


def test_non_buyer_gets_401():
    """Sanity: an email that has never been added returns 401."""
    r = _check(_fresh_email())
    assert r.status_code == 401, r.text


def test_buyer_with_entitlements_can_sign_in():
    """Customer granted via Admin → Buyers UI can sign in and gets the
    exact entitlements the admin chose."""
    token = _admin_token()
    email = _fresh_email()
    try:
        imp = _admin_post(
            "/admin/buyers/import",
            token,
            {"buyers": [{"email": email, "entitlements": ["base", "shorts", "studio"]}]},
        )
        assert imp.status_code == 200, imp.text
        assert imp.json()["imported"] == 1

        r = _check(email)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["email"] == email
        assert sorted(body["user"]["entitlements"]) == ["base", "shorts", "studio"]
        assert body["user"]["isAdmin"] is False
        assert body["token"]  # JWT issued
    finally:
        _admin_delete(f"/admin/buyers/{email}", token)


def test_buyer_with_partial_entitlements_signs_in_with_only_those():
    """Revoking 'studio' should let buyer sign in with the remaining ents
    (frontend paywall then handles per-feature gating)."""
    token = _admin_token()
    email = _fresh_email()
    try:
        _admin_post(
            "/admin/buyers/import",
            token,
            {"buyers": [{"email": email, "entitlements": ["base", "shorts", "studio"]}]},
        )
        rv = _admin_patch(f"/admin/buyers/{email}/revoke", token, {"entitlement": "studio"})
        assert rv.status_code == 200, rv.text

        r = _check(email)
        assert r.status_code == 200, r.text
        ents = r.json()["user"]["entitlements"]
        assert sorted(ents) == ["base", "shorts"]
        assert "studio" not in ents
    finally:
        _admin_delete(f"/admin/buyers/{email}", token)


def test_buyer_with_zero_entitlements_falls_through_to_401():
    """An empty-entitlements buyer record is treated as revoked — they
    get the same 401 as a non-buyer (no silent bypass)."""
    token = _admin_token()
    email = _fresh_email()
    try:
        _admin_post(
            "/admin/buyers/import",
            token,
            {"buyers": [{"email": email, "entitlements": ["base"]}]},
        )
        _admin_patch(f"/admin/buyers/{email}/revoke", token, {"entitlement": "base"})

        r = _check(email)
        assert r.status_code == 401, r.text
    finally:
        _admin_delete(f"/admin/buyers/{email}", token)


def test_email_is_case_insensitive():
    """Customers might type their email with different casing than was
    stored in db.buyers — match must be case-insensitive."""
    token = _admin_token()
    email_lower = _fresh_email().lower()
    try:
        _admin_post(
            "/admin/buyers/import",
            token,
            {"buyers": [{"email": email_lower, "entitlements": ["base", "studio"]}]},
        )
        # Sign in with weird casing
        r = _check(email_lower.upper())
        assert r.status_code == 200, r.text
        assert sorted(r.json()["user"]["entitlements"]) == ["base", "studio"]
    finally:
        _admin_delete(f"/admin/buyers/{email_lower}", token)


def test_admin_email_gets_admin_flag_via_buyers_branch():
    """If an admin-listed email also happens to be in db.buyers, the JWT
    must still carry isAdmin=True."""
    r = _check(ADMIN_EMAIL)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["isAdmin"] is True
