from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.kie_image import KIE_CREATE_URL, KIE_RECORD_URL, KieImageProvider


@pytest.mark.asyncio
async def test_disabled_provider_makes_no_request():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = KieImageProvider(api_key="key", enabled=False, http_client=client)
        result = await provider.generate(prompt="coffee cup", aspect="9_16")
    assert result.ok is False
    assert result.error_code == "kie_image_unavailable"
    assert calls == []


@pytest.mark.asyncio
async def test_submit_payload_and_poll_success():
    requests = []

    async def handler(request):
        requests.append(request)
        if str(request.url).startswith(KIE_CREATE_URL):
            return httpx.Response(200, json={"code": 200, "data": {"taskId": "img-task-1"}})
        assert str(request.url).startswith(KIE_RECORD_URL)
        return httpx.Response(200, json={
            "code": 200,
            "data": {
                "state": "success",
                "resultJson": json.dumps({"resultUrls": ["https://cdn.kie.test/image.png"]}),
            },
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = KieImageProvider(
            api_key="secret-test-key",
            enabled=True,
            http_client=client,
            poll_interval_s=0,
            max_wait_s=1,
        )
        result = await provider.generate(prompt="A founder planning at a desk", aspect="9_16")

    assert result.ok is True
    assert result.output_url == "https://cdn.kie.test/image.png"
    assert result.task_id == "img-task-1"
    payload = json.loads(requests[0].content)
    assert payload == {
        "model": "nano-banana-2",
        "input": {
            "prompt": "A founder planning at a desk",
            "image_input": [],
            "aspect_ratio": "9:16",
            "resolution": "1K",
            "output_format": "png",
        },
    }
    assert requests[0].headers["authorization"] == "Bearer secret-test-key"
    assert requests[1].url.params["taskId"] == "img-task-1"


@pytest.mark.asyncio
async def test_landscape_mapping_and_safe_failure():
    submitted = {}

    async def handler(request):
        if str(request.url).startswith(KIE_CREATE_URL):
            submitted.update(json.loads(request.content))
            return httpx.Response(200, json={"code": 200, "data": {"taskId": "bad-task"}})
        return httpx.Response(200, json={"code": 200, "data": {
            "state": "fail", "failCode": "moderated", "failMsg": "Rejected prompt"
        }})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await KieImageProvider(
            api_key="key", enabled=True, http_client=client, poll_interval_s=0, max_wait_s=1
        ).generate(prompt="landscape", aspect="16_9")
    assert submitted["input"]["aspect_ratio"] == "16:9"
    assert result.ok is False
    assert result.error_code == "moderated"
    assert result.task_id == "bad-task"


@pytest.mark.asyncio
async def test_http_error_does_not_echo_api_key():
    async def handler(request):
        return httpx.Response(500, text="upstream failed and should remain private")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await KieImageProvider(
            api_key="never-echo-this", enabled=True, http_client=client
        ).generate(prompt="scene", aspect="9_16")
    assert result.error_code == "http_500"
    assert "never-echo-this" not in (result.error or "")
