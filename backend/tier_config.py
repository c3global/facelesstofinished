"""
Tier definitions — single source of truth for Studio access tiers.

This module is the ONLY place we encode tier sticker prices, monthly render
quotas, Avatar sub-caps, per-user kill-switch ceilings, and BYOK eligibility.
Backend gating (render endpoints, quota counter resets, kill-switch breakers),
admin UI labels, and customer-visible upgrade prompts all read from here so
prices / caps stay consistent across the app.

v1.20.5 pivot (Iter 65, 2026-08-10): AppSumo deal was denied. Pivoting to
a $127/mo Community Membership model. Tier IDs, labels, entitlements, and
pricing renamed to match the new business shape:

  starter — Script Engine + Thumbnail Engine only. No shorts, no studio.
            Existing off-platform customers. BYOK included.
  legacy  — Script + Thumbnail + Shorts. No studio.
            Old AppSumo t1 ("Starter" $49) buyers migrate here. BYOK included.
            Sunset tier — closed to new signups.
  founder — Script + Thumbnail + Shorts + Studio. LIFETIME one-time payment.
            Old AppSumo t2 + t3 + original founders all migrate here. BYOK
            included. Software feature set identical to Premium; the
            distinction is billing (lifetime one-time) and NO Community /
            other-software access (Community lives outside this codebase).
  premium — Script + Thumbnail + Shorts + Studio. $127/mo SUBSCRIPTION
            (special intro price; $197/mo full price). BYOK included. Comes
            with Community + other-software access (enforced outside this
            codebase; Studio just checks the entitlement set).

Design decisions (locked by user 2026-08-10):
  • BYOK is now ENABLED FOR EVERY TIER, not just Pro Plus. Power users at
    any level can plug in their own OpenRouter / HeyGen / ElevenLabs /
    Anthropic keys to bypass platform quotas + cost caps.
  • Founder and Premium have the SAME software entitlement set. They
    differ only in billing model (lifetime vs monthly) and Community
    access (Premium yes, Founder no — but Studio itself doesn't gate on
    community, that's Charity's external system).
  • No new "AppSumo" language anywhere. Legacy tier is functionally the
    old AppSumo Starter but doesn't reference AppSumo publicly.

Keep this file Python-only / no DB writes — pure data definitions consumed
by quota gating + cost projection logic elsewhere.
"""

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass(frozen=True)
class Tier:
    """One tier's enforced limits. Frozen so accidental mutation can't drift
    state mid-render (e.g., a render in flight reading a different cap than
    what the quota check used)."""

    id: str
    """Stable string id — used as the key in `buyers.tier` field."""

    label: str
    """Customer-facing tier name shown in admin UI + upgrade prompts."""

    sticker_cents: int
    """Sticker price in cents. Interpretation depends on `billing_cadence`:
    one-time payment for starter/legacy/founder, monthly subscription for
    premium. Zero for founder (grandfathered / lifetime, no ongoing charge)."""

    billing_cadence: str
    """`one_time` for lifetime buyers, `monthly` for recurring subscriptions."""

    entitlements: tuple[str, ...]
    """Entitlement strings auto-granted at tier provisioning. Must be a subset
    of KNOWN_ENTITLEMENTS in server.py."""

    render_quota_monthly: int
    """Faceless + Avatar combined monthly render cap. 0 = no renders allowed
    (script-only tiers). 9999 = effectively unlimited (Founder / Premium)."""

    avatar_sub_cap: int
    """Of the monthly render quota, how many can be Avatar (HeyGen)? Protects
    margin since Avatar costs 3-4x Faceless."""

    thumbnail_quota_monthly: int
    """Thumbnail-engine cap. 9999 = effectively unlimited."""

    thumbnail_premium_allowed: bool
    """Whether the user can pick the Premium thumbnail engine (newest OpenAI
    image model). False = locked to Standard + Fast."""

    monthly_cost_cap_cents: int
    """Kill-switch ceiling in cents. When this tier's infra spend on a single
    customer exceeds this in a calendar month, render endpoints return a 402
    until the cycle resets. 0 = no cap (Founder only)."""

    byok_allowed: bool
    """Whether the user can plug in their own fal.ai / HeyGen / OpenAI /
    Anthropic keys to bypass quotas + the cost cap. v1.20.5: TRUE for
    every tier — see module docstring."""

    is_founder_grandfather: bool = False
    """True for the FOUNDER tier — exempts the buyer from all quota + cost
    gates. New buyers must NEVER be assigned FOUNDER; it's stamped only on
    pre-existing legacy buyers and on Studio Founder direct-sale customers."""

    sprint_allowed: bool = True
    """Whether Content Sprint (5-variant shorts generation) is available."""

    is_public: bool = True
    """False for closed / sunset tiers that shouldn't appear on public
    pricing surfaces (e.g. legacy tier — grandfathered buyers keep it, new
    signups can't select it)."""

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------
# Canonical tier table. ORDER MATTERS — the admin UI lists them in this order
# (lowest sticker first → highest), and the upgrade-path resolver walks this
# list to find "next tier above current".
# ----------------------------------------------------------------------------

