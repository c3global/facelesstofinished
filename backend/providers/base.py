"""Abstract base for AI video motion providers.

Concrete adapters live in fal_provider.py and kie_provider.py and are
registered via registry.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import ProviderResult, SceneMotionRequest


class VideoMotionProvider(ABC):
    """Contract every motion provider satisfies.

    Providers are stateless — they read configuration from environment
    variables at construction time. Adapters must never persist API
    keys, log them, or echo them back in error strings.
    """

    #: Short slug used as the ``provider`` field on stored scenes.
    name: str = "base"

    #: The concrete upstream model id (e.g. ``bytedance/seedance-2-5``).
    model_id: str = "unknown"

    @abstractmethod
    def is_available(self) -> bool:
        """Return True when this provider has valid credentials + config.

        The registry filters out unavailable providers, so callers never
        have to null-check before submitting a request.
        """

    @abstractmethod
    def supports(self, request: SceneMotionRequest) -> bool:
        """Return True if this provider can service the given request.

        Used by the registry when a caller requests ``provider="auto"``
        and we need to short-list providers that support (for example)
        first-and-last-frame generation.
        """

    @abstractmethod
    def estimate_cost_cents(self, request: SceneMotionRequest) -> int:
        """Return the estimated cost in USD cents for this request.

        Used by the pre-submission preview + the server-side hard
        ceiling. Real cost is captured post-completion when the provider
        reports it (KIE returns ``creditsConsumed``).
        """

    @abstractmethod
    async def generate(self, request: SceneMotionRequest) -> ProviderResult:
        """Submit + await + normalize into a ProviderResult.

        Blocks until the upstream reaches a terminal state (or the
        adapter's internal timeout fires). The result is always a
        ProviderResult — adapters raise only for programmer error
        (invalid request combinations), not upstream failures.
        """


__all__ = ["VideoMotionProvider"]
