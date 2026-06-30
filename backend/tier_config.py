"""
Tier definitions — single source of truth for AppSumo / Studio access tiers.

This module is the ONLY place we encode tier sticker prices, monthly render
quotas, Avatar sub-caps, per-user kill-switch ceilings, and BYOK eligibility.
Backend gating (render endpoints, quota counter resets, kill-switch breakers),
admin UI labels, and customer-visible upgrade prompts all read from here so
prices / caps stay consistent across the app.

Design decisions (locked by user 2026-06-29):
  • Quotas, not credits — simpler comprehension, refund-safe on AppSumo.
  • T1 / T2 bundle a small Faceless quota so every tier produces actual video,
    not just text. Improves AppSumo conversion (no "scripts only" perception).
  • T3 / T4 sub-cap Avatar renders separately because HeyGen costs 3-4x more
    than Faceless — protects margin on a lifetime deal.
  • Existing 39 buyers grandfather into FOUNDER tier — no quotas enforced
    (user explicitly said "leave them alone — they are unlimited founders").
  • T4 BYOK is a toggle, NOT a requirement. T4 users without their own keys
    still get a generous quota (40/mo) on platform infra. BYOK unlocks truly
    unlimited rendering by offloading cost to their fal.ai / HeyGen account.
  • $ kill-switch caps are SILENT (we don't expose cents to non-admins) —
    they pause renders at the threshold and alert the admin via Activity log.

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
    """AppSumo sticker price in cents. 0 for FOUNDER (grandfathered)."""

    entitlements: tuple[str, ...]
    """Entitlement strings auto-granted at tier provisioning. Must be a subset
    of KNOWN_ENTITLEMENTS in server.py."""

    render_quota_monthly: int
    """Faceless + Avatar combined monthly render cap. 0 = no renders allowed
    (script-only tiers). 9999 = effectively unlimited (Founder grandfather)."""

    avatar_sub_cap: int
    """Of the monthly render quota, how many can be Avatar (HeyGen)? Protects
    margin since Avatar costs 3-4x Faceless. Set to 0 for tiers that block
    Avatar entirely. Must be ≤ render_quota_monthly."""

    thumbnail_quota_monthly: int
    """Thumbnail-engine cap. 9999 = effectively unlimited."""

    thumbnail_premium_allowed: bool
    """Whether the user can pick the Premium thumbnail engine (newest OpenAI
    image model). False = locked to Standard + Fast."""

    monthly_cost_cap_cents: int
    """Kill-switch ceiling in cents. When this tier's infra spend on a single
    customer exceeds this in a calendar month, render endpoints return a 402
    until the cycle resets. 0 = no cap (FOUNDER only)."""

    byok_allowed: bool
    """Whether the user can plug in their own fal.ai / HeyGen / OpenAI keys
    to bypass quotas + the cost cap. T4 only by design."""

    is_founder_grandfather: bool = False
    """True for the FOUNDER tier — exempts the buyer from all quota + cost
    gates. New buyers must NEVER be assigned FOUNDER; it's stamped only on
    the 39 pre-existing buyers via a one-time migration."""

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------
# Canonical tier table. ORDER MATTERS — the admin UI lists them in this order
# (lowest sticker first → highest), and the upgrade-path resolver walks this
# list to find "next tier above current".
# ----------------------------------------------------------------------------

TIER_T1 = Tier(
    id="t1",
    label="Script Engine",
    sticker_cents=4_900,             # $49
    entitlements=("base",),
    render_quota_monthly=5,           # 5 free Faceless renders/month for tier credibility
    avatar_sub_cap=0,                 # No Avatar access at T1
    thumbnail_quota_monthly=20,
    thumbnail_premium_allowed=False,
    monthly_cost_cap_cents=500,       # $5 silent kill-switch
    byok_allowed=False,
)

TIER_T2 = Tier(
    id="t2",
    label="Scripts + Shorts",
    sticker_cents=9_900,             # $99
    entitlements=("base", "shorts"),
    render_quota_monthly=10,
    avatar_sub_cap=0,
    thumbnail_quota_monthly=50,
    thumbnail_premium_allowed=True,
    monthly_cost_cap_cents=1_000,    # $10 silent kill-switch
    byok_allowed=False,
)

TIER_T3 = Tier(
    id="t3",
    label="Studio Pro",
    sticker_cents=17_900,            # $179
    entitlements=("base", "shorts", "studio"),
    render_quota_monthly=15,
    avatar_sub_cap=5,                # 5 of the 15 can be Avatar
    thumbnail_quota_monthly=9_999,   # effectively unlimited
    thumbnail_premium_allowed=True,
    monthly_cost_cap_cents=2_000,    # $20 silent kill-switch
    byok_allowed=False,
)

TIER_T4 = Tier(
    id="t4",
    label="Studio Pro + BYOK",
    sticker_cents=34_900,            # $349
    entitlements=("base", "shorts", "studio", "byok"),
    render_quota_monthly=40,
    avatar_sub_cap=10,               # 10 of the 40 can be Avatar
    thumbnail_quota_monthly=9_999,
    thumbnail_premium_allowed=True,
    monthly_cost_cap_cents=5_000,    # $50 silent kill-switch (BYOK off path)
    byok_allowed=True,
)

TIER_FOUNDER = Tier(
    id="founder",
    label="Founder",
    sticker_cents=0,
    entitlements=("base", "shorts", "studio", "byok"),
    render_quota_monthly=9_999,
    avatar_sub_cap=9_999,
    thumbnail_quota_monthly=9_999,
    thumbnail_premium_allowed=True,
    monthly_cost_cap_cents=0,        # no cap — trusted founders
    byok_allowed=True,
    is_founder_grandfather=True,
)

# Order-preserved tuple (low → high sticker, then FOUNDER as a separate bucket).
TIERS_ORDERED: tuple[Tier, ...] = (TIER_T1, TIER_T2, TIER_T3, TIER_T4)

# Lookup map for O(1) access by id.
TIERS_BY_ID: dict[str, Tier] = {t.id: t for t in (TIER_T1, TIER_T2, TIER_T3, TIER_T4, TIER_FOUNDER)}


# ----------------------------------------------------------------------------
# Helpers consumed by render endpoints + admin UI.
# ----------------------------------------------------------------------------

def get_tier(tier_id: Optional[str]) -> Tier:
    """Resolve a tier by id with a safe fallback. Unknown ids fall back to T1
    (most restrictive paid tier) rather than 500'ing — if a buyer record
    somehow has a corrupt `tier` field, we still gate them safely until the
    admin reassigns."""
    if not tier_id:
        return TIER_T1
    return TIERS_BY_ID.get(tier_id.strip().lower(), TIER_T1)


# ============================================================================
# Buyer provisioning + cycle helpers (Group B foundation, AppSumo launch plan)
# ============================================================================

from datetime import datetime, timedelta, timezone

# Cycle length — 30 days from purchase / first provisioning, NOT calendar
# month. Rationale: customers buying near the end of a calendar month would
# otherwise lose almost-immediately if we reset on the 1st. Locked by user
# 2026-06-29: "every user gets exactly 30 days per cycle, anchored to their
# own purchase date."
CYCLE_LENGTH_DAYS = 30


def assign_buyer_to_tier(*, tier_id: str, is_upgrade: bool = False) -> dict:
    """Compute the $set payload to stamp a buyer's tier + quota fields.

    Two modes:
      • is_upgrade=False (default, fresh provisioning) — also stamps a new
        cycleStartedAt / cycleResetsAt and zeroes the counters. Use this on
        Pinball webhook first-grant + admin first-grant.
      • is_upgrade=True — ONLY updates the tier fields. Keeps the existing
        cycle clock and counters untouched. Locked by user: mid-cycle
        upgrades bump the cap immediately but keep the original 30-day
        clock so the buyer doesn't get a free reset.

    Returns a flat dict ready for `db.buyers.update_one({...}, {"$set": ...})`.
    """
    t = get_tier(tier_id)
    now = datetime.now(timezone.utc)
    payload = {
        "tier": t.id,
        "renderQuotaMonthly": t.render_quota_monthly,
        "avatarSubCap": t.avatar_sub_cap,
        "thumbnailQuotaMonthly": t.thumbnail_quota_monthly,
        "monthlyCostCapCents": t.monthly_cost_cap_cents,
        "byokAllowed": t.byok_allowed,
        "updatedAt": now.isoformat(),
    }
    if not is_upgrade:
        # Fresh cycle. Zero every counter and stamp clock fields.
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
    """Counters + clock to advance a buyer's cycle. Called by the cron loop
    when `cycleResetsAt <= now`. Does NOT touch `tier`, `renderQuotaMonthly`,
    or `avatarSubCap` — those persist across cycles by design."""
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
    `tier` field hasn't been migrated yet. Used by the one-time backfill
    script and by /api/admin/usage when a buyer pre-dates the tier system.
    Precedence: founder > t4(byok) > t3(studio) > t2(shorts) > t1(base)."""
    ents = {e.strip().lower() for e in (entitlements or [])}
    if "byok" in ents and "studio" in ents:
        return TIER_T4
    if "studio" in ents:
        return TIER_T3
    if "shorts" in ents:
        return TIER_T2
    if "base" in ents:
        return TIER_T1
    return TIER_T1  # safe default; admin can reclassify