TIER_STARTER = Tier(
    id="starter",
    label="Starter",
    sticker_cents=0,                        # off-platform pricing; not sold via Studio checkout
    billing_cadence="one_time",
    entitlements=("base", "byok"),           # Script + Thumbnail + BYOK
    render_quota_monthly=0,                 # no faceless/avatar
    avatar_sub_cap=0,
    thumbnail_quota_monthly=20,
    thumbnail_premium_allowed=False,
    monthly_cost_cap_cents=500,             # $5 silent kill-switch
    byok_allowed=True,                       # v1.20.5: BYOK on for every tier
    sprint_allowed=False,
)

TIER_LEGACY = Tier(
    id="legacy",
    label="Legacy",
    sticker_cents=4_900,                    # historical $49 AppSumo t1 price
    billing_cadence="one_time",
    entitlements=("base", "shorts", "byok"),  # Script + Thumbnail + Shorts + BYOK
    render_quota_monthly=0,                 # no faceless/avatar (was $49 AppSumo Starter)
    avatar_sub_cap=0,
    thumbnail_quota_monthly=20,
    thumbnail_premium_allowed=False,
    monthly_cost_cap_cents=500,
    byok_allowed=True,
    sprint_allowed=False,
    is_public=False,                        # sunset — no new signups
)

# Founder = LIFETIME one-time Studio buyers (old AppSumo t2 $179 + t3 $349 +
# original direct-sale $297/3×$99 founders). Grandfathered. Same software
# feature set as Premium but NO Community/other-software access (that's
# enforced by Charity's external system, not Studio).
TIER_FOUNDER = Tier(
    id="founder",
    label="Founder",
    sticker_cents=0,                        # already paid, no recurring charge
    billing_cadence="one_time",
    entitlements=("base", "shorts", "studio", "byok"),
    render_quota_monthly=9_999,             # effectively unlimited
    avatar_sub_cap=9_999,
    thumbnail_quota_monthly=9_999,
    thumbnail_premium_allowed=True,
    monthly_cost_cap_cents=0,               # no cap — trusted founders
    byok_allowed=True,
    is_founder_grandfather=True,
    is_public=False,                        # not selectable on public pricing surfaces
)

# Premium = NEW $127/mo (intro) / $197/mo (full) subscription. Full Studio
# software access + Community + other-software (Community access enforced
# outside this codebase). The only publicly-purchasable tier going forward.
TIER_PREMIUM = Tier(
    id="premium",
    label="Premium",
    sticker_cents=12_700,                   # $127/mo intro; flip to 19_700 when intro window closes
    billing_cadence="monthly",
    entitlements=("base", "shorts", "studio", "byok"),
    render_quota_monthly=9_999,             # membership = effectively unlimited
    avatar_sub_cap=9_999,
    thumbnail_quota_monthly=9_999,
    thumbnail_premium_allowed=True,
    monthly_cost_cap_cents=25_000,          # $250/mo kill-switch (BYOK bypasses)
    byok_allowed=True,
)


# Order-preserved tuple (low → high). Used by the upgrade-path resolver.
# Legacy is INCLUDED here for admin UI ordering but is `is_public=False`
# so pricing surfaces can filter it out.
TIERS_ORDERED: tuple[Tier, ...] = (TIER_STARTER, TIER_LEGACY, TIER_FOUNDER, TIER_PREMIUM)

# Set of tier ids that are LEGITIMATELY redeemable via /api/licenses/redeem.
# Founder is intentionally excluded — Founder is granted by admin migration
# or Pinball webhook (Studio lifetime SKU), never by public code.
REDEEMABLE_TIER_IDS: frozenset[str] = frozenset({TIER_LEGACY.id, TIER_PREMIUM.id})

# Lookup map for O(1) access by id.
TIERS_BY_ID: dict[str, Tier] = {t.id: t for t in (TIER_STARTER, TIER_LEGACY, TIER_FOUNDER, TIER_PREMIUM)}

# Legacy AppSumo Licensing webhooks/licenses carrying NUMERIC tiers (1, 2, 3)
# still need a mapping in case any lingering redemptions land after the pivot.
# 1 → legacy (Shorts+Script), 2 → founder (Studio lifetime), 3 → founder + BYOK
# was already on by default. Founder is set explicitly here so post-pivot
# AppSumo redemptions honor the customer's original purchase promise.
APPSUMO_NUMERIC_TIER_MAP: dict[str, str] = {"1": "legacy", "2": "founder", "3": "founder"}

# Back-compat aliases so any old code path still referencing t1/t2/t3 keeps
# working during the migration window. The migration script rewrites
# buyers.tier field to the new ids; these aliases catch anything that
# somehow flows through unmigrated (e.g., a stale webhook payload).
_LEGACY_TIER_ID_ALIAS: dict[str, str] = {
    "t1": "legacy",
    "t2": "founder",
    "t3": "founder",
}


