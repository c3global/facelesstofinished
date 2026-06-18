"""Live integration tests against the preview URL with real JWT tokens.

Exercises the admin + Pinball endpoints via the deployed FastAPI to confirm
ingress routing, JWT issuance via DEV_BYPASS, ADMIN_EMAILS gating, and the
production PINBALL_WEBHOOK_TOKEN value all line up end-to-end.
"""
import os
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://f2f48-video-engine.preview.emergentagent.com").rstrip("/")
PINBALL_TOKEN = "replace-me-before-deploy"  # from /app/backend/.env

ADMIN_EMAIL = "drcharitycampbell@gmail.com"
NON_ADMIN_EMAIL = "directkynections@gmail.com"


def _login(email: str) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/check", json={"email": email}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login(ADMIN_EMAIL)}"}


@pytest.fixture(scope="module")
def nonadmin_headers():
    return {"Authorization": f"Bearer {_login(NON_ADMIN_EMAIL)}"}


# ---- Admin gating ---------------------------------------------------------
def test_admin_buyers_requires_auth():
    r = requests.get(f"{BASE_URL}/api/admin/buyers", timeout=15)
    assert r.status_code == 401


def test_admin_buyers_403_for_non_admin(nonadmin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/buyers", headers=nonadmin_headers, timeout=15)
    assert r.status_code == 403


def test_admin_buyers_200_for_admin(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/buyers", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "total" in body and "items" in body
    assert isinstance(body["items"], list)


def test_admin_buyers_filter_q(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/buyers?q=example", headers=admin_headers, timeout=15)
    assert r.status_code == 200


def test_admin_buyers_filter_entitlement(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/buyers?entitlement=studio", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert "studio" in item.get("entitlements", [])


# ---- Grant / Revoke / Delete ---------------------------------------------
TEST_EMAIL = f"TEST_live_{uuid.uuid4().hex[:8]}@example.com"


def test_grant_creates_and_unions(admin_headers):
    r = requests.patch(f"{BASE_URL}/api/admin/buyers/{TEST_EMAIL}/grant",
                       json={"entitlement": "base"}, headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert "base" in r.json()["buyer"]["entitlements"]
    # idempotent
    r2 = requests.patch(f"{BASE_URL}/api/admin/buyers/{TEST_EMAIL}/grant",
                        json={"entitlement": "shorts"}, headers=admin_headers, timeout=15)
    assert set(r2.json()["buyer"]["entitlements"]) >= {"base", "shorts"}


def test_grant_rejects_unknown_entitlement(admin_headers):
    r = requests.patch(f"{BASE_URL}/api/admin/buyers/{TEST_EMAIL}/grant",
                       json={"entitlement": "premium"}, headers=admin_headers, timeout=15)
    assert r.status_code == 400


def test_revoke_removes(admin_headers):
    r = requests.patch(f"{BASE_URL}/api/admin/buyers/{TEST_EMAIL}/revoke",
                       json={"entitlement": "base"}, headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert "base" not in r.json()["buyer"]["entitlements"]


def test_delete_removes_buyer(admin_headers):
    r = requests.delete(f"{BASE_URL}/api/admin/buyers/{TEST_EMAIL}", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    # verify gone
    g = requests.get(f"{BASE_URL}/api/admin/buyers?q={TEST_EMAIL}", headers=admin_headers, timeout=15)
    emails = [x["email"] for x in g.json()["items"]]
    assert TEST_EMAIL.lower() not in emails


def test_bulk_delete(admin_headers):
    # create two test buyers first
    e1 = f"TEST_bulk1_{uuid.uuid4().hex[:6]}@example.com"
    e2 = f"TEST_bulk2_{uuid.uuid4().hex[:6]}@example.com"
    for e in (e1, e2):
        requests.patch(f"{BASE_URL}/api/admin/buyers/{e}/grant",
                       json={"entitlement": "base"}, headers=admin_headers, timeout=15)
    r = requests.post(f"{BASE_URL}/api/admin/buyers/bulk-delete",
                      json={"emails": [e1, e2]}, headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["deleted"] == 2


# ---- Import ---------------------------------------------------------------
def test_import_endpoint(admin_headers):
    payload = {
        "buyers": [
            {"email": f"TEST_imp_{uuid.uuid4().hex[:6]}@example.com",
             "entitlements": ["base"], "totalSpendCents": 4700,
             "addedAt": "2026-02-01T00:00:00Z"},
            {"email": "not-an-email", "entitlements": ["base"]},
        ]
    }
    r = requests.post(f"{BASE_URL}/api/admin/buyers/import",
                      json=payload, headers=admin_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] >= 1
    assert body["skipped"] == 1
    assert len(body["errors"]) == 1


# ---- Activity + Replay ----------------------------------------------------
def test_activity_list(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/activity", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert "total" in r.json() and "items" in r.json()


def test_activity_filter_by_type(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/activity?type=webhook_failed",
                     headers=admin_headers, timeout=15)
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item["type"] == "webhook_failed"


# ---- Stats ---------------------------------------------------------------
def test_stats(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/stats", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    for k in ("total_users", "active_30d", "total_renders", "total_scripts",
              "revenue_cents", "entitlement_breakdown", "signups_series"):
        assert k in body, f"missing key {k} in stats response"
    assert set(body["entitlement_breakdown"].keys()) == {"base", "shorts", "studio"}


# ---- Pinball webhook (live, no external) ----------------------------------
def test_pinball_bad_token():
    r = requests.post(f"{BASE_URL}/api/pinball-webhook?token=WRONG&product=studio",
                      json={"email": "wht@example.com", "total_amount": "100", "order_id": "wht1"},
                      timeout=15)
    assert r.status_code == 401


def test_pinball_unknown_product():
    r = requests.post(f"{BASE_URL}/api/pinball-webhook?token={PINBALL_TOKEN}&product=lifetime",
                      json={"email": "wht@example.com", "total_amount": "100",
                            "order_id": f"po_{uuid.uuid4().hex[:6]}"}, timeout=15)
    assert r.status_code == 400


def test_pinball_missing_email():
    r = requests.post(f"{BASE_URL}/api/pinball-webhook?token={PINBALL_TOKEN}&product=base",
                      json={"total_amount": "100", "order_id": f"po_{uuid.uuid4().hex[:6]}"}, timeout=15)
    assert r.status_code == 400


def test_pinball_full_flow_with_studio_lifetime(admin_headers):
    email = f"TEST_pb_{uuid.uuid4().hex[:6]}@example.com"
    order = f"po_{uuid.uuid4().hex[:8]}"
    r = requests.post(
        f"{BASE_URL}/api/pinball-webhook?token={PINBALL_TOKEN}&product=studio",
        json={"email": email, "total_amount": "29700", "order_id": order}, timeout=15)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # duplicate
    r2 = requests.post(
        f"{BASE_URL}/api/pinball-webhook?token={PINBALL_TOKEN}&product=studio",
        json={"email": email, "total_amount": "29700", "order_id": order}, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"

    # verify via admin GET
    g = requests.get(f"{BASE_URL}/api/admin/buyers?q={email}", headers=admin_headers, timeout=15)
    items = g.json()["items"]
    assert len(items) >= 1
    buyer = next(i for i in items if i["email"] == email.lower())
    assert "studio" in buyer["entitlements"]
    assert buyer.get("studio_lifetime") is True
    assert buyer.get("studio_status") == "active"
    assert buyer.get("studio_current_period_end") == "2099-01-01T00:00:00Z"
    assert buyer.get("totalSpendCents") == 29700  # not double-counted

    # cleanup
    requests.delete(f"{BASE_URL}/api/admin/buyers/{email}", headers=admin_headers, timeout=15)
