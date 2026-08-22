"""Scene Builder v1 project and revision foundation.

This module intentionally has no render-provider dependencies.  It stores an
editable scene plan before rendering and gives every scene a stable ID plus an
exact narration word range.  Audio timestamps remain explicitly pending until
a later alignment worker measures the selected voiceover.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError


SCHEMA_VERSION = 1
MAX_SCENES = 200
DEFAULT_WORDS_PER_SCENE = 45


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def normalize_script(script: str) -> str:
    """Collapse whitespace while preserving the authored words and punctuation."""
    normalized = re.sub(r"\s+", " ", script or "").strip()
    if not normalized:
        raise ValueError("Script is required")
    return normalized


class NarrationSpan(BaseModel):
    text: str
    word_start: int = Field(ge=0)
    word_end: int = Field(gt=0)
    start_ms: Optional[int] = Field(default=None, ge=0)
    end_ms: Optional[int] = Field(default=None, ge=0)
    timing_source: Literal["pending", "aligned", "manual"] = "pending"


class SceneVisual(BaseModel):
    source: Literal["unassigned", "stock", "upload", "ai"] = "unassigned"
    detailed_prompt: str = ""
    stock_query: str = ""
    asset_id: Optional[str] = None
    asset_url: Optional[str] = None
    asset_kind: Optional[Literal["image", "video"]] = None
    alternatives: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class SceneEdit(BaseModel):
    clip_start_ms: Optional[int] = Field(default=None, ge=0)
    clip_end_ms: Optional[int] = Field(default=None, ge=0)
    fit: Literal["cover", "contain"] = "cover"
    motion: Literal["standard", "none", "premium"] = "standard"
    transition: Literal["cut", "crossfade"] = "cut"
    freeze_end: bool = False


class SceneDraft(BaseModel):
    id: str = Field(min_length=5, max_length=80)
    order: int = Field(ge=0)
    narration: NarrationSpan
    visual: SceneVisual = Field(default_factory=SceneVisual)
    edit: SceneEdit = Field(default_factory=SceneEdit)


class VoiceoverState(BaseModel):
    kind: Literal["unassigned", "generated", "upload"] = "unassigned"
    url: Optional[str] = None
    duration_ms: Optional[int] = Field(default=None, ge=0)
    alignment_status: Literal["pending", "aligned", "failed"] = "pending"


class ProjectCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=160)
    script: str = Field(min_length=1, max_length=200_000)
    aspect: Literal["9:16", "16:9", "1:1"] = "9:16"
    target_scene_count: Optional[int] = Field(default=None, ge=1, le=MAX_SCENES)


class RevisionSave(BaseModel):
    expected_revision: int = Field(ge=1)
    script: str = Field(min_length=1, max_length=200_000)
    scenes: list[SceneDraft] = Field(min_length=1, max_length=MAX_SCENES)
    voiceover: VoiceoverState = Field(default_factory=VoiceoverState)
    change_summary: str = Field(default="Autosave", max_length=300)


def _ends_sentence(word: str) -> bool:
    return bool(re.search(r"[.!?][\"'\)\]]*$", word))


def build_initial_scenes(script: str, target_scene_count: Optional[int] = None) -> list[dict[str, Any]]:
    """Create deterministic narration boundaries and fresh stable scene IDs.

    Boundaries prefer sentence endings near equal-sized targets.  Every word is
    assigned exactly once.  Millisecond timing is deliberately left unset.
    """
    normalized = normalize_script(script)
    words = normalized.split(" ")
    word_count = len(words)
    target = target_scene_count or max(1, round(word_count / DEFAULT_WORDS_PER_SCENE))
    target = min(MAX_SCENES, word_count, max(1, target))
    sentence_boundaries = {i + 1 for i, word in enumerate(words[:-1]) if _ends_sentence(word)}

    boundaries = [0]
    for scene_index in range(1, target):
        remaining = target - scene_index
        minimum = boundaries[-1] + 1
        maximum = word_count - remaining
        ideal = round(word_count * scene_index / target)
        candidates = [point for point in sentence_boundaries if minimum <= point <= maximum]
        # Prefer punctuation when it is reasonably near the balanced boundary.
        nearby = [point for point in candidates if abs(point - ideal) <= max(8, word_count // (target * 2))]
        boundary = min(nearby, key=lambda point: (abs(point - ideal), point)) if nearby else ideal
        boundaries.append(max(minimum, min(maximum, boundary)))
    boundaries.append(word_count)

    scenes: list[dict[str, Any]] = []
    for order, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        scenes.append(
            SceneDraft(
                id=_id("scn"),
                order=order,
                narration=NarrationSpan(
                    text=" ".join(words[start:end]),
                    word_start=start,
                    word_end=end,
                ),
            ).model_dump(mode="json")
        )
    return scenes


def validate_revision(script: str, scenes: list[SceneDraft]) -> str:
    """Validate exact, gap-free narration coverage and optional audio timing."""
    try:
        normalized = normalize_script(script)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    words = normalized.split(" ")
    ids: set[str] = set()
    expected_word = 0
    previous_end_ms: Optional[int] = None

    for index, scene in enumerate(scenes):
        if scene.id in ids:
            raise HTTPException(status_code=422, detail=f"Duplicate scene id: {scene.id}")
        ids.add(scene.id)
        span = scene.narration
        if span.word_start != expected_word or span.word_end <= span.word_start:
            raise HTTPException(status_code=422, detail=f"Scene {index + 1} narration ranges must be contiguous")
        if span.word_end > len(words):
            raise HTTPException(status_code=422, detail=f"Scene {index + 1} narration exceeds the script")
        if span.text != " ".join(words[span.word_start:span.word_end]):
            raise HTTPException(status_code=422, detail=f"Scene {index + 1} narration text does not match its word range")
        if (span.start_ms is None) != (span.end_ms is None):
            raise HTTPException(status_code=422, detail=f"Scene {index + 1} must set both audio timestamps or neither")
        if span.start_ms is None:
            if span.timing_source != "pending":
                raise HTTPException(status_code=422, detail=f"Scene {index + 1} has no timestamps and must remain pending")
        else:
            if span.end_ms <= span.start_ms:
                raise HTTPException(status_code=422, detail=f"Scene {index + 1} audio timing is invalid")
            if previous_end_ms is not None and span.start_ms < previous_end_ms:
                raise HTTPException(status_code=422, detail=f"Scene {index + 1} audio timing overlaps")
            previous_end_ms = span.end_ms
        expected_word = span.word_end

    if expected_word != len(words):
        raise HTTPException(status_code=422, detail="Scene narration does not cover the complete script")
    return normalized


def _clean(doc: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if doc is None:
        return None
    result = dict(doc)
    result.pop("_id", None)
    return result


async def ensure_scene_builder_indexes(db) -> None:
    await db.studio_projects.create_index([("user_email", 1), ("updated_at", -1)])
    await db.studio_projects.create_index("id", unique=True)
    await db.studio_project_revisions.create_index([("project_id", 1), ("version", -1)], unique=True)
    await db.studio_project_revisions.create_index("id", unique=True)


def register_scene_builder_routes(api, db, current_user_dep, require_studio: Callable[[Any], None]) -> None:
    """Register authenticated Scene Builder routes on the existing API app."""

    def entitled(user: Any) -> None:
        require_studio(user)

    async def owned_project(project_id: str, user: Any) -> dict[str, Any]:
        project = await db.studio_projects.find_one({"id": project_id, "user_email": user.email, "archived": {"$ne": True}})
        if not project:
            raise HTTPException(status_code=404, detail="Scene Builder project not found")
        return project

    @api.post("/studio/projects", status_code=201)
    async def create_project(payload: ProjectCreate, user=Depends(current_user_dep)):
        entitled(user)
        try:
            script = normalize_script(payload.script)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        created_at = _now()
        project_id = _id("prj")
        revision_id = _id("rev")
        scenes = build_initial_scenes(script, payload.target_scene_count)
        title = (payload.title or " ".join(script.split(" ")[:8])).strip() or "Untitled video"
        project = {
            "id": project_id,
            "user_email": user.email,
            "title": title,
            "mode": "faceless",
            "aspect": payload.aspect,
            "status": "draft",
            "schema_version": SCHEMA_VERSION,
            "current_revision_id": revision_id,
            "current_revision_number": 1,
            "archived": False,
            "created_at": created_at,
            "updated_at": created_at,
        }
        revision = {
            "id": revision_id,
            "project_id": project_id,
            "user_email": user.email,
            "version": 1,
            "source_revision_id": None,
            "script": script,
            "voiceover": VoiceoverState().model_dump(mode="json"),
            "scenes": scenes,
            "change_summary": "Initial scene plan",
            "created_at": created_at,
        }
        await db.studio_project_revisions.insert_one(dict(revision))
        try:
            await db.studio_projects.insert_one(dict(project))
        except Exception:
            await db.studio_project_revisions.delete_one({"id": revision_id})
            raise
        return {"project": _clean(project), "revision": _clean(revision)}

    @api.get("/studio/projects")
    async def list_projects(limit: int = Query(default=30, ge=1, le=100), user=Depends(current_user_dep)):
        entitled(user)
        cursor = db.studio_projects.find({"user_email": user.email, "archived": {"$ne": True}}).sort("updated_at", -1).limit(limit)
        items = [_clean(doc) async for doc in cursor]
        return {"items": items}

    @api.get("/studio/projects/{project_id}")
    async def get_project(project_id: str, user=Depends(current_user_dep)):
        entitled(user)
        project = await owned_project(project_id, user)
        revision = await db.studio_project_revisions.find_one({
            "id": project["current_revision_id"], "project_id": project_id, "user_email": user.email,
        })
        if not revision:
            raise HTTPException(status_code=409, detail="Current project revision is missing")
        return {"project": _clean(project), "revision": _clean(revision)}

    @api.get("/studio/projects/{project_id}/revisions")
    async def list_revisions(project_id: str, user=Depends(current_user_dep)):
        entitled(user)
        await owned_project(project_id, user)
        cursor = db.studio_project_revisions.find({"project_id": project_id, "user_email": user.email}).sort("version", -1)
        items = []
        async for doc in cursor:
            clean = _clean(doc)
            clean.pop("scenes", None)
            items.append(clean)
        return {"items": items}

    @api.get("/studio/projects/{project_id}/revisions/{version}")
    async def get_revision(project_id: str, version: int, user=Depends(current_user_dep)):
        entitled(user)
        await owned_project(project_id, user)
        revision = await db.studio_project_revisions.find_one({
            "project_id": project_id, "user_email": user.email, "version": version,
        })
        if not revision:
            raise HTTPException(status_code=404, detail="Scene Builder revision not found")
        return {"revision": _clean(revision)}

    @api.put("/studio/projects/{project_id}/revisions", status_code=201)
    async def save_revision(project_id: str, payload: RevisionSave, user=Depends(current_user_dep)):
        entitled(user)
        project = await owned_project(project_id, user)
        if project["current_revision_number"] != payload.expected_revision:
            raise HTTPException(status_code=409, detail={
                "message": "This project changed in another session. Reload before saving.",
                "current_revision": project["current_revision_number"],
            })
        script = validate_revision(payload.script, payload.scenes)
        version = payload.expected_revision + 1
        revision_id = _id("rev")
        created_at = _now()
        scenes = []
        for order, scene in enumerate(payload.scenes):
            saved_scene = scene.model_copy(update={"order": order})
            scenes.append(saved_scene.model_dump(mode="json"))
        revision = {
            "id": revision_id,
            "project_id": project_id,
            "user_email": user.email,
            "version": version,
            "source_revision_id": project["current_revision_id"],
            "script": script,
            "voiceover": payload.voiceover.model_dump(mode="json"),
            "scenes": scenes,
            "change_summary": payload.change_summary.strip() or "Autosave",
            "created_at": created_at,
        }
        try:
            await db.studio_project_revisions.insert_one(dict(revision))
        except DuplicateKeyError as exc:
            current = await db.studio_projects.find_one({"id": project_id, "user_email": user.email})
            raise HTTPException(status_code=409, detail={
                "message": "This project changed in another session. Reload before saving.",
                "current_revision": (current or {}).get("current_revision_number"),
            }) from exc
        result = await db.studio_projects.update_one(
            {"id": project_id, "user_email": user.email, "current_revision_number": payload.expected_revision},
            {"$set": {
                "current_revision_id": revision_id,
                "current_revision_number": version,
                "updated_at": created_at,
            }},
        )
        if result.modified_count != 1:
            await db.studio_project_revisions.delete_one({"id": revision_id})
            current = await db.studio_projects.find_one({"id": project_id, "user_email": user.email})
            raise HTTPException(status_code=409, detail={
                "message": "This project changed in another session. Reload before saving.",
                "current_revision": (current or {}).get("current_revision_number"),
            })
        updated_project = await db.studio_projects.find_one({"id": project_id, "user_email": user.email})
        return {"project": _clean(updated_project), "revision": _clean(revision)}