def appsumo_tier_to_tier_id(value) -> str:
    """Normalize a tier value from an external payload (AppSumo webhook,
    admin license upload) to an internal tier id.

    Accepts numerics (1, "2", 3.0 → via listing map), new-style ids
    ("starter", "PREMIUM"), legacy ids ("t1", "T3" → aliased to new
    equivalent), or anything else → "" so callers can reject it.
    Founder is never resolvable from external input by design."""
    if value is None:
        return ""
    s = str(value).strip().lower()
    if not s:
        return ""
    if s in TIERS_BY_ID:
        return s
    if s in _LEGACY_TIER_ID_ALIAS:
        return _LEGACY_TIER_ID_ALIAS[s]
    # "3.0" → "3" (JSON floats), "tier 2" → "2"
    s = s.replace("tier", "").strip()
    try:
        s = str(int(float(s)))
    except (ValueError, TypeError):
        return ""
    return APPSUMO_NUMERIC_TIER_MAP.get(s, "")


# ----------------------------------------------------------------------------
# Helpers consumed by render endpoints + admin UI.
# ----------------------------------------------------------------------------

def get_tier(tier_id: Optional[str]) -> Tier:
    """Resolve a tier by id with a safe fallback. Unknown ids fall back to
    Starter (most restrictive) rather than 500'ing — if a buyer record
    somehow has a corrupt `tier` field, we still gate them safely until the
    admin reassigns.

    Also accepts legacy t1/t2/t3 for back-compat with any code path that
    hasn't been migrated yet."""
    if not tier_id:
        return TIER_STARTER
    s = tier_id.strip().lower()
    if s in _LEGACY_TIER_ID_ALIAS:
        s = _LEGACY_TIER_ID_ALIAS[s]
    return TIERS_BY_ID.get(s, TIER_STARTER)


# ============================================================================
# Buyer provisioning + cycle helpers.
# ============================================================================

from datetime import datetime, timedelta, timezone

# Cycle length — 30 days from purchase / first provisioning, NOT calendar
# month. Rationale: customers buying near the end of a calendar month would
# otherwise lose almost-immediately if we reset on the 1st.
CYCLE_LENGTH_DAYS = 30


def assign_buyer_to_tier(*, tier_id: str, is_upgrade: bool = False) -> dict:
    """Compute the $set payload to stamp a buyer's tier + quota fields.

    Two modes:
      • is_upgrade=False (default, fresh provisioning) — also stamps a new
        cycleStartedAt / cycleResetsAt and zeroes the counters. Use this on
        Pinball webhook first-grant + admin first-grant.
      • is_upgrade=True — ONLY updates the tier fields. Keeps the existing
        cycle clock and counters untouched.

    Returns a flat dict ready for `db.buyers.update_one({...}, {"$set": ...})`.
    """
    t = get_tier(tier_id)
    now = datetime.now(timezone.utc)
    payload = {
        "tier": t.id,
        "entitlements": sorted(t.entitlements),
        "renderQuotaMonthly": t.render_quota_monthly,
        "avatarSubCap": t.avatar_sub_cap,
        "thumbnailQuotaMonthly": t.thumbnail_quota_monthly,
        "monthlyCostCapCents": t.monthly_cost_cap_cents,
        "byokAllowed": t.byok_allowed,
        "updatedAt": now.isoformat(),
    }
    if not is_upgrade:
        payload.update({
            "rendersThisCycle": 0,
            "avatarRendersThisCycle": 0,
            "thumbnailsThisCycle": 0,
            "monthlyCostCents": 0,
            "cycleStartedAt": now.isoformat(),
            "cycleResetsAt": (now + timedelta(days=CYCLE_LENGTH_DAYS)).isoformat(),
        })
    return payload


def fresh_cycle_payload() -> dict:
    """Counters + clock to advance a buyer's cycle."""
    now = datetime.now(timezone.utc)
    return {
        "rendersThisCycle": 0,
        "avatarRendersThisCycle": 0,
        "thumbnailsThisCycle": 0,
        "monthlyCostCents": 0,
        "cycleStartedAt": now.isoformat(),
        "cycleResetsAt": (now + timedelta(days=CYCLE_LENGTH_DAYS)).isoformat(),
        "updatedAt": now.isoformat(),
    }


def tier_for_entitlements(entitlements: list[str]) -> Tier:
    """Map a buyer's entitlement set to the most appropriate tier when the
    `tier` field hasn't been migrated yet.
    Precedence: founder (studio) > legacy (shorts, no studio) > starter (base only)."""
    ents = {e.strip().lower() for e in (entitlements or [])}
    if "studio" in ents:
        # Anyone with historical studio access maps to founder (lifetime,
        # grandfathered). Fresh premium subscribers must be assigned via
        # Pinball webhook or admin panel — never inferred from ents alone,
        # since the ents look identical to founder.
        return TIER_FOUNDER
    if "shorts" in ents:
        return TIER_LEGACY
    return TIER_STARTER
