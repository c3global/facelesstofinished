"""Provider registry — selects concrete adapters by name.

Usage:
    from providers.registry import get_provider, available_providers
    provider = get_provider("kie")            # explicit
    provider = get_provider("auto", request)  # capability-based selection

Providers are constructed lazily on first access so tests can mutate
environment variables (KIE_API_KEY etc.) before the registry snapshots
credentials.
"""

from __future__ import annotations

import os
from typing import Optional

from .base import VideoMotionProvider
from .fal_provider import FalProvider
from .kie_provider import KieProvider
from .types import SceneMotionRequest


# ---- Registry state --------------------------------------------------------

_PROVIDER_ORDER = ("kie", "fal")  # preference order for "auto"
_INSTANCES: dict[str, VideoMotionProvider] = {}


def _build(name: str) -> Optional[VideoMotionProvider]:
    if name == "kie":
        return KieProvider()
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


# ---- Public API ------------------------------------------------------------


def default_provider_name() -> str:
    """Return the caller's preferred provider name from env, else 'auto'.

    Set ``RENDER_PROVIDER=kie|fal|auto`` in the environment to override
    per-deployment. Default is ``auto`` (capability-based selection).
    """
    return os.environ.get("RENDER_PROVIDER", "auto").strip().lower() or "auto"


def available_providers() -> list[str]:
    """Return the names of providers that are currently available.

    Availability = credential present + instance can be constructed.
    Used by the frontend to hide provider choices that aren't
    configured in this environment.
    """
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
    """Return the provider matching ``name`` (or the best fit for auto).

    Returns None when no provider satisfies the constraints.

    Args:
        name: 'kie', 'fal', or 'auto'. Case-insensitive.
        request: When ``name == 'auto'`` the registry picks the first
            available provider that ``supports(request)``.
    """
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
