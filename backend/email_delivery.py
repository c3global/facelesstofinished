"""Transactional email delivery for magic-link sign-in.

Provider chain (first configured wins):
  1. Resend (api.resend.com) — Charity's account, sending domain
     faceless48.com. Fast, purpose-built for transactional email; login
     links need to arrive in seconds.
  2. GHL outbound webhook — the original wiring (ghl_integration.
     push_magic_link); the GHL workflow sends the actual email.
  3. Log-only fallback — the link is logged at INFO so the operator can
     retrieve it from backend logs while providers are being wired.

Config resolution per field: db.settings("email") > env var > default.
The db layer exists because the operator can't edit env vars on her
deployment platform — the Resend API key is pasted via the admin config
endpoint (PUT /api/admin/email/config) instead.

NOTE: the SENDING domain (faceless48.com) is independent of the APP
domain (faceless48.c3global.co). Resend only needs its DNS records on the
sending domain; every link inside the email still points at the app.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("f48.email")

RESEND_API_URL = "https://api.resend.com/emails"

DEFAULT_FROM = "Faceless to Finished <sign-in@faceless48.com>"

# Baked-in default Resend key (Charity's account, provided 2026-07-02).
# Lives in code because the operator can't edit env vars on her deployment
# platform. db.settings("email") and the RESEND_API_KEY env var both
# override it. TODO once Emergent env access returns: move this to an env
# var and ROTATE the key at resend.com → API Keys (revoke this one).
DEFAULT_RESEND_API_KEY = "re_Xnv4diji_3xBqgxv4NnLSjnT5V2zNUEcx"


async def get_email_config(db) -> dict:
    cfg = {
        "resend_api_key": (os.environ.get("RESEND_API_KEY") or "").strip()
        or DEFAULT_RESEND_API_KEY,
        "resend_from": (os.environ.get("RESEND_FROM") or "").strip() or DEFAULT_FROM,
    }
    doc = await db.settings.find_one({"_id": "email"}) or {}
    for key in cfg:
        val = doc.get(key)
        if isinstance(val, str) and val.strip():
            cfg[key] = val.strip()
    return cfg


def _magic_link_html(magic_link_url: str, ttl_minutes: int) -> str:
    """Branded, minimal HTML — single CTA, plain-text-ish fallback copy.
    Kept table-free and inline-styled for maximum client compatibility."""
    return f"""\
<div style="max-width:520px;margin:0 auto;padding:32px 24px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#111827;">
  <p style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#B45309;margin:0 0 12px;">Faceless to Finished</p>
  <h1 style="font-size:22px;margin:0 0 12px;">Your sign-in link</h1>
  <p style="font-size:15px;line-height:1.6;margin:0 0 24px;">
    Click the button below to sign in. This link works once and expires in
    {ttl_minutes} minutes.
  </p>
  <p style="margin:0 0 28px;">
    <a href="{magic_link_url}"
       style="display:inline-block;background:#F59E0B;color:#111827;font-weight:600;font-size:15px;padding:12px 28px;border-radius:8px;text-decoration:none;">
      Sign in to your Studio
    </a>
  </p>
  <p style="font-size:13px;line-height:1.6;color:#6B7280;margin:0 0 8px;">
    Button not working? Copy and paste this link into your browser:
  </p>
  <p style="font-size:12px;line-height:1.5;color:#6B7280;word-break:break-all;margin:0 0 24px;">{magic_link_url}</p>
  <p style="font-size:12px;line-height:1.6;color:#9CA3AF;margin:0;">
    Didn't request this? You can safely ignore this email — the link only
    works for someone with access to this inbox.
  </p>
</div>"""


async def send_via_resend(cfg: dict, *, email: str, magic_link_url: str, ttl_minutes: int) -> dict:
    """Send the magic-link email through Resend. Returns a status dict;
    never raises (callers fall through to the next provider on failure)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            r = await client.post(
                RESEND_API_URL,
                headers={"Authorization": f"Bearer {cfg['resend_api_key']}"},
                json={
                    "from": cfg["resend_from"],
                    "to": [email],
                    "subject": "Your Faceless to Finished sign-in link",
                    "html": _magic_link_html(magic_link_url, ttl_minutes),
                },
            )
        if r.status_code in (200, 201):
            rid = ""
            try:
                rid = (r.json() or {}).get("id", "")
            except Exception:
                pass
            return {"status": "sent", "provider": "resend", "id": rid}
        logger.warning("[resend] send failed %s: %s", r.status_code, r.text[:300])
        return {"status": "error", "provider": "resend", "http_status": r.status_code}
    except Exception as exc:  # noqa: BLE001 — delivery must never 500 auth
        logger.warning("[resend] send crashed: %s: %s", type(exc).__name__, exc)
        return {"status": "error", "provider": "resend", "reason": str(exc)[:200]}


async def send_magic_link_email(
    db, *, email: str, magic_link_url: str, expires_at_iso: str,
    ttl_minutes: int, log_activity,
) -> dict:
    """Deliver the magic-link email via the first working provider.
    Resend → GHL → log-only. Always returns a status dict."""
    cfg = await get_email_config(db)

    if cfg["resend_api_key"]:
        result = await send_via_resend(
            cfg, email=email, magic_link_url=magic_link_url, ttl_minutes=ttl_minutes,
        )
        if result["status"] == "sent":
            return result
        # Resend configured but failing — fall through to GHL so a bad key
        # or an outage doesn't lock every customer out of sign-in.
        try:
            await log_activity("magic_link_send_failed", email,
                               {"provider": "resend", **result})
        except Exception:
            pass

    try:
        import ghl_integration  # noqa: PLC0415 — optional provider
        if ghl_integration.is_configured():
            return await ghl_integration.push_magic_link(
                email=email,
                magic_link_url=magic_link_url,
                expires_at_iso=expires_at_iso,
                ttl_minutes=ttl_minutes,
                log_activity=log_activity,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ghl] magic-link push crashed: %s: %s", type(exc).__name__, exc)

    # Last resort: log the link so the operator can retrieve it manually.
    logger.info("[magic-link] no email provider configured — link for %s (expires %s): %s",
                email, expires_at_iso, magic_link_url)
    return {"status": "logged_only"}
