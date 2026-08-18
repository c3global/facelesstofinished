from datetime import datetime, timezone

import httpx
import pytest

from render_dispatch import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    canonical_dispatch_body,
    dispatch_render_job,
    dispatch_signature,
    recovery_query,
    verify_dispatch_signature,
)


def test_signature_round_trip_and_tamper_rejection():
    body = canonical_dispatch_body("job-123")
    timestamp = "1000"
    signature = dispatch_signature("secret", timestamp, body)
    assert verify_dispatch_signature(
        "secret", timestamp, body, signature, now=1001,
    )
    assert not verify_dispatch_signature(
        "secret", timestamp, body + b"x", signature, now=1001,
    )


def test_signature_rejects_expired_request():
    body = canonical_dispatch_body("job-123")
    signature = dispatch_signature("secret", "1000", body)
    assert not verify_dispatch_signature(
        "secret", "1000", body, signature, now=1301,
    )


def test_recovery_query_requires_a_real_unclaimed_queued_faceless_job():
    query = recovery_query(
        now=datetime(2026, 8, 18, 1, 0, tzinfo=timezone.utc),
        redispatch_after_s=300,
    )
    assert query["status"] == "queued"
    assert query["mode"] == "faceless"
    assert {"worker_execution_id": {"$exists": False}} in query["$and"][0]["$or"]
    assert {
        "dispatch_last_accepted_at": {"$lte": "2026-08-18T00:55:00+00:00"}
    } in query["$and"][1]["$or"]


@pytest.mark.asyncio
async def test_dispatch_client_sends_signed_canonical_body():
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        seen["body"] = body
        seen["timestamp"] = request.headers[TIMESTAMP_HEADER]
        seen["signature"] = request.headers[SIGNATURE_HEADER]
        return httpx.Response(202, json={"accepted": True, "operation": "op-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await dispatch_render_job(
            "job-123",
            url="https://dispatcher.test/dispatch",
            secret="secret",
            client=client,
        )

    assert seen["body"] == b'{"job_id":"job-123"}'
    assert verify_dispatch_signature(
        "secret",
        seen["timestamp"],
        seen["body"],
        seen["signature"],
    )
    assert result == {"accepted": True, "operation": "op-1"}
