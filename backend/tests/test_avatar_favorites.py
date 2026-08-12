"""Backend tests for avatar favorites endpoints (iteration 20).

Endpoints under test (added in /app/backend/server.py lines ~478-533):
  GET    /api/studio/avatars/favorites
  POST   /api/studio/avatars/favorites               body: {avatar_id}
  DELETE /api/studio/avatars/favorites/{avatar_id}

All three require a JWT with `studio` entitlement. Uses DEV_BYPASS_EMAIL
(`drcharitycampbell@gmail.com`) to obtain a token via /api/auth/check.
Mirror of test_voice_favorites.py (iter-19).
"""
import os
import requests
import pytest

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://modal-chip-ui.preview.emergentagent.com",
).rstrip("/")
ADMIN_EMAIL = "drcharitycampbell@gmail.com"


@pytest.fixture(scope="module")
def auth_token():
    r = requests.post(f"{BASE_URL}/api/auth/check", json={"email": ADMIN_EMAIL}, timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok
    return tok


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


TEST_AVATAR_ID = "TEST_avatar_pytest_iter20"
TEST_AVATAR_ID_2 = "TEST_avatar_pytest_iter20_b"


# Auth gating — all three endpoints must reject unauthenticated requests.
class TestAvatarFavoritesAuth:
    def test_get_favorites_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/studio/avatars/favorites", timeout=10)
        assert r.status_code == 401

    def test_post_favorite_requires_auth(self):
        r = requests.post(
            f"{BASE_URL}/api/studio/avatars/favorites",
            json={"avatar_id": TEST_AVATAR_ID},
            timeout=10,
        )
        assert r.status_code == 401

    def test_delete_favorite_requires_auth(self):
        r = requests.delete(
            f"{BASE_URL}/api/studio/avatars/favorites/{TEST_AVATAR_ID}", timeout=10
        )
        assert r.status_code == 401


# End-to-end CRUD with GET-after-mutate persistence checks.
class TestAvatarFavoritesCRUD:
    def test_get_initial_favorites_returns_list(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/studio/avatars/favorites", headers=auth_headers, timeout=10
        )
        assert r.status_code == 200
        data = r.json()
        assert "favorites" in data
        assert isinstance(data["favorites"], list)

    def test_post_adds_favorite_and_persists(self, auth_headers):
        # Cleanup first in case prior run left it
        requests.delete(
            f"{BASE_URL}/api/studio/avatars/favorites/{TEST_AVATAR_ID}",
            headers=auth_headers, timeout=10,
        )
        # ADD
        r = requests.post(
            f"{BASE_URL}/api/studio/avatars/favorites",
            headers=auth_headers,
            json={"avatar_id": TEST_AVATAR_ID},
            timeout=10,
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True
        # GET to verify persistence
        g = requests.get(
            f"{BASE_URL}/api/studio/avatars/favorites", headers=auth_headers, timeout=10
        )
        assert g.status_code == 200
        assert TEST_AVATAR_ID in g.json()["favorites"]

    def test_post_is_idempotent_addToSet(self, auth_headers):
        # Add twice — $addToSet must not duplicate
        for _ in range(2):
            r = requests.post(
                f"{BASE_URL}/api/studio/avatars/favorites",
                headers=auth_headers, json={"avatar_id": TEST_AVATAR_ID}, timeout=10,
            )
            assert r.status_code == 200
        g = requests.get(
            f"{BASE_URL}/api/studio/avatars/favorites", headers=auth_headers, timeout=10
        )
        favs = g.json()["favorites"]
        assert favs.count(TEST_AVATAR_ID) == 1

    def test_post_missing_avatar_id_rejected(self, auth_headers):
        r = requests.post(
            f"{BASE_URL}/api/studio/avatars/favorites",
            headers=auth_headers, json={"avatar_id": ""}, timeout=10,
        )
        assert r.status_code == 400

    def test_delete_removes_favorite_and_persists(self, auth_headers):
        # Ensure present
        requests.post(
            f"{BASE_URL}/api/studio/avatars/favorites",
            headers=auth_headers, json={"avatar_id": TEST_AVATAR_ID_2}, timeout=10,
        )
        # DELETE
        r = requests.delete(
            f"{BASE_URL}/api/studio/avatars/favorites/{TEST_AVATAR_ID_2}",
            headers=auth_headers, timeout=10,
        )
        assert r.status_code == 200
        # GET — must be gone
        g = requests.get(
            f"{BASE_URL}/api/studio/avatars/favorites", headers=auth_headers, timeout=10
        )
        assert TEST_AVATAR_ID_2 not in g.json()["favorites"]

    def test_voice_favorites_unaffected(self, auth_headers):
        # Regression: voice favorites endpoint still works independently of avatar favorites.
        r = requests.get(
            f"{BASE_URL}/api/studio/voices/favorites", headers=auth_headers, timeout=10
        )
        assert r.status_code == 200
        assert "favorites" in r.json()

    def test_cleanup(self, auth_headers):
        # Final teardown — remove TEST_AVATAR_ID added earlier
        r = requests.delete(
            f"{BASE_URL}/api/studio/avatars/favorites/{TEST_AVATAR_ID}",
            headers=auth_headers, timeout=10,
        )
        assert r.status_code == 200
        g = requests.get(
            f"{BASE_URL}/api/studio/avatars/favorites", headers=auth_headers, timeout=10
        )
        assert TEST_AVATAR_ID not in g.json()["favorites"]
