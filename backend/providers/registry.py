"""Provider registry — selects concrete adapters by name / slug.

Two axes of selection:
  * ``provider name`` — "kie" or "fal" (or "auto" to pick either)
  * ``kie model slug`` — for KIE, which model in kie_models.py to build

The registry is deliberately conservative:
  * KIE is only "available" when KIE_API_KEY is set AND at least one
    model is enabled via KIE_MODELS_ENABLED.
  * fal is a fallback only — never picked by ``auto`` when a KIE model
    supports the request (unless KIE is unavailable).
"""

from __future__ import annotations

import os
from typing import Optional

from .base import VideoMotionProvider
from .fal_provider import FalProvider
from .kie_models import default_slug, enabled_slugs
from .kie_provider import KieProvider
from .types import SceneMotionRequest


_PROVIDER_ORDER = ("kie", "fal")
_INSTANCES: dict[str, VideoMotionProvider] = {}


def _build_kie_provider() -> Optional[KieProvider]:
    """Construct a KieProvider using the deployment's default slug.

    Returns None when:
      * KIE_API_KEY is missing
      * KIE_MODELS_ENABLED is empty
      * KIE_DEFAULT_MODEL is unset OR points at a disabled slug
    """
    slug = default_slug()
    slugs = enabled_slugs()
    if not slugs:
        return None
    if slug is None:
        # No explicit default — pick the first enabled slug so admin can
        # still exercise the pipeline without a KIE_DEFAULT_MODEL env
        # var. But we do NOT let the code silently prefer a specific
        # model — the enabled list is the source of truth.
        slug = slugs[0]
    provider = KieProvider.for_slug(slug)
    if provider is None or not provider.is_available():
        return None
    return provider


def _build(name: str) -> Optional[VideoMotionProvider]:
    if name == "kie":
        return _build_kie_provider()
    if name == "fal":
        return FalProvider()
    return None


def _get_or_build(name: str) -> Optional[VideoMotionProvider]:
    if name in _INSTANCES:
        return _INSTANCES[name]
    instance = _build(name)
    if instance is not None:
        _INSTANCES[name] = instance
    return instance


def reset_registry() -> None:
    """Drop cached instances. Test helper — mutating env vars post-import
    won't be seen unless the registry is reset first."""
    _INSTANCES.clear()


def default_provider_name() -> str:
    return os.environ.get("RENDER_PROVIDER", "auto").strip().lower() or "auto"


def available_providers() -> list[str]:
    names: list[str] = []
    for name in _PROVIDER_ORDER:
        instance = _get_or_build(name)
        if instance is not None and instance.is_available():
            names.append(name)
    return names


def get_provider(
    name: str,
    request: Optional[SceneMotionRequest] = None,
) -> Optional[VideoMotionProvider]:
    name = (name or "").strip().lower() or "auto"

    if name == "auto":
        for candidate_name in _PROVIDER_ORDER:
            candidate = _get_or_build(candidate_name)
            if candidate is None or not candidate.is_available():
                continue
            if request is None or candidate.supports(request):
                return candidate
        return None

    instance = _get_or_build(name)
    if instance is None or not instance.is_available():
        return None
    if request is not None and not instance.supports(request):
        return None
    return instance


__all__ = [
    "available_providers",
    "default_provider_name",
    "get_provider",
    "reset_registry",
]
