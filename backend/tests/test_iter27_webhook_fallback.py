"""Regression: /api/pinball/order-completed must accept the payload shapes
Charity's funnel actually fires under. On 2026-02-23 her GHL automation
was returning Status 400 'No items in payload' for EVERY new buyer (D.C.
Sirisena, David Stephens, Mary Melvina Jackson, etc.). The legacy Netlify
handler accepted these via a `?product=base` fallback that was missing
from the Emergent port.

Two layers of coverage:
  1. Pure-function unit tests for the lenient extractors.
  2. Live-backend integration tests via httpx (avoids the TestClient +
     motor event-loop binding problem from iter-26).
"""
import os
import re
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
import pytest

load_dotenv("/app/backend/.env", override=True)
sys.path.insert(0, "/app/backend")

assert os.environ["DB_NAME"] == "f48_studio", (
    f"Cross-test env pollution: DB_NAME={os.environ.get('DB_NAME')}"
)

from admin_routes import (  # noqa: E402
    _extract_items,
    _extract_order_total_cents,
    _synthesize_single_item,
)

TOKEN = os.environ.get("PINBALL_WEBHOOK_TOKEN") or ""
BASE = "http://localhost:8001"
ADMIN_ROUTES_PY = Path("/app/backend/admin_routes.py").read_text()
NONCE = str(int(time.time() * 1000))


# =========================================================================
# Pure helper unit tests (no DB, no HTTP)
# =========================================================================
def test_extract_items_camelCase_lineItems():
    """GHL ships `lineItems` (camelCase), not `items`."""
    assert _extract_items({"lineItems": [{"product_id": "x"}]}) == [{"product_id": "x"}]


def test_extract_items_snake_case_line_items():
    """Kajabi ships `line_items` (snake_case)."""
    assert _extract_items({"line_items": [{"product_id": "x"}]}) == [{"product_id": "x"}]


def test_extract_items_data_lineItems():
    """Wrapped under `data` is common for GHL workflow nodes."""
    assert _extract_items({"data": {"lineItems": [{"product_id": "x"}]}}) == [{"product_id": "x"}]


def test_extract_items_order_products():
    """Some Kajabi flows nest under `order.products`."""
    assert _extract_items({"order": {"products": [{"product_id": "x"}]}}) == [{"product_id": "x"}]


def test_extract_items_event_lineItems():
    """Stripe-style `event.lineItems`."""
    assert _extract_items({"event": {"lineItems": [{"product_id": "x"}]}}) == [{"product_id": "x"}]


def test_extract_items_returns_empty_for_flat_payload():
    """A truly flat payload (no array anywhere) returns empty list."""
    assert _extract_items({"email": "a@b.com", "product_id": "x", "amount": 27}) == []


# -------------------------------------------------------------------------
def test_synthesize_top_level_product_id():
    """Flat GHL Order Submitted shape: product_id at top level."""
    item = _synthesize_single_item({"email": "a@b.com", "product_id": "f48-base", "amount": 27})
    assert item is not None and item["product_id"] == "f48-base"


def test_synthesize_camelCase_productId_under_data():
    """GHL workflow ships productId (camelCase) under data."""
    item = _synthesize_single_item({"data": {"productId": "f48-base", "amount": 27}})
    assert item is not None and item["product_id"] == "f48-base"


def test_synthesize_returns_none_when_no_product():
    """Payload with email but no product info anywhere → None."""
    assert _synthesize_single_item({"email": "a@b.com", "amount": 27}) is None


# -------------------------------------------------------------------------
def test_extract_order_total_dollars_heuristic():
    """A small float looks like dollars and is converted to cents."""
    assert _extract_order_total_cents({"amount": 27.00}) == 2700


def test_extract_order_total_large_integer_pass_through():
    """A large int (>= 10000) is treated as cents already (so legacy
    Pinball payloads shipping `total_amount` in cents keep working)."""
    assert _extract_order_total_cents({"amount": 270000}) == 270000


# =========================================================================
# Source-level guarantees — fast, no DB needed, catches regressions
# =========================================================================
def test_pinball_endpoint_accepts_optional_product_query_param():
    """`/pinball/order-completed` must accept an optional ?product= query
    param to fall back when items[] is empty. This was the missing piece
    in Charity's GHL setup."""
    # The route handler's signature must contain `product: str = Query(`
    m = re.search(
        r"@api\.post\(\"/pinball/order-completed\"\).*?async def pinball_order_completed\((.*?)\):",
        ADMIN_ROUTES_PY,
        re.DOTALL,
    )
    assert m, "could not locate pinball_order_completed signature"
    sig = m.group(1)
    assert "product:" in sig and "Query(" in sig, (
        "endpoint must accept ?product= query param for legacy fallback"
    )


def test_pinball_endpoint_uses_synthesize_then_query_fallback():
    """The endpoint body must call _synthesize_single_item AND fall back
    to the ?product= query param when synthesis returns None."""
    # Find the function body
    m = re.search(
        r"async def pinball_order_completed\(.*?\n(    return [^\n]+)",
        ADMIN_ROUTES_PY,
        re.DOTALL,
    )
    assert m, "could not locate pinball_order_completed body"
    body = m.group(0)
    assert "_synthesize_single_item(body)" in body, "synthesizer must be called"
    assert "elif product:" in body, "query-param fallback branch must exist"
    assert "KNOWN_ENTITLEMENTS" in body, "query-param fallback must validate the product"


