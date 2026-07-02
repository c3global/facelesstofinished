"""Magic-link authentication for F2F48 Studio.

Replaces the previous "type-your-email-and-you're-in" security hole with a
real passwordless flow:

    1. User submits email at /login.
    2. Backend generates a cryptographically random token, stores it in
       `db.magic_link_tokens` with a 15-minute expiry, and pushes an
       outbound webhook to GoHighLevel (GHL).
    3. GHL workflow sends the actual email (via its own SMTP/email node)
       containing the magic link URL:
           `<APP_BASE_URL>/api/auth/verify-magic-link?token=<token>`
    4. User clicks the link → backend verifies the token, marks it used,
       runs the existing entitlement lookup (DEV_BYPASS_EMAIL, STUDIO_GRANT,
       db.buyers), and 302-redirects to `<APP_BASE_URL>/auth/callback#jwt=<JWT>`
    5. Frontend `/auth/callback` page reads the JWT from the URL hash,
       stores it in localStorage as `f48_studio_token`, and navigates to
       `/scripts` — same signed-in state as the old direct-login flow.

The hash-based JWT delivery is intentional — URL fragments are never sent
to the server (nor logged by intermediary proxies), so the token doesn't
leak into backend access logs even when the browser follows the redirect.

Anti-enumeration: the request endpoint ALWAYS returns `{ok: true}` — the
UI never learns whether a given email is on file. Rate-limiting caps
magic-link requests to 5 per email per 15 minutes to prevent abuse.

Env vars:
  - MAGIC_LINK_TTL_MINUTES  (optional, default 15)
  - APP_BASE_URL           (required in production — the origin the
                             magic link and callback resolve against;
                             falls back to the request `Origin` header
                             on preview so no manual config needed)
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("f48.auth.magic")

MAGIC_LINK_TTL_MINUTES = int(os.environ.get("MAGIC_LINK_TTL_MINUTES", "15"))
MAGIC_LINK_RATE_LIMIT_PER_15MIN = 5


def generate_token() -> str:
    """Cryptographically-random URL-safe token (~43 chars)."""
    return secrets.token_urlsafe(32)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_indexes(db) -> None:
    """Create MongoDB indexes for the magic-link collection. Called once at
    backend startup. TTL index on `expires_at` auto-purges expired tokens so
    the collection never grows unbounded."""
    try:
        await db.magic_link_tokens.create_index("token", unique=True)
        await db.magic_link_tokens.create_index("email")
        await db.magic_link_tokens.create_index(
            "expires_at", expireAfterSeconds=0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[magic-link] index create failed: %s", exc)


async def is_rate_limited(db, email: str) -> bool:
    """Return True if the email has requested >= 5 links in the last 15
    minutes. Prevents mailbox flooding."""
    cutoff = now_utc() - timedelta(minutes=15)
    count = await db.magic_link_tokens.count_documents({
        "email": email,
        "created_at": {"$gte": cutoff.isoformat()},
    })
    return count >= MAGIC_LINK_RATE_LIMIT_PER_15MIN


async def create_token(db, *, email: str, ip: str = "", redeem_code: str = "") -> tuple[str, datetime]:
    """Insert a fresh single-use token for `email`. Returns (token, expiry).

    `redeem_code` (optional) rides along with the token: a redemption code /
    AppSumo license key (or `oauth:<code>` for the AppSumo OAuth redirect
    flow) that verify-magic-link applies AFTER email ownership is proven.
    This is how brand-new AppSumo buyers get provisioned — they have no
    buyer record yet, so redemption must happen inside the sign-in flow."""
    token = generate_token()
    created = now_utc()
    expires = created + timedelta(minutes=MAGIC_LINK_TTL_MINUTES)
    await db.magic_link_tokens.insert_one({
        "token": token,
        "email": email.strip().lower(),
        "created_at": created.isoformat(),
        "expires_at": expires,   # datetime for TTL index
        "used_at": None,
        "ip": ip[:64],
        "redeem_code": (redeem_code or "").strip()[:256],
    })
    return token, expires


async def consume_token_full(db, *, token: str) -> Optional[dict]:
    """Validate + single-use consume `token`. Returns {"email", "redeem_code"}
    when valid, or None when the token is missing/expired/already-used.

    Uses an atomic `find_one_and_update` so two concurrent verify hits on
    the same token can't both succeed."""
    now = now_utc()
    doc = await db.magic_link_tokens.find_one_and_update(
        {
            "token": token,
            "used_at": None,
            "expires_at": {"$gt": now},
        },
        {"$set": {"used_at": now.isoformat()}},
    )
    if not doc:
        return None
    email = (doc.get("email") or "").strip().lower()
    if not email:
        return None
    return {"email": email, "redeem_code": (doc.get("redeem_code") or "").strip()}


async def consume_token(db, *, token: str) -> Optional[str]:
    """Back-compat wrapper around consume_token_full — email only."""
    doc = await consume_token_full(db, token=token)
    return doc["email"] if doc else None


def build_magic_link_url(base_url: str, token: str) -> str:
    base = (base_url or "").rstrip("/")
    return f"{base}/api/auth/verify-magic-link?token={token}"


def build_callback_url(base_url: str, jwt_token: str, *, email: str = "") -> str:
    """Frontend callback URL. JWT lives in the URL fragment so it never
    hits the server (or intermediary access logs)."""
    base = (base_url or "").rstrip("/")
    # Email hint is optional — lets the callback page personalize the
    # welcome toast without an extra `/auth/me` round-trip.
    frag = f"jwt={jwt_token}"
    if email:
        frag += f"&email={email}"
    return f"{base}/auth/callback#{frag}"


def resolve_base_url(request, fallback: str = "") -> str:
    """Best-effort resolution of the origin the magic link / callback URL
    should point at.

    Priority:
      1. `APP_BASE_URL` env var (set this in production for stability).
      2. Request `Origin` header (the frontend's origin — same host as
         the backend in the emergent preview / production ingress).
      3. Request `Referer` header (strip path).
      4. Explicit fallback argument.
    """
    env = (os.environ.get("APP_BASE_URL") or "").strip()
    if env:
        return env.rstrip("/")
    origin = (request.headers.get("origin") or "").strip()
    if origin:
        return origin.rstrip("/")
    referer = (request.headers.get("referer") or "").strip()
    if referer:
        # Strip anything after the path so we get scheme+host only.
        try:
            from urllib.parse import urlparse
            u = urlparse(referer)
            if u.scheme and u.netloc:
                return f"{u.scheme}://{u.netloc}"
        except Exception:
            pass
    return (fallback or "").rstrip("/")
