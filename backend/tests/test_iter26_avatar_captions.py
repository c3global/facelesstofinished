"""Regression: Avatar (HeyGen) render must run the same auto-subtitle
second pass as the Faceless pipeline when captions=True. Charity reported
on 2026-02-23 that picking 'Captions · Boxed · Bottom' on an HeyGen Avatar
render produced a final video with NO captions — the burn-in step was
silently skipped because it was only wired into _run_render_faceless.

These tests do source-level assertions on server.py to keep them fast and
loop-agnostic, matching the pattern in test_iter25_charity_bugs.py.
"""
import re
from pathlib import Path

SERVER_PY = Path("/app/backend/server.py").read_text()


def _extract_run_render_avatar() -> str:
    """Return the source text of the _run_render_avatar function only."""
    m = re.search(
        r"async def _run_render_avatar\(.*?\nasync def ",
        SERVER_PY,
        re.DOTALL,
    )
    assert m, "could not locate _run_render_avatar block"
    return m.group(0)


def test_avatar_render_calls_burn_in_captions():
    """The Avatar pipeline must invoke _burn_in_captions when the job has
    captions=True. Charity's bug repro: 'Captions · Boxed · Bottom' on a
    HeyGen render produced a final video with NO captions because the
    burn-in step lived only in the Faceless pipeline."""
    block = _extract_run_render_avatar()
    assert "_burn_in_captions(" in block, (
        "Avatar success path must call _burn_in_captions(...) to honor the "
        "captions=True request flag."
    )


def test_avatar_burn_in_call_passes_style_and_position():
    """The burn-in call must pass `caption_style` AND `caption_position`
    from the job doc (with sensible defaults) so HeyGen renders honor
    Charity's chip selection ('Captions · Boxed · Bottom')."""
    block = _extract_run_render_avatar()
    # The call should reference both fields off the job dict.
    assert 'job.get("caption_style")' in block, (
        "burn-in call must read job['caption_style']"
    )
    assert 'job.get("caption_position")' in block, (
        "burn-in call must read job['caption_position']"
    )


def test_avatar_burn_in_gated_on_captions_flag():
    """The burn-in MUST be conditional on `job['captions']` so users who
    pick 'Off' don't get charged the $0.10 auto-subtitle fee."""
    block = _extract_run_render_avatar()
    # Look for a gate of the shape `if ... job.get("captions"):` near the
    # _burn_in_captions call.
    burn_idx = block.find("_burn_in_captions(")
    assert burn_idx > 0
    # The 200 chars before the burn-in call must contain a captions gate.
    prelude = block[max(0, burn_idx - 400):burn_idx]
    assert 'job.get("captions")' in prelude, (
        "_burn_in_captions call must be guarded by job.get('captions') to "
        "avoid surprise charges when the user picks Off."
    )


def test_avatar_burn_in_charges_caption_fee():
    """When the burn-in succeeds, `CAPTION_BURN_COST_CENTS` must be added
    to `actual_cost_cents` so admin telemetry reflects the real spend."""
    block = _extract_run_render_avatar()
    burn_idx = block.find("_burn_in_captions(")
    # Look in the ~500 chars after the burn-in call for the cost addition.
    after = block[burn_idx:burn_idx + 800]
    assert "CAPTION_BURN_COST_CENTS" in after, (
        "after a successful burn-in we must add CAPTION_BURN_COST_CENTS to "
        "actual_cost_cents to keep cost telemetry consistent with Faceless."
    )


def test_avatar_burn_in_soft_fails_gracefully():
    """If _burn_in_captions returns None or raises, the avatar render must
    STILL ship the uncaptioned URL — a caption outage can't block a paid
    HeyGen render from delivering."""
    block = _extract_run_render_avatar()
    burn_idx = block.find("_burn_in_captions(")
    # The block around the burn-in call should contain a try/except so
    # exceptions don't bubble up and abort the render.
    surround = block[max(0, burn_idx - 200):burn_idx + 800]
    assert "try:" in surround and "except Exception" in surround, (
        "burn-in must be wrapped in try/except so caption failures don't "
        "abort the underlying HeyGen render."
    )
    # And there should be a `if captioned:` (or similar) so a None return
    # falls back to the uncaptioned URL.
    assert "if captioned" in surround, (
        "must handle the burn-in returning None by keeping the uncaptioned URL."
    )


def test_avatar_final_url_is_captioned_when_burn_in_succeeds():
    """The final_url passed to _finalize must be the CAPTIONED URL after a
    successful burn-in, not the raw HeyGen URL. Charity's screenshot showed
    the render finishing with the HeyGen URL even though captions=True."""
    block = _extract_run_render_avatar()
    # The success branch should reassign final_url from the burn-in return.
    assert re.search(r"final_url\s*=\s*captioned", block), (
        "after a successful burn-in, final_url must be reassigned to the "
        "captioned URL so _finalize ships the captioned video."
    )
    # _finalize must be called with final_url (not d.get('video_url') directly).
    assert "url=final_url" in block, (
        "_finalize must be called with the (possibly captioned) final_url, "
        "not the raw HeyGen URL."
    )
