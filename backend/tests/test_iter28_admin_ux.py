"""Regression: BuyersTab must auto-refresh so new webhook-granted buyers
appear in the Admin UI without manual reload. Per Charity's 2026-02-23
feedback: 'when they purchase, if they go to click on it and it's not
showing anything in admin, that's an issue.'

Also: Studio nav must be visible to non-Studio users with an Upgrade
pill (was previously hidden entirely → no conversion path).

Also: Shorts paywall CTA now points at the direct payment link, not the
sales page.

Source-level checks; runs in <100ms, no DB, no HTTP. Companion to the
live screenshot smoke tests that already verified the actual rendered UI.
"""
import re
from pathlib import Path

BUYERS_TAB = Path("/app/frontend/src/components/admin/BuyersTab.jsx").read_text()
HEADER = Path("/app/frontend/src/components/Header.jsx").read_text()
APP_JS = Path("/app/frontend/src/App.js").read_text()


def test_buyers_tab_has_auto_refresh_interval():
    """Polling interval must exist so new webhook buyers surface without
    manual refresh. Interval should be reasonable (5-60s); a too-fast
    interval would hammer the DB."""
    assert "setInterval" in BUYERS_TAB, "auto-refresh setInterval missing"
    # Find the interval value — must be between 5_000 and 60_000 ms
    m = re.search(r"setInterval\([^,]+,\s*(\d[\d_]*)\s*\)", BUYERS_TAB)
    assert m, "could not parse setInterval period"
    period_ms = int(m.group(1).replace("_", ""))
    assert 5_000 <= period_ms <= 60_000, (
        f"buyers auto-refresh period {period_ms}ms is outside the "
        f"5s-60s sane range"
    )


def test_buyers_tab_pauses_polling_when_tab_hidden():
    """Polling should pause when the browser tab is hidden so we don't
    drain the DB on tabs left open overnight."""
    assert "document.hidden" in BUYERS_TAB, (
        "must check document.hidden to pause polling on hidden tabs"
    )


def test_buyers_tab_refreshes_on_tab_focus():
    """When the tab regains focus the list should refresh immediately —
    covers the 'webhook fired while tab was hidden' case."""
    assert "visibilitychange" in BUYERS_TAB, (
        "must listen to document visibilitychange so the list refreshes "
        "the moment the admin returns to the tab"
    )


def test_buyers_tab_cleans_up_interval_on_unmount():
    """The effect must return a cleanup that calls clearInterval to avoid
    a memory leak when the admin tab is destroyed."""
    assert "clearInterval" in BUYERS_TAB


def test_studio_nav_is_always_visible():
    """Header must render the Studio nav link UNCONDITIONALLY (no
    `user?.entitlements?.includes('studio') && <NavLink ...>` wrapper).
    The paywall handles the unauthorized landing."""
    # Find the Studio NavLink and confirm it is NOT wrapped in a
    # `user?.entitlements?.includes("studio") && (` conditional.
    m = re.search(
        r'(\S+\s*&&\s*\(\s*\n\s*<NavLink[^>]*to="/studio")',
        HEADER,
    )
    assert not m, (
        f"Studio NavLink must NOT be wrapped in an entitlement-gated "
        f"conditional — was: {m.group(1) if m else None}"
    )
    # And it MUST exist (not removed entirely)
    assert 'to="/studio"' in HEADER, "Studio NavLink must exist"


def test_studio_nav_shows_upgrade_pill_to_non_entitled_users():
    """Users without the `studio` entitlement see an Upgrade pill next to
    the Studio nav link so they understand the feature is gated."""
    assert "nav-studio-upgrade-pill" in HEADER, (
        "Upgrade pill testid missing on non-entitled Studio nav"
    )
    # The pill must be conditionally rendered based on entitlements
    assert re.search(
        r'!user\?\.entitlements\?\.includes\("studio"\)\s*&&',
        HEADER,
    ), (
        "Upgrade pill must be conditional on the user NOT having studio "
        "entitlement"
    )


def test_shorts_paywall_uses_direct_payment_link():
    """Shorts EntitlementPaywall CTA must point at the direct payment link
    (per 2026-02-23 customer request), NOT the sales page."""
    # Find the shorts block in EntitlementPaywall
    m = re.search(
        r"shorts:\s*\{(.*?)\},",
        APP_JS,
        re.DOTALL,
    )
    assert m, "could not locate shorts paywall meta in App.js"
    shorts_block = m.group(1)
    assert "hub.c3global.co/payment-link/6a151b0d3f4eb69bef72feae" in shorts_block, (
        "Shorts paywall CTA must point at the direct payment link"
    )
    # Old sales page link must be gone from the shorts block
    assert "sprint.c3global.co/faceless" not in shorts_block, (
        "old sales page link still present in shorts paywall meta"
    )


def test_studio_paywall_unchanged_per_user_request():
    """Charity explicitly said the Studio sales page link is correct.
    Don't accidentally change it during the Shorts update."""
    m = re.search(r"studio:\s*\{(.*?)\},", APP_JS, re.DOTALL)
    assert m
    assert "sprint.c3global.co/f2f48studio" in m.group(1), (
        "Studio paywall sales page link must remain intact"
    )
