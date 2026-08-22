from __future__ import annotations

import copy
import inspect
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scene_builder import (
    SceneDraft,
    build_initial_scenes,
    normalize_script,
    register_scene_builder_routes,
    validate_revision,
)


class _WriteResult:
    def __init__(self, modified_count=0, deleted_count=0):
        self.modified_count = modified_count
        self.deleted_count = deleted_count


def _matches(document, query):
    for key, expected in query.items():
        actual = document.get(key)
        if isinstance(expected, dict) and "$ne" in expected:
            if actual == expected["$ne"]:
                return False
        elif actual != expected:
            return False
    return True


class _Cursor:
    def __init__(self, documents):
        self.documents = [copy.deepcopy(doc) for doc in documents]

    def sort(self, key, direction):
        self.documents.sort(key=lambda doc: doc.get(key), reverse=direction < 0)
        return self

    def limit(self, limit):
        self.documents = self.documents[:limit]
        return self

    def __aiter__(self):
        self._iterator = iter(self.documents)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _Collection:
    def __init__(self):
        self.documents = []

    async def insert_one(self, document):
        self.documents.append(copy.deepcopy(document))
        return SimpleNamespace(inserted_id=document.get("id"))

    async def find_one(self, query):
        return next((copy.deepcopy(doc) for doc in self.documents if _matches(doc, query)), None)

    def find(self, query):
        return _Cursor(doc for doc in self.documents if _matches(doc, query))

    async def update_one(self, query, update):
        for document in self.documents:
            if _matches(document, query):
                document.update(copy.deepcopy(update.get("$set", {})))
                return _WriteResult(modified_count=1)
        return _WriteResult()

    async def delete_one(self, query):
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                self.documents.pop(index)
                return _WriteResult(deleted_count=1)
        return _WriteResult()

    async def create_index(self, *args, **kwargs):
        return "test-index"


class _Database:
    def __init__(self):
        self.studio_projects = _Collection()
        self.studio_project_revisions = _Collection()


def _client(email="owner@example.com"):
    database = _Database()
    app = FastAPI()

    async def current_user():
        return SimpleNamespace(email=email, entitlements=["studio"], is_admin=False)

    def require_studio(user):
        assert "studio" in user.entitlements

    register_scene_builder_routes(app, database, current_user, require_studio)
    return TestClient(app), database


def test_initial_scenes_cover_exact_transcript_without_fake_timestamps():
    script = "  First   sentence has several words.\nSecond sentence follows cleanly! Third one closes it.  "
    normalized = normalize_script(script)
    scenes = [SceneDraft.model_validate(scene) for scene in build_initial_scenes(script, 3)]

    assert " ".join(scene.narration.text for scene in scenes) == normalized
    assert [scene.order for scene in scenes] == [0, 1, 2]
    assert len({scene.id for scene in scenes}) == 3
    assert scenes[0].narration.word_start == 0
    assert scenes[-1].narration.word_end == len(normalized.split())
    assert all(scene.narration.start_ms is None for scene in scenes)
    assert all(scene.narration.end_ms is None for scene in scenes)
    assert all(scene.narration.timing_source == "pending" for scene in scenes)


@pytest.mark.parametrize("mutation,detail", [
    (lambda scenes: setattr(scenes[1].narration, "word_start", scenes[1].narration.word_start + 1), "contiguous"),
    (lambda scenes: setattr(scenes[0].narration, "text", "not the transcript"), "does not match"),
    (lambda scenes: setattr(scenes[1], "id", scenes[0].id), "Duplicate"),
])
def test_revision_validation_rejects_drift_gaps_and_duplicate_ids(mutation, detail):
    script = "One two three four five six seven eight nine ten."
    scenes = [SceneDraft.model_validate(scene) for scene in build_initial_scenes(script, 2)]
    mutation(scenes)
    with pytest.raises(Exception) as exc:
        validate_revision(script, scenes)
    assert detail in str(exc.value)


def test_create_edit_and_conflict_safe_revision_flow():
    client, database = _client()
    created = client.post("/studio/projects", json={
        "title": "Morning routine",
        "script": "Wake up slowly. Drink a glass of water. Plan the day before opening email.",
        "target_scene_count": 3,
    })
    assert created.status_code == 201, created.text
    body = created.json()
    project_id = body["project"]["id"]
    assert body["project"]["current_revision_number"] == 1
    assert body["revision"]["voiceover"]["alignment_status"] == "pending"

    scenes = body["revision"]["scenes"]
    stable_ids = [scene["id"] for scene in scenes]
    scenes[0]["visual"].update({
        "source": "stock",
        "detailed_prompt": "Close-up of a calm morning bedroom as sunlight enters",
        "stock_query": "morning sunlight bedroom",
    })
    saved = client.put(f"/studio/projects/{project_id}/revisions", json={
        "expected_revision": 1,
        "script": body["revision"]["script"],
        "scenes": scenes,
        "change_summary": "Choose opening B-roll",
    })
    assert saved.status_code == 201, saved.text
    saved_body = saved.json()
    assert saved_body["project"]["current_revision_number"] == 2
    assert [scene["id"] for scene in saved_body["revision"]["scenes"]] == stable_ids
    assert saved_body["revision"]["scenes"][0]["visual"]["stock_query"] == "morning sunlight bedroom"

    stale = client.put(f"/studio/projects/{project_id}/revisions", json={
        "expected_revision": 1,
        "script": body["revision"]["script"],
        "scenes": scenes,
    })
    assert stale.status_code == 409
    assert len(database.studio_project_revisions.documents) == 2


def test_script_engine_handoff_preserves_broll_prompts_without_provider_calls():
    client, _database = _client()
    prompts = [
        "Split screen, influencer setup versus simple screen recording software open.",
        "Cursor clicking start recording inside screen capture software.",
    ]
    response = client.post("/studio/projects", json={
        "title": "Tutorial authority video",
        "script": "You do not need a complicated setup. Start by recording the useful process on your screen.",
        "aspect": "16:9",
        "broll_prompts": prompts,
    })
    assert response.status_code == 201, response.text
    body = response.json()
    scenes = body["revision"]["scenes"]
    assert len(scenes) == 2
    assert [scene["visual"]["detailed_prompt"] for scene in scenes] == prompts
    assert scenes[0]["visual"]["stock_query"] == "split influencer setup simple recording software open"
    assert scenes[1]["visual"]["stock_query"] == "cursor clicking start recording inside capture software"
    assert all(scene["visual"]["source"] == "unassigned" for scene in scenes)


def test_projects_are_owner_scoped():
    client, database = _client("owner@example.com")
    created = client.post("/studio/projects", json={"script": "A private customer script."}).json()
    project_id = created["project"]["id"]

    other_app = FastAPI()

    async def other_user():
        return SimpleNamespace(email="other@example.com", entitlements=["studio"], is_admin=False)

    register_scene_builder_routes(other_app, database, other_user, lambda user: None)
    response = TestClient(other_app).get(f"/studio/projects/{project_id}")
    assert response.status_code == 404


def test_foundation_has_no_paid_or_external_provider_code():
    import scene_builder

    source = inspect.getsource(scene_builder).lower()
    forbidden = ["httpx", "fal_client", "heygen", "api.kie.ai", "pexels.com", "pixabay.com", "subprocess"]
    assert all(token not in source for token in forbidden)