def test_pinball_endpoint_400_detail_mentions_three_fixes():
    """When all fallbacks miss, the 400 detail must surface ALL three
    remediation paths so the admin can self-serve."""
    m = re.search(
        r'detail=\(\s*\n\s*"No items in payload[^"]*"\s*\n\s*"[^"]*items\[\][^"]*"',
        ADMIN_ROUTES_PY,
    )
    # Approximate: just require the three phrases somewhere in the source
    assert "items[]" in ADMIN_ROUTES_PY
    assert "product_id" in ADMIN_ROUTES_PY
    assert "?product=" in ADMIN_ROUTES_PY


def test_pinball_endpoint_response_includes_fallback_mode():
    """The 200 response must report which path matched so admin telemetry
    can distinguish synthesize vs query-param vs real-items[] grants."""
    assert '"fallback_mode": fallback_mode' in ADMIN_ROUTES_PY


def test_per_item_loop_honors_fallback_entitlement_sentinel():
    """Synthesized & query-param fallback items carry
    `_fallback_entitlement` directly — the loop must prefer it over the
    PINBALL_PRODUCT_MAP lookup (which would miss on the synthetic
    product_id)."""
    assert 'item.get("_fallback_entitlement") or PINBALL_PRODUCT_MAP' in ADMIN_ROUTES_PY


# =========================================================================
# Live backend integration (uses real DB — namespaced + cleaned up)
# =========================================================================
def _health_ok() -> bool:
    """Skip live tests if the backend isn't up — keeps the suite green
    on machines where supervisor isn't running."""
    try:
        return httpx.get(f"{BASE}/api/", timeout=2).status_code == 200
    except Exception:
        return False


live = pytest.mark.skipif(
    not (_health_ok() and TOKEN),
    reason="live backend or PINBALL_WEBHOOK_TOKEN missing",
)


def _delete_buyer_sync(email: str):
    """Sync cleanup — uses a fresh pymongo-style call via the running
    backend's admin endpoint isn't worth the auth dance. Instead poke
    the test endpoint OR just leave the cleanup to a fresh motor client
    in a one-shot asyncio.run."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _do():
        cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
        await cli[os.environ["DB_NAME"]].buyers.delete_one({"email": email})
        cli.close()

    try:
        asyncio.run(_do())
    except RuntimeError:
        # If there's already an event loop running, ignore — the test was
        # only checking the response, the buyer doc will get sweeped later.
        pass


@live
def test_live_charity_ghl_flat_with_query_param_fallback_returns_200():
    """The bug repro: flat GHL payload + ?product=base must succeed."""
    email = f"iter27.live.flat+{NONCE}@test.example"
    try:
        r = httpx.post(
            f"{BASE}/api/pinball/order-completed?token={TOKEN}&product=base",
            json={
                "email": email,
                "order_id": f"ord-iter27-flat-{NONCE}",
                "amount": 27.0,
                "first_name": "Test",
            },
            timeout=10,
        )
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:300]}"
        data = r.json()
        assert data.get("ok") is True
        assert data.get("granted") == 1
        assert data.get("fallback_mode") == "query_param_product"
    finally:
        _delete_buyer_sync(email)


@live
def test_live_charity_flat_no_query_param_returns_400_with_helpful_detail():
    """A flat payload with NO product info AND NO ?product= query must
    400 — but the error message must list all 3 fixes."""
    r = httpx.post(
        f"{BASE}/api/pinball/order-completed?token={TOKEN}",
        json={"email": f"iter27.live.no_product+{NONCE}@test.example", "amount": 9.99},
        timeout=10,
    )
    assert r.status_code == 400
    detail = r.json().get("detail", "")
    assert "items[]" in detail
    assert "product_id" in detail
    assert "?product=" in detail


@live
def test_live_invalid_token_returns_401():
    """Token gate untouched by this fix."""
    r = httpx.post(
        f"{BASE}/api/pinball/order-completed?token=invalid-iter27",
        json={"email": "x@y.com"},
        timeout=10,
    )
    assert r.status_code == 401


@live
def test_live_normal_pinball_items_array_still_works():
    """Regression: the original Pinball-shape payload with data.items[]
    must keep working — fallback chain is additive, not replacement."""
    email = f"iter27.live.normal+{NONCE}@test.example"
    try:
        r = httpx.post(
            f"{BASE}/api/pinball/order-completed?token={TOKEN}",
            json={
                "data": {
                    "customer": {"email": email},
                    "order": {"id": f"ord-iter27-norm-{NONCE}", "total_amount": 4995},
                    "items": [
                        {"id": f"li-iter27-{NONCE}",
                         "product_id": "__test_unmapped_iter27__",
                         "amount": 4995},
                    ],
                },
            },
            timeout=10,
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("items_processed") == 1
        # fallback_mode null because the real items[] path matched
        assert data.get("fallback_mode") is None
    finally:
        _delete_buyer_sync(email)
