"""BYOK (Bring Your Own Key) vault for T4 / Founder users.

Stores user-supplied API keys for OpenAI, HeyGen, and fal.ai — encrypted at
rest with Fernet (symmetric AES-128-CBC + HMAC). The encryption key comes
from the `BYOK_ENCRYPTION_KEY` env var; if missing or malformed we DERIVE
a deterministic fallback from `JWT_SECRET` so the service still functions
in dev/preview without manual key generation.

Threat model:
  • Mongo dump attacker: keys are unreadable without BYOK_ENCRYPTION_KEY
  • App-server attacker (process memory): can decrypt — same as any vault
  • Customer-side leak: customer rotates the key on their provider side

API surface:
  POST   /api/user/byok           — save a key (service + key string)
  GET    /api/user/byok           — list configured services (no key material returned, ever)
  DELETE /api/user/byok/{service} — remove a saved key
  Module-level helper `get_byok_key(db, email, service) -> str | None`
    is the canonical retrieval used by render code paths.

Tier gate: only `byok_allowed` tiers (T4 / Pro Plus, Founder) can save keys.
Lower tiers get a 403 with an upgrade hint.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


logger = logging.getLogger("byok")


SERVICES: dict[str, dict] = {
    "anthropic": {
        "label": "Anthropic",
        "purpose": "Powers the Script Engine + thumbnail prompt rewriter with your own Claude quota",
        "key_hint": "starts with sk-ant-…",
    },
    "openai": {
        "label": "OpenAI",
        "purpose": "Unlocks the Premium 2 thumbnail engine (gpt-image-2)",
        "key_hint": "starts with sk-…",
    },
    "heygen": {
        "label": "HeyGen",
        "purpose": "Uses your own quota for Avatar video renders",
        "key_hint": "from your HeyGen dashboard → API",
    },
    "fal": {
        "label": "fal.ai",
        "purpose": "Uses your own quota for Faceless video renders",
        "key_hint": "format: <uuid>:<hex>",
    },
}


def _load_fernet() -> Fernet:
    """Return a Fernet instance from BYOK_ENCRYPTION_KEY, or a deterministic
    fallback derived from JWT_SECRET. The fallback path logs a single
    warning so the operator knows to set BYOK_ENCRYPTION_KEY in prod."""
    raw = (os.environ.get("BYOK_ENCRYPTION_KEY") or "").strip()
    if raw:
        try:
            return Fernet(raw.encode("utf-8"))
        except Exception:
            logger.warning("[byok] BYOK_ENCRYPTION_KEY is set but invalid (must be url-safe base64 32 bytes). Falling back to derived key.")
    # Deterministic fallback — same key across restarts so already-encrypted
    # keys stay decryptable. Derived from JWT_SECRET via SHA-256 → base64.
    jwt_secret = (os.environ.get("JWT_SECRET") or "f48-default").encode("utf-8")
    derived = base64.urlsafe_b64encode(hashlib.sha256(jwt_secret).digest())
    return Fernet(derived)


_FERNET = _load_fernet()


def _encrypt(plain: str) -> str:
    return _FERNET.encrypt(plain.encode("utf-8")).decode("ascii")


def _decrypt(token: str) -> Optional[str]:
    try:
        return _FERNET.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.warning("[byok] Failed to decrypt a stored key — encryption key changed?")
        return None


def _mask(plain: str) -> str:
    """Render a non-reversible preview of a key for the UI ('sk-…ax3F').
    Never leak this beyond list/save responses."""
    if not plain or len(plain) < 8:
        return "•••"
    return f"{plain[:3]}…{plain[-4:]}"


async def get_byok_key(db, email: str, service: str) -> Optional[str]:
    """Look up + decrypt a user's BYOK key for a given service. Returns
    None when no key is stored OR decryption fails (rotated env key).
    Side-effect: stamps `last_used_at` so the admin can spot dormant keys."""
    if not email or not service:
        return None
    doc = await db.byok_keys.find_one({"email": email, "service": service})
    if not doc:
        return None
    plain = _decrypt(doc.get("encrypted_key") or "")
    if not plain:
        return None
    # Fire-and-forget last_used stamp; failure here can NEVER fail the render.
    try:
        await db.byok_keys.update_one(
            {"_id": doc["_id"]},
            {"$set": {"last_used_at": datetime.now(timezone.utc).isoformat()}},
        )
    except Exception:
        pass
    return plain


class SaveKeyRequest(BaseModel):
    service: str = Field(..., min_length=1, max_length=32)
    key: str = Field(..., min_length=8, max_length=512)


def register_byok_routes(
    *,
    api: APIRouter,
    db,
    current_user_dep,
    dev_bypass_email: str,
    studio_grant_emails: set,
):
    """Mount /api/user/byok* endpoints on the /api router."""

    async def _require_byok_allowed(user) -> bool:
        """Returns True if this user can save BYOK keys. Owner + studio
        grants + founders = always allowed. Others require tier.byok_allowed."""
        if dev_bypass_email and user.email == dev_bypass_email:
            return True
        if user.email in studio_grant_emails:
            return True
        from tier_config import get_tier, tier_for_entitlements  # noqa: WPS433

        buyer = await db.buyers.find_one({"email": user.email}) or {}
        if buyer.get("founders"):
            return True
        tier_id = (buyer.get("tier") or "").strip().lower()
        if not tier_id:
            tier_id = tier_for_entitlements(list(buyer.get("entitlements") or [])).id
        return bool(get_tier(tier_id).byok_allowed)

    @api.get("/user/byok")
    async def list_keys(user=Depends(current_user_dep)):
        """Return the user's current key inventory. The masked preview
        (`hint`) is included for the UI's "you saved sk-…ax3F" copy but
        the FULL key is NEVER returned by any endpoint — once saved, the
        plaintext only exists in render-time decryption."""
        allowed = await _require_byok_allowed(user)
        cursor = db.byok_keys.find({"email": user.email})
        configured: dict[str, dict] = {}
        async for doc in cursor:
            svc = doc.get("service")
            if not svc:
                continue
            plain = _decrypt(doc.get("encrypted_key") or "") or ""
            configured[svc] = {
                "configured": True,
                "hint": _mask(plain),
                "created_at": doc.get("created_at"),
                "last_used_at": doc.get("last_used_at"),
            }
        return {
            "byok_allowed": allowed,
            "services": [
                {
                    "id": svc_id,
                    "label": meta["label"],
                    "purpose": meta["purpose"],
                    "key_hint": meta["key_hint"],
                    **(configured.get(svc_id) or {"configured": False}),
                }
                for svc_id, meta in SERVICES.items()
            ],
        }

    @api.post("/user/byok")
    async def save_key(payload: SaveKeyRequest, user=Depends(current_user_dep)):
        if not await _require_byok_allowed(user):
            raise HTTPException(
                status_code=403,
                detail={
                    "reason": "byok_not_allowed",
                    "message": "Bring-your-own-key is part of the Pro Plus tier. Upgrade to unlock.",
                },
            )
        service = payload.service.strip().lower()
        if service not in SERVICES:
            raise HTTPException(status_code=400, detail=f"Unknown service '{service}'.")
        key = payload.key.strip()
        if len(key) < 8:
            raise HTTPException(status_code=400, detail="That key looks too short.")

        now_iso = datetime.now(timezone.utc).isoformat()
        encrypted = _encrypt(key)

        # Upsert by (email, service) — saving a new key REPLACES the old one
        # cleanly. `created_at` is preserved on update via $setOnInsert.
        await db.byok_keys.update_one(
            {"email": user.email, "service": service},
            {
                "$set": {
                    "encrypted_key": encrypted,
                    "updated_at": now_iso,
                },
                "$setOnInsert": {
                    "email": user.email,
                    "service": service,
                    "created_at": now_iso,
                    "last_used_at": None,
                },
            },
            upsert=True,
        )
        return {
            "ok": True,
            "service": service,
            "hint": _mask(key),
        }

    @api.delete("/user/byok/{service}")
    async def delete_key(service: str, user=Depends(current_user_dep)):
        service = service.strip().lower()
        result = await db.byok_keys.delete_one({"email": user.email, "service": service})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="No key saved for that service.")
        return {"ok": True}
