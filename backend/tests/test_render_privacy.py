from render_privacy import scrub_render_for_customer


def test_scrub_removes_internal_fields_recursively():
    raw = {
        "id": "render-1",
        "status": "complete",
        "estimated_cost_cents": 42,
        "provider": "hidden-provider",
        "scenes": [{
            "kind": "uploaded_image",
            "model": "hidden-model",
            "_provider_telemetry": {"task_id": "secret"},
        }],
    }

    assert scrub_render_for_customer(raw) == {
        "id": "render-1",
        "status": "complete",
        "scenes": [{"kind": "uploaded_image"}],
    }


def test_scrub_does_not_mutate_admin_source_document():
    raw = {"id": "render-1", "actual_cost_cents": 99}
    scrubbed = scrub_render_for_customer(raw)

    assert scrubbed == {"id": "render-1"}
    assert raw["actual_cost_cents"] == 99
