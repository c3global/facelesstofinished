"""
migrate_tiers.py — one-shot migration for the v1.20.5 tier pivot.

Renames tier ids on `db.buyers` from the old AppSumo t1/t2/t3 naming
to the new Community-membership naming:

  Old tier field       Old ents                                 → New tier
  ─────────────────────────────────────────────────────────────────────────
  "t1"                 (base, shorts)                           → "legacy"
  "t2"                 (base, shorts, studio)                   → "founder"
  "t3"                 (base, shorts, studio, byok)             → "founder"
  "founder"            (any)                                    → "founder"    (untouched)
  "" or missing        (base,)                                  → "starter"
  "" or missing        (base, shorts)                           → "legacy"
  "" or missing        (base, shorts, studio)                   → "founder"
  "" or missing        (base, shorts, studio, byok)             → "founder"
  anything else        (partial / unknown ents)                 → REPORTED, not touched

Also stamps `byok` entitlement + `byokAllowed: true` on every migrated
buyer since v1.20.5 turns BYOK on for all tiers.

Usage (dry-run — recommended first):
    python /app/backend/tools/migrate_tiers.py

Usage (apply changes for real):
    python /app/backend/tools/migrate_tiers.py --apply

Idempotent — re-running after a successful apply is a no-op.
"""

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import datetime, timezone

# Support running from repo root or from /app/backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


def _classify(buyer: dict) -> tuple[str, str, list[str], str]:
    """Return (new_tier_id, reason, new_ents, warn).

    `warn` is non-empty when the row's tier/entitlement combo is unusual
    and the operator should eyeball it before applying."""
    ents = {e.strip().lower() for e in (buyer.get("entitlements") or [])}
    tier_field = (buyer.get("tier") or "").strip().lower()
    founder_flag = bool(buyer.get("founders"))

    if tier_field == "founder" or founder_flag:
        return ("founder", "founder flag / tier already set", sorted(ents | {"base", "shorts", "studio", "byok"}), "")

    if tier_field in ("premium",):
        return ("premium", "premium tier already set (post-migration re-run)", sorted(ents | {"base", "shorts", "studio", "byok"}), "")

    if tier_field in ("legacy", "starter"):
        # Already migrated. Ensure byok is present + entitlements match tier.
        base_ents = {
            "starter": {"base", "byok"},
            "legacy": {"base", "shorts", "byok"},
        }[tier_field]
        return (tier_field, f"{tier_field} already set (post-migration re-run)", sorted(ents | base_ents), "")

    # Old AppSumo t1/t2/t3 → map
    if tier_field == "t1":
        return ("legacy", "t1 → legacy (had shorts)", sorted(ents | {"base", "shorts", "byok"}), "")
    if tier_field == "t2":
        return ("founder", "t2 → founder (paid for Studio lifetime)", sorted(ents | {"base", "shorts", "studio", "byok"}), "")
    if tier_field == "t3":
        return ("founder", "t3 → founder + BYOK", sorted(ents | {"base", "shorts", "studio", "byok"}), "")

    # No tier field — infer from entitlements
    has_studio = "studio" in ents
    has_shorts = "shorts" in ents
    has_base = "base" in ents

    if has_studio:
        return ("founder", "inferred from studio entitlement", sorted(ents | {"base", "shorts", "studio", "byok"}), "")
    if has_shorts and has_base:
        return ("legacy", "inferred from base+shorts entitlements", sorted(ents | {"base", "shorts", "byok"}), "")
    if has_base and not has_shorts:
        return ("starter", "inferred from base-only entitlement", sorted(ents | {"base", "byok"}), "")

    # Weird partial ents (e.g., ("studio",) alone or ("shorts",) alone)
    # — flag for manual review, don't auto-classify.
    return ("", "UNKNOWN / partial entitlements — manual review required", sorted(ents), f"weird ents: {sorted(ents)}")


async def main(apply_changes: bool):
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME must be set in the environment.")
        return 1

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    print(f"Connected: db={db_name}")
    print(f"Mode: {'APPLY (will write)' if apply_changes else 'DRY RUN (no writes)'}")
    print("=" * 78)

    from_counts: Counter = Counter()
    to_counts: Counter = Counter()
    warnings: list[tuple[str, str]] = []
    plan: list[tuple[str, str, list[str], str]] = []  # (email, new_tier, new_ents, reason)

    async for b in db.buyers.find({}, {"email": 1, "tier": 1, "entitlements": 1, "founders": 1}):
        email = b.get("email") or "(no email)"
        old_tier = (b.get("tier") or "").strip().lower() or "(none)"
        from_counts[old_tier] += 1
        new_tier, reason, new_ents, warn = _classify(b)
        if not new_tier:
            warnings.append((email, warn))
            continue
        to_counts[new_tier] += 1
        plan.append((email, new_tier, new_ents, reason))

    print(f"Buyers examined: {sum(from_counts.values())}")
    print()
    print("BEFORE (current tier field):")
    for t, n in from_counts.most_common():
        print(f"  {t}: {n}")
    print()
    print("AFTER (target tier field):")
    for t, n in to_counts.most_common():
        print(f"  {t}: {n}")
    print()

    if warnings:
        print(f"⚠️  {len(warnings)} buyer(s) require manual review — SKIPPED:")
        for email, warn in warnings:
            print(f"   {email}: {warn}")
        print()

    if not plan:
        print("Nothing to migrate.")
        return 0

    print(f"Plan: {len(plan)} buyer(s) to update.")
    if not apply_changes:
        print()
        print("Dry-run only. Re-run with --apply to write.")
        return 0

    # Apply
    now_iso = datetime.now(timezone.utc).isoformat()
    updated = 0
    for email, new_tier, new_ents, reason in plan:
        result = await db.buyers.update_one(
            {"email": email},
            {"$set": {
                "tier": new_tier,
                "entitlements": new_ents,
                "byokAllowed": True,  # v1.20.5: BYOK-for-all
                "tierMigratedAt": now_iso,
                "tierMigrationReason": reason,
                "updatedAt": now_iso,
            }},
        )
        if result.modified_count > 0:
            updated += 1
    print(f"✅ Updated {updated}/{len(plan)} buyers.")

    # Log the migration in activity
    await db.activity.insert_one({
        "id": f"tier_migration_{now_iso}",
        "ts": now_iso,
        "type": "tier_migration_v1_20_5",
        "email": "system",
        "detail": {
            "buyers_examined": sum(from_counts.values()),
            "buyers_updated": updated,
            "buyers_skipped": len(warnings),
            "from_distribution": dict(from_counts),
            "to_distribution": dict(to_counts),
        },
    })
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.apply)))
