#!/usr/bin/env python3
"""
sync_roadmap_to_production.py
==============================

One-shot script that syncs today's 3 new SHIPPED roadmap items + the
updated Cinematic Faceless blurb from preview → your live site's
roadmap database.

WHAT IT DOES
------------
1. Signs in as admin (via DEV_BYPASS_EMAIL → /api/auth/check).
2. Reads the current roadmap.
3. Adds any of these 3 SHIPPED items that aren't already there:
     • Passwordless magic-link sign-in
     • AppSumo redemption + auto-provisioning
     • Studio Founder auto-unlock via Pinball
4. Updates the "Cinematic Faceless (true text-to-video)" blurb.
5. Prints a summary. Idempotent — safe to run multiple times.

HOW TO RUN
----------

    python3 sync_roadmap_to_production.py

That's it. Uses default production URL + admin email baked in.

If /api/auth/check refuses (i.e., DEV_BYPASS isn't set on production),
sign in via the browser once, grab your JWT from DevTools:

    DevTools → Application → Local Storage → f48_studio_token

Then re-run with:

    F48_TOKEN='<paste JWT here>' python3 sync_roadmap_to_production.py

REQUIREMENTS
------------
    Python 3.7+ (no third-party libs — uses stdlib urllib).
"""
from __future__ import annotations

import json
import os
import sys
from urllib import request, error


# --------------------------------------------------------------------------
# Config — override with env vars if needed. Defaults point at Charity's
# production deployment + admin email.
# --------------------------------------------------------------------------
PROD_URL = os.environ.get("F48_URL", "https://faceless48.c3global.co").rstrip("/")
ADMIN_EMAIL = os.environ.get("F48_ADMIN_EMAIL", "drcharitycampbell@gmail.com")
TOKEN = os.environ.get("F48_TOKEN", "").strip()

# The 3 items to add if missing. Order + tags match preview state.
NEW_SHIPPED_ITEMS = [
    {
        "title": "Passwordless magic-link sign-in",
        "blurb": (
            "Enter your email and we'll send you a secure one-time link. "
            "Links expire in 15 minutes and can only be used once — your "
            "account is safe even if someone else knows your email."
        ),
        "tag": "New",
    },
    {
        "title": "AppSumo redemption + auto-provisioning",
        "blurb": (
            "AppSumo lifetime buyers redeem their license inside the "
            "Studio and get instant Starter / Pro / Pro Plus access — "
            "with entitlements, quotas, and BYOK all provisioned "
            "automatically."
        ),
        "tag": "AppSumo",
    },
    {
        "title": "Studio Founder auto-unlock via Pinball",
        "blurb": (
            "Studio Founder Lifetime buyers ($297 one-time or 3×$99 "
            "payment plan) now get truly unlimited access the instant "
            "Pinball fires the webhook — no manual admin grant needed. "
            "Full Founder-tier quotas from the very first sign-in."
        ),
        "tag": "New",
    },
]

CINEMATIC_BLURB_NEW = (
    "Upgrade Faceless mode from static-image slideshows to real motion "
    "video. For 9:16 vertical shorts (our primary output), Google Veo 3 "
    "Fast is the cost leader at ~$0.15/sec — half the price of Sora 2 "
    "Pro at the same aspect. We're pricing this as: Veo Fast in-app "
    "default, Sora 2 available for BYOK users who prefer OpenAI quality."
)


# --------------------------------------------------------------------------
# HTTP helpers — small wrappers around urllib so no requests/httpx needed.
# --------------------------------------------------------------------------
def http(method: str, path: str, *, body=None, token: str = "") -> tuple[int, dict]:
    url = f"{PROD_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as r:
            payload = r.read().decode("utf-8")
            return r.status, (json.loads(payload) if payload else {})
    except error.HTTPError as e:
        try:
            payload = e.read().decode("utf-8")
            return e.code, (json.loads(payload) if payload else {"detail": ""})
        except Exception:
            return e.code, {"detail": str(e)}
    except Exception as e:
        return 0, {"detail": f"{type(e).__name__}: {e}"}


def get_admin_token() -> str:
    global TOKEN
    if TOKEN:
        print(f"→ Using token from F48_TOKEN env var")
        return TOKEN
    print(f"→ Signing in as {ADMIN_EMAIL} via /api/auth/check …")
    status, body = http("POST", "/api/auth/check", body={"email": ADMIN_EMAIL})
    if status == 200 and body.get("token"):
        token = body["token"]
        print("  ✅ signed in")
        return token
    print(f"  ❌ /api/auth/check returned HTTP {status}: {body}")
    print()
    print("DEV_BYPASS isn't enabled on production. Fallback:")
    print("  1. Sign in at https://faceless48.c3global.co/login")
    print("  2. Open DevTools → Application → Local Storage")
    print("  3. Copy the value of `f48_studio_token`")
    print("  4. Re-run this script:")
    print(f"     F48_TOKEN='<paste>' python3 {sys.argv[0]}")
    sys.exit(1)


# --------------------------------------------------------------------------
# Main sync.
# --------------------------------------------------------------------------
def main() -> None:
    print(f"F2F48 Roadmap Sync → {PROD_URL}")
    print("=" * 60)

    token = get_admin_token()

    print("\n→ Reading current roadmap …")
    status, body = http("GET", "/api/roadmap")
    if status != 200:
        print(f"  ❌ /api/roadmap returned HTTP {status}: {body}")
        sys.exit(1)

    # Flatten all items into a title→item map for quick lookup.
    existing = {}
    for col in body.get("columns", []):
        for item in col.get("items", []):
            existing[item.get("title", "").strip().lower()] = item
    print(f"  📖 found {len(existing)} existing items across all columns")

    # ---- Add the 3 new SHIPPED items (skip if already there). ----
    added = 0
    skipped = 0
    for item in NEW_SHIPPED_ITEMS:
        key = item["title"].strip().lower()
        if key in existing:
            print(f"  ⏭  SKIP (already there): {item['title']}")
            skipped += 1
            continue
        payload = {
            "column": "shipped",
            "title": item["title"],
            "blurb": item["blurb"],
            "tag": item["tag"],
        }
        status, resp = http(
            "POST", "/api/admin/roadmap/items", body=payload, token=token,
        )
        if status == 200:
            print(f"  ✅ ADDED: {item['title']}")
            added += 1
        else:
            print(f"  ❌ FAILED to add {item['title']} → HTTP {status}: {resp}")

    # ---- Update the Cinematic Faceless blurb. ----
    print()
    cine = existing.get("cinematic faceless (true text-to-video)")
    if cine and cine.get("id"):
        status, resp = http(
            "PATCH",
            f"/api/admin/roadmap/items/{cine['id']}",
            body={"blurb": CINEMATIC_BLURB_NEW},
            token=token,
        )
        if status == 200:
            print("  ✅ UPDATED blurb for: Cinematic Faceless (true text-to-video)")
        else:
            print(f"  ❌ FAILED to update Cinematic Faceless → HTTP {status}: {resp}")
    else:
        print("  ⚠  'Cinematic Faceless' item not found on production (skipping blurb update)")

    print()
    print("=" * 60)
    print(f"Done. Added: {added}   Skipped (already there): {skipped}")
    print(f"Visit {PROD_URL}/roadmap to verify.")


if __name__ == "__main__":
    main()
