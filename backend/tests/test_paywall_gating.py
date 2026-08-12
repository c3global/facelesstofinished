"""Iter-21 — Pre-customer-launch paywall gating regression.

Verifies backend 403 entitlement gating still works for:
- GET /api/studio/avatars (requires `studio`)
- POST /api/scripts/shorts (requires `shorts`)

We mint custom JWTs locally (using the same JWT_SECRET as the backend)
because the only DEV_BYPASS path in the live backend grants ALL three
entitlements automatically — there's no way to actually log in as a
non-entitled user in this dev env.
"""
import os
import time
import jwt
import pytest
import requests
from pathlib import Path

# Load JWT_SECRET from backend/.env so we mint tokens the live server accepts.
_BACKEND_ENV = Path("/app/backend/.env")
for line in _BACKEND_ENV.read_text().splitlines():
    if line.startswith("JWT_SECRET="):
        os.environ["JWT_SECRET"] = line.split("=", 1)[1].strip()
        break

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = "HS256"

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://modal-chip-ui.preview.emergentagent.com").rstrip("/")


def _mint(email: str, entitlements: list[str], is_admin: bool = False) -> str:
    payload = {
        "email": email,
        "entitlements": entitlements,
        "isAdmin": is_admin,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


@pytest.fixture
def base_only_token():
    # Customer with base only — no studio, no shorts.
    return _mint("test-base-only@example.com", ["base"])


@pytest.fixture
def shorts_token():
    return _mint("test-shorts-only@example.com", ["base", "shorts"])


@pytest.fixture
def full_token():
    return _mint("test-full@example.com", ["base", "shorts", "studio"])


# --- Studio gating ----------------------------------------------------------

class TestStudioGating:
    def test_studio_avatars_403_without_studio_entitlement(self, base_only_token):
        r = requests.get(
            f"{BASE_URL}/api/studio/avatars",
            headers={"Authorization": f"Bearer {base_only_token}"},
            timeout=30,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert "studio" in (body.get("detail", "")).lower()

    def test_studio_avatars_401_without_token(self):
        r = requests.get(f"{BASE_URL}/api/studio/avatars", timeout=10)
        assert r.status_code == 401

    def test_studio_avatars_403_for_shorts_only_user(self, shorts_token):
        # Shorts entitlement should NOT grant Studio access.
        r = requests.get(
            f"{BASE_URL}/api/studio/avatars",
            headers={"Authorization": f"Bearer {shorts_token}"},
            timeout=30,
        )
        assert r.status_code == 403


# --- Shorts gating ----------------------------------------------------------

class TestShortsGating:
    def _shorts_payload(self):
        return {
            "topic": "TEST topic for paywall gating",
            "platform": "youtube",
            "sprint": False,
        }

    def test_scripts_shorts_403_without_shorts_entitlement(self, base_only_token):
        r = requests.post(
            f"{BASE_URL}/api/scripts/shorts",
            headers={"Authorization": f"Bearer {base_only_token}"},
            json=self._shorts_payload(),
            timeout=30,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"

    def test_scripts_shorts_401_without_token(self):
        r = requests.post(
            f"{BASE_URL}/api/scripts/shorts",
            json=self._shorts_payload(),
            timeout=10,
        )
        assert r.status_code == 401


# --- No-regression sanity for full-entitlement user -------------------------

class TestFullEntitlementNoRegression:
    def test_studio_avatars_not_403_for_full_user(self, full_token):
        # Backend caches avatars so this should be quick after iter-20 warm.
        # Accept anything OTHER than 403 (200, 502 from ingress race are OK
        # — what matters is the entitlement check itself passed).
        r = requests.get(
            f"{BASE_URL}/api/studio/avatars",
            headers={"Authorization": f"Bearer {full_token}"},
            timeout=90,
        )
        assert r.status_code != 403, f"full-entitlement user incorrectly 403'd: {r.text[:200]}"

    def test_auth_me_includes_all_entitlements_for_dev_bypass(self):
        # Login as DEV_BYPASS admin and verify /auth/me lists all 3 ents.
        login = requests.post(
            f"{BASE_URL}/api/auth/check",
            json={"email": "drcharitycampbell@gmail.com"},
            timeout=10,
        )
        assert login.status_code == 200
        token = login.json()["token"]
        me = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert me.status_code == 200
        ents = set(me.json().get("entitlements", []))
        assert {"base", "shorts", "studio"}.issubset(ents)


# --- Favicon + index.html branding ------------------------------------------

class TestBrandingAssets:
    def test_favicon_png_served(self):
        r = requests.get(f"{BASE_URL}/favicon.png", timeout=10)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/png")
        assert len(r.content) > 1000  # >1KB sanity

    def test_login_hero_png_served(self):
        r = requests.get(f"{BASE_URL}/login-hero.png", timeout=20)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/png")
        assert len(r.content) > 10000

    def test_index_html_title_and_favicon_link(self):
        r = requests.get(f"{BASE_URL}/", timeout=10)
        assert r.status_code == 200
        html = r.text
        assert "<title>Faceless to Finished — Studio</title>" in html
        assert 'rel="icon"' in html and "favicon.png" in html
