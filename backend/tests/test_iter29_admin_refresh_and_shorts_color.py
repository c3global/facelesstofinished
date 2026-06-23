"""Iter-29 regression: 3 things Charity asked for on 2026-02-23:

1. Activity tab must auto-refresh like Buyers tab (same low-overhead poll +
   visibilitychange listener). "That should've automatically been added."

2. Shorts B-roll cue display must STAND OUT — bright green / yellow per
   Charity. Was muted grey-on-grey. The on-screen TEXT cue (red box) must
   remain EXACTLY as-is per her explicit "don't change this please".

3. Copy-pasting a Short into a doc must preserve the same styling as the
   in-app view (b-roll green). The per-variant "Copy this Short" button
   was using plain-text-only writeText; switched to copyRichText with
   markdownToHtml so green B-roll cues survive the paste.

Source-level checks — runs in <100ms, no DB, no HTTP. Real visual
verification happens in the screenshot smoke test.
"""
import re
from pathlib import Path

ACTIVITY_TAB = Path("/app/frontend/src/components/admin/ActivityTab.jsx").read_text()
BUYERS_TAB = Path("/app/frontend/src/components/admin/BuyersTab.jsx").read_text()
APP_CSS = Path("/app/frontend/src/App.css").read_text()
SPRINT_RESULT = Path("/app/frontend/src/components/scripts/SprintResult.jsx").read_text()


# =========================================================================
# Activity tab auto-refresh (parity with iter-28 Buyers tab)
# =========================================================================
def test_activity_tab_has_auto_refresh_interval():
    """Same low-overhead polling as Buyers — surfaces new webhook events,
    render completions, and admin actions in real time."""
    assert "setInterval" in ACTIVITY_TAB, "ActivityTab missing auto-refresh setInterval"
    m = re.search(r"setInterval\([^,]+,\s*(\d[\d_]*)\s*\)", ACTIVITY_TAB)
    assert m, "could not parse Activity setInterval period"
    period_ms = int(m.group(1).replace("_", ""))
    assert 5_000 <= period_ms <= 60_000, (
        f"Activity auto-refresh period {period_ms}ms outside 5s-60s sane range"
    )


def test_activity_tab_pauses_on_hidden_tab():
    """No DB drain while the admin tab is in the background."""
    assert "document.hidden" in ACTIVITY_TAB


def test_activity_tab_refreshes_on_focus():
    """Covers the 'webhook fired while admin tab was hidden' case."""
    assert "visibilitychange" in ACTIVITY_TAB


def test_activity_tab_cleans_up_interval_on_unmount():
    """No leaked intervals when the admin tab unmounts."""
    assert "clearInterval" in ACTIVITY_TAB


def test_activity_polling_matches_buyers_period():
    """Both tabs should poll at the same cadence so the admin UI feels
    consistent across tabs."""
    a = re.search(r"setInterval\([^,]+,\s*(\d[\d_]*)\s*\)", ACTIVITY_TAB)
    b = re.search(r"setInterval\([^,]+,\s*(\d[\d_]*)\s*\)", BUYERS_TAB)
    assert a and b
    a_ms = int(a.group(1).replace("_", ""))
    b_ms = int(b.group(1).replace("_", ""))
    assert a_ms == b_ms, (
        f"Activity ({a_ms}ms) and Buyers ({b_ms}ms) should poll at the "
        f"same cadence for consistent admin UX"
    )


# =========================================================================
# Shorts B-roll cue display (bright green; TEXT pill unchanged)
# =========================================================================
def test_shorts_broll_cue_uses_bright_green():
    """`.phone-cue-broll` must use the same bright green (#4ADE80) the
    Long-form `.markdown .broll-cue` uses — visual language consistent
    across both engines."""
    m = re.search(r"\.phone-cue-broll\s*\{([^}]+)\}", APP_CSS)
    assert m, "could not locate .phone-cue-broll block"
    block = m.group(1)
    # Must reference the bright green hex
    assert "#4ADE80" in block, (
        f".phone-cue-broll must use #4ADE80 (matches Long-form broll-cue). "
        f"Got: {block!r}"
    )
    # Border-left should also use the green
    assert "border-left" in block and "#4ADE80" in block


def test_shorts_broll_tag_pill_uses_green_background():
    """The 'B-ROLL' tag pill itself should also stand out in green so it
    pairs visually with the cue text below."""
    assert re.search(
        r"\.phone-cue-broll\s+\.phone-cue-tag\s*\{[^}]*background:\s*#4ADE80",
        APP_CSS,
        re.IGNORECASE,
    ), "B-ROLL tag pill must have green background"


def test_shorts_onscreen_text_cue_unchanged_per_charity_request():
    """Charity: 'Right now, only the text on screen section stands out
    (don't change this please).' The on-screen cue still uses the
    platform-accent color-mix (red on YouTube, etc) — NOT touched."""
    m = re.search(r"\.phone-cue-onscreen\s*\{([^}]+)\}", APP_CSS)
    assert m, "could not locate .phone-cue-onscreen block"
    block = m.group(1)
    # Must still use color-mix with platform-accent (the unchanged rule)
    assert "color-mix" in block and "platform-accent" in block, (
        "On-screen TEXT cue must keep the platform-accent color-mix — "
        f"Charity explicitly asked us not to change it. Got: {block!r}"
    )
    # Specifically must NOT have inherited the new green
    assert "#4ADE80" not in block, (
        ".phone-cue-onscreen must NOT use the bright B-roll green"
    )


# =========================================================================
# Shorts copy preserves green B-roll styling when pasted
# =========================================================================
def test_sprint_result_imports_rich_clipboard_helpers():
    """The per-variant Copy button must import markdownToHtml + copyRichText
    so pasted Shorts keep the green B-roll styling."""
    assert "markdownToHtml" in SPRINT_RESULT
    assert "copyRichText" in SPRINT_RESULT
    assert 'from "./SectionCard"' in SPRINT_RESULT


def test_sprint_result_per_variant_copy_uses_rich_text():
    """The CopyShortButton handler must call copyRichText(text, html) —
    NOT navigator.clipboard.writeText alone."""
    # Find the CopyShortButton function body
    m = re.search(
        r"function CopyShortButton\([^)]*\)\s*\{(.*?)^\}",
        SPRINT_RESULT,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "could not locate CopyShortButton fn"
    body = m.group(1)
    assert "copyRichText" in body, (
        "CopyShortButton must use the rich-text clipboard path so B-roll "
        "cues paste green into Docs / Notion / Word"
    )
    assert "markdownToHtml" in body, (
        "must call markdownToHtml to inline the B-roll green styling "
        "before writing to the clipboard"
    )
    # The old plain-only path should be gone
    assert "navigator.clipboard.writeText(variantToClipboardText" not in body, (
        "old plain-text-only writeText call still present — "
        "must be replaced by copyRichText"
    )
