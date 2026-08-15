"""Gold-standard integration tests for POST /api/studio/stock-candidates.

Uses FastAPI dependency override to bypass auth (so we don't have to mint a
real JWT under test) and `respx` to intercept the outgoing HTTP requests to
Pexels + Pixabay so we can assert the EXACT `query` / `q` param on the wire.

Bug guarded against (v1.20.12): the endpoint used to sanitize the detailed
AI `prompt` for stock providers even when the paired `search_query` was
present. The correct behaviour: prefer `search_query` verbatim, only fall
back to the sanitized prompt when the query is missing/empty, and NEVER
send the raw AI prompt.

No paid provider is actually contacted — all HTTP is mocked via respx.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "f48_tests")
os.environ.setdefault("CORS_ORIGINS", "*")

import server  # noqa: E402
from server import AuthUser, app, api, current_user  # noqa: E402


def _fake_admin_user() -> AuthUser:
    return AuthUser(
        email="drcharitycampbell@gmail.com",
        entitlements=["studio"],
        is_admin=True,
    )


@pytest.fixture(autouse=True)
def _override_auth_and_keys(monkeypatch):
    """Bypass JWT auth + inject placeholder provider keys so branch is taken."""
    app.dependency_overrides[current_user] = _fake_admin_user
    api.dependency_overrides[current_user] = _fake_admin_user
    monkeypatch.setattr(server, "PEXELS_API_KEY", "TEST_PEXELS_KEY", raising=False)
    monkeypatch.setattr(server, "PIXABAY_API_KEY", "TEST_PIXABAY_KEY", raising=False)
    yield
    app.dependency_overrides.pop(current_user, None)
    api.dependency_overrides.pop(current_user, None)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# --------------------------------------------------------------------------- #
# Bug #1: `search_query` present + non-empty → hits Pexels with THAT string.
# The raw detailed AI prompt must NEVER be sent.
# --------------------------------------------------------------------------- #


@respx.mock
def test_pexels_uses_search_query_verbatim_not_the_prompt(client: TestClient):
    route = respx.get("https://api.pexels.com/videos/search").mock(
        return_value=httpx.Response(200, json={"videos": []})
    )

    detailed = (
        "Medium tracking shot of a barista pouring milk into a coffee cup, "
        "warm indoor light, gentle push-in"
    )
    resp = client.post(
        "/api/studio/stock-candidates",
        headers={"Authorization": "Bearer TEST"},
        json={
            "prompts": [detailed],
            "search_queries": ["coffee pouring cup"],
            "source": "pexels",
            "orientation": "portrait",
        },
    )
    assert resp.status_code == 200, resp.text
    assert route.called, "Pexels endpoint was never hit"

    sent = route.calls[0].request
    q = httpx.QueryParams(sent.url.query.decode()).get("query")
    assert q == "coffee pouring cup", (
        f"Pexels received query={q!r} — expected the paired search_query verbatim, "
        f"NOT the detailed AI prompt."
    )
    # And critically: the detailed prompt was never sent.
    assert "tracking" not in (q or ""), "raw AI prompt leaked to Pexels"
    assert "push-in" not in (q or ""), "raw AI prompt leaked to Pexels"


@respx.mock
def test_pixabay_uses_search_query_verbatim(client: TestClient):
    route = respx.get("https://pixabay.com/api/videos/").mock(
        return_value=httpx.Response(200, json={"hits": []})
    )
    resp = client.post(
        "/api/studio/stock-candidates",
        headers={"Authorization": "Bearer TEST"},
        json={
            "prompts": ["Aerial wide shot of runners on a mountain trail at dawn, cool blue light"],
            "search_queries": ["runners trail sunrise"],
            "source": "pixabay",
            "orientation": "landscape",
        },
    )
    assert resp.status_code == 200, resp.text
    assert route.called
    q = httpx.QueryParams(route.calls[0].request.url.query.decode()).get("q")
    assert q == "runners trail sunrise"


# --------------------------------------------------------------------------- #
# Bug #1 fallback path — no search_query → sanitized prompt reaches Pexels.
# --------------------------------------------------------------------------- #


@respx.mock
def test_pexels_falls_back_to_sanitized_prompt_when_search_query_missing(client: TestClient):
    route = respx.get("https://api.pexels.com/videos/search").mock(
        return_value=httpx.Response(200, json={"videos": []})
    )

    resp = client.post(
        "/api/studio/stock-candidates",
        headers={"Authorization": "Bearer TEST"},
        json={
            "prompts": [
                "Wide overhead shot of hands typing on laptop keyboard, "
                "soft window daylight, slow camera drift right"
            ],
            # search_queries omitted entirely — fallback branch must fire.
            "source": "pexels",
        },
    )
    assert resp.status_code == 200, resp.text
    assert route.called

    q = httpx.QueryParams(route.calls[0].request.url.query.decode()).get("query") or ""
    tokens = q.split()
    # Cinematic vocabulary must be stripped by _extract_stock_query.
    for banned in ("wide", "overhead", "shot", "soft", "slow", "camera", "drift"):
        assert banned not in tokens, (
            f"Sanitizer failed to strip '{banned}' from outgoing Pexels query: {q!r}"
        )
    # And concrete nouns survive.
    assert any(w in tokens for w in ("hands", "typing", "laptop", "keyboard")), (
        f"Sanitized query lost all concrete nouns: {q!r}"
    )


@respx.mock
def test_pexels_empty_search_query_string_treated_as_missing(client: TestClient):
    route = respx.get("https://api.pexels.com/videos/search").mock(
        return_value=httpx.Response(200, json={"videos": []})
    )
    resp = client.post(
        "/api/studio/stock-candidates",
        headers={"Authorization": "Bearer TEST"},
        json={
            "prompts": ["Wide overhead shot of a busy cafe counter, soft daylight"],
            "search_queries": [""],
            "source": "pexels",
        },
    )
    assert resp.status_code == 200
    assert route.called
    q = httpx.QueryParams(route.calls[0].request.url.query.decode()).get("query") or ""
    assert "overhead" not in q.split()
    assert "shot" not in q.split()


# --------------------------------------------------------------------------- #
# Safety net — all-stopword prompt + no search_query = zero HTTP fanout.
# The raw prompt must NEVER hit the provider.
# --------------------------------------------------------------------------- #


@respx.mock
def test_all_stopwords_prompt_never_hits_pexels(client: TestClient):
    route = respx.get("https://api.pexels.com/videos/search").mock(
        return_value=httpx.Response(200, json={"videos": []})
    )
    resp = client.post(
        "/api/studio/stock-candidates",
        headers={"Authorization": "Bearer TEST"},
        json={"prompts": ["the and of in"], "source": "pexels"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["candidates"][0]["candidates"] == []
    assert not route.called, (
        "REGRESSION: endpoint issued a Pexels call with an unsanitized/empty query. "
        "It must return [] instead of leaking the raw prompt."
    )
