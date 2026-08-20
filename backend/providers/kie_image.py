"""KIE.ai still-image generation for Faceless scene visuals.

This adapter is intentionally separate from the video-motion registry. It is
enabled with ``KIE_IMAGE_GENERATION_ENABLED=1`` and makes KIE the first choice
for AI-generated stills while preserving the legacy image providers as a
fallback in ``server.py``.

Uploaded customer media never enters this adapter; uploaded images and videos
are classified and normalized locally by the render pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx

KIE_CREATE_URL = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_RECORD_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"

logger = logging.getLogger(__name__)


def _enabled(value: Optional[str] = None) -> bool:
    raw = value if value is not None else os.environ.get("KIE_IMAGE_GENERATION_ENABLED", "0")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class KieImageResult:
    ok: bool
    output_url: Optional[str] = None
    task_id: Optional[str] = None
    model: str = "nano-banana-2"
    error_code: Optional[str] = None
    error: Optional[str] = None


class KieImageProvider:
    """Small async adapter around KIE's unified image-task API."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        enabled: Optional[bool] = None,
        model: Optional[str] = None,
        resolution: Optional[str] = None,
        poll_interval_s: Optional[float] = None,
        max_wait_s: Optional[float] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("KIE_API_KEY", "")
        self.enabled = _enabled() if enabled is None else enabled
        self.model = (model or os.environ.get("KIE_IMAGE_MODEL", "nano-banana-2")).strip()
        self.resolution = (resolution or os.environ.get("KIE_IMAGE_RESOLUTION", "1K")).strip().upper()
        self.poll_interval_s = (
            float(os.environ.get("KIE_IMAGE_POLL_INTERVAL_S", "3"))
            if poll_interval_s is None else poll_interval_s
        )
        self.max_wait_s = (
            float(os.environ.get("KIE_IMAGE_MAX_WAIT_S", "300"))
            if max_wait_s is None else max_wait_s
        )
        self._client = http_client

    def is_available(self) -> bool:
        return bool(self.enabled and self.api_key and self.model)

    async def generate(self, *, prompt: str, aspect: str) -> KieImageResult:
        if not self.is_available():
            return self._fail("kie_image_unavailable", "KIE image generation is not configured")
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            return self._fail("invalid_prompt", "Image prompt is empty")

        payload = {
            "model": self.model,
            "input": {
                "prompt": clean_prompt,
                "image_input": [],
                "aspect_ratio": "9:16" if aspect == "9_16" else "16:9",
                "resolution": self.resolution,
                "output_format": "png",
            },
        }

        own_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15, read=30, write=30, pool=15)
        )
        try:
            try:
                response = await client.post(
                    KIE_CREATE_URL,
                    headers=self._headers(),
                    json=payload,
                    timeout=30,
                )
            except httpx.HTTPError as exc:
                logger.warning("[kie-image] submit transport error: %s", type(exc).__name__)
                return self._fail("transport_error", type(exc).__name__)

            if response.status_code == 402:
                return self._fail("insufficient_credits", "KIE account has insufficient credits")
            if response.status_code == 429:
                return self._fail("rate_limited", "KIE image generation is temporarily rate limited")
            if response.status_code >= 400:
                return self._fail(f"http_{response.status_code}", "KIE image task submission failed")

            body = _safe_json(response)
            task_id = str(((body.get("data") or {}).get("taskId") or "")).strip()
            if body.get("code") != 200 or not task_id:
                return self._fail("create_failed", "KIE image task returned no task id")

            terminal = await self._poll(client, task_id)
            data = terminal.get("data") or {}
            if str(data.get("state") or "").lower() != "success":
                return self._fail(
                    str(data.get("failCode") or "task_failed"),
                    str(data.get("failMsg") or "KIE image task failed")[:300],
                    task_id=task_id,
                )
            urls = _result_urls(data)
            if not urls:
                return self._fail("empty_result", "KIE image task returned no image URL", task_id=task_id)
            return KieImageResult(ok=True, output_url=urls[0], task_id=task_id, model=self.model)
        finally:
            if own_client:
                await client.aclose()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def _poll(self, client: httpx.AsyncClient, task_id: str) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.max_wait_s
        while True:
            try:
                response = await client.get(
                    KIE_RECORD_URL,
                    params={"taskId": task_id},
                    headers=self._headers(),
                    timeout=20,
                )
                body = _safe_json(response)
            except httpx.HTTPError as exc:
                logger.warning("[kie-image] poll transport error: %s", type(exc).__name__)
                body = {}
            state = str(((body.get("data") or {}).get("state") or "")).lower()
            if state in {"success", "fail"}:
                return body
            if loop.time() >= deadline:
                return {"data": {"state": "fail", "failCode": "poll_timeout", "failMsg": "poll timeout"}}
            await asyncio.sleep(self.poll_interval_s)

    def _fail(self, code: str, message: str, *, task_id: Optional[str] = None) -> KieImageResult:
        return KieImageResult(
            ok=False,
            task_id=task_id,
            model=self.model,
            error_code=code,
            error=message,
        )


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _result_urls(data: dict[str, Any]) -> list[str]:
    result = data.get("resultJson")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            return []
    if not isinstance(result, dict):
        return []
    values = result.get("resultUrls") or result.get("result_urls") or []
    return [value for value in values if isinstance(value, str) and value.startswith(("https://", "http://"))]


__all__ = ["KIE_CREATE_URL", "KIE_RECORD_URL", "KieImageProvider", "KieImageResult"]
