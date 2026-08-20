"""Per-model spec + registry for KIE.ai video models.

The KieProvider is model-agnostic. Each concrete model (Seedance 2.5,
Kling family, Veo, PixVerse, etc.) is described by a KieModelSpec that
carries:
  * The upstream model id
  * Pricing (per-second rates, split by resolution + whether the input
    is a video)
  * Duration + resolution + aspect ratio schema
  * The set of MotionInputModes the model supports
  * Field-name overrides where the model's KIE payload deviates from the
    default (e.g. Kling 2.1 uses ``image_url`` singular vs Seedance 2.5's
    ``first_frame_url``)

The KieModelSpec instances registered on module load are DELIBERATELY
env-configurable — Seedance 2.5 is included as an optional model, not
the default. Admin config chooses which model(s) are enabled per
deployment via KIE_MODELS_ENABLED (comma-separated) and per-model
overrides via KIE_<MODEL_SLUG>_* env vars.

Reference for Seedance 2.5 pricing (2026-08-15 KIE rate card, provided
by product):
  * 480p, non-video input: 14.0 ¢/output-second
  * 720p, non-video input: 31.5 ¢/output-second
  * 480p, video input:      8.5 ¢/billed-second
  * 720p, video input:     19.0 ¢/billed-second

Text-to-video and uploaded-image-to-video are BOTH treated as "no video
input" for billing purposes. Only requests that supply a reference video
URL trigger the "with video input" rate.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from .types import MotionInputMode


# ---- Pricing table --------------------------------------------------------


@dataclass(frozen=True)
class ResolutionPricing:
    """Per-resolution rate in USD cents per output second.

    ``per_sec_no_video_input``  — text-to-video and image-to-video calls
    ``per_sec_with_video_input`` — calls that reference an input video
    """

    per_sec_no_video_input: float
    per_sec_with_video_input: float


@dataclass(frozen=True)
class KieModelSpec:
    """Static description of a KIE model.

    Constructed once at module load; all fields are pure data so
    instances can be shared across requests safely.
    """

    slug: str  # short internal name, e.g. "seedance-2-5"
    model_id: str  # KIE upstream model id, e.g. "bytedance/seedance-2-5"
    pricing: dict[str, ResolutionPricing]  # keyed by resolution string
    allowed_resolutions: frozenset[str]
    allowed_aspects: frozenset[str]
    min_duration_s: int
    max_duration_s: int
    default_duration_s: int
    supported_modes: frozenset[MotionInputMode]
    #: If True, the model billed the full request even for image/text
    #: inputs when a reference video is present. All modern KIE video
    #: models behave this way as of 2026-08-15.
    billed_when_input_is_video: bool = True


# ---- Default specs (built-in; env can enable/disable per deployment) ------


def _seedance_2_5_default() -> KieModelSpec:
    """Optional Seedance 2.5 spec.

    Pricing pulled from env with the KIE rate card values as defaults.
    """
    return KieModelSpec(
        slug="seedance-2-5",
        model_id="bytedance/seedance-2-5",
        pricing={
            "480p": ResolutionPricing(
                per_sec_no_video_input=float(
                    os.environ.get("KIE_SEEDANCE_2_5_PRICE_CENTS_480P_NO_VIDEO_PER_SEC", "14.0")
                ),
                per_sec_with_video_input=float(
                    os.environ.get("KIE_SEEDANCE_2_5_PRICE_CENTS_480P_VIDEO_PER_SEC", "8.5")
                ),
            ),
            "720p": ResolutionPricing(
                per_sec_no_video_input=float(
                    os.environ.get("KIE_SEEDANCE_2_5_PRICE_CENTS_720P_NO_VIDEO_PER_SEC", "31.5")
                ),
                per_sec_with_video_input=float(
                    os.environ.get("KIE_SEEDANCE_2_5_PRICE_CENTS_720P_VIDEO_PER_SEC", "19.0")
                ),
            ),
        },
        allowed_resolutions=frozenset({"480p", "720p"}),
        allowed_aspects=frozenset({"1:1", "4:3", "3:4", "16:9", "9:16", "21:9", "adaptive"}),
        min_duration_s=4,
        max_duration_s=30,
        default_duration_s=5,
        supported_modes=frozenset({
            MotionInputMode.TEXT,
            MotionInputMode.FIRST_FRAME,
            MotionInputMode.FIRST_AND_LAST_FRAME,
            MotionInputMode.MULTIMODAL_REFERENCE,
        }),
    )


# Registered models. Add more as needed. Each entry is a lazily-built spec
# so the constructor reads env vars at build-time — tests can monkeypatch
# env then call reload_specs() to refresh.
_SPEC_BUILDERS: dict[str, Callable[[], KieModelSpec]] = {
    "seedance-2-5": _seedance_2_5_default,
}

_SPEC_CACHE: dict[str, KieModelSpec] = {}


def reload_specs() -> None:
    """Drop cached specs so env changes take effect. Test helper."""
    _SPEC_CACHE.clear()


def all_registered_slugs() -> list[str]:
    """Return every model slug the registry knows about (enabled or not)."""
    return list(_SPEC_BUILDERS.keys())


def enabled_slugs() -> list[str]:
    """Return slugs that the current deployment allows.

    Controlled by ``KIE_MODELS_ENABLED`` (comma-separated). When unset,
    NO model is enabled by default — deployments must opt-in per model
    so a new integration never lights up without explicit configuration.
    """
    raw = os.environ.get("KIE_MODELS_ENABLED", "").strip()
    if not raw:
        return []
    return [slug.strip().lower() for slug in raw.split(",") if slug.strip()]


def default_slug() -> Optional[str]:
    """Return the deployment's chosen default model slug, if any.

    Controlled by ``KIE_DEFAULT_MODEL``. When unset, callers must
    request a specific slug — there is intentionally no fallback focal
    model in code.
    """
    slug = os.environ.get("KIE_DEFAULT_MODEL", "").strip().lower()
    return slug or None


def get_spec(slug: str) -> Optional[KieModelSpec]:
    """Return the spec for ``slug`` if the deployment has it enabled.

    Returns None when the slug is not registered OR not in
    KIE_MODELS_ENABLED. This is the single choke point that gates model
    availability — the KieProvider builds against whatever spec this
    returns.
    """
    slug = (slug or "").strip().lower()
    if slug not in _SPEC_BUILDERS:
        return None
    if slug not in enabled_slugs():
        return None
    if slug not in _SPEC_CACHE:
        _SPEC_CACHE[slug] = _SPEC_BUILDERS[slug]()
    return _SPEC_CACHE[slug]


def register_spec_builder(slug: str, builder: Callable[[], KieModelSpec]) -> None:
    """Test / plugin extension: register a new model spec builder.

    Not called from production code paths — kept public so integration
    tests can add fake models without editing this file.
    """
    _SPEC_BUILDERS[slug] = builder
    _SPEC_CACHE.pop(slug, None)


__all__ = [
    "KieModelSpec",
    "ResolutionPricing",
    "all_registered_slugs",
    "enabled_slugs",
    "default_slug",
    "get_spec",
    "register_spec_builder",
    "reload_specs",
]
