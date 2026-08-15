"""User uploads — B-roll media + recorded voiceovers.

Uses MongoDB GridFS as the storage backend. Files are stored chunked in
Mongo so we don't need a separate object-storage integration. Adequate
for our scale (~100 customers × ~50 MB/month). URLs returned by upload
endpoints are `/api/files/{file_id}` — these MUST be publicly readable
(no auth) because fal.ai's render workers fetch them at compose time.
File IDs are UUIDs so they're effectively unguessable.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from upload_paths import object_id_from_public_file_token


# Allowed MIME types — explicit allowlist beats blocklist for safety.
ALLOWED_BROLL_MIMES = {
    "video/mp4", "video/quicktime", "video/webm", "video/x-matroska",
    "image/png", "image/jpeg", "image/webp", "image/gif",
}
ALLOWED_VOICE_MIMES = {
    "audio/webm", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav",
    "audio/ogg", "audio/aac", "audio/x-m4a", "audio/m4a",
}

# Per-file size caps. 100 MB for B-roll (long screen recordings happen);
# 25 MB for voice (a 5-min mono 44.1kHz WAV is ~26MB so this is tight but
# reasonable — most voices will be 1-15 MB WebM).
MAX_BROLL_BYTES = 100 * 1024 * 1024
MAX_VOICE_BYTES = 25 * 1024 * 1024

# Streaming chunk size for GET responses.
STREAM_CHUNK = 256 * 1024


def register_uploads_routes(api: APIRouter, db, current_user_dep, require_studio):
    """Mount upload routes on the given /api router.

    Args:
        api: FastAPI router for /api/* endpoints
        db: motor AsyncIOMotorDatabase
        current_user_dep: FastAPI Depends() that returns the authenticated user
        require_studio: callable(user) -> raises 403 if user lacks studio ent
    """
    fs = AsyncIOMotorGridFSBucket(db, bucket_name="uploads")

    @api.post("/studio/uploads/broll")
    async def upload_broll(
        file: UploadFile = File(...),
        user=Depends(current_user_dep),
    ):
        require_studio(user)
        return await _store_file(
            file, user.email, kind="broll",
            allowed_mimes=ALLOWED_BROLL_MIMES, max_bytes=MAX_BROLL_BYTES, fs=fs,
        )

    @api.post("/studio/uploads/voiceover")
    async def upload_voiceover(
        file: UploadFile = File(...),
        user=Depends(current_user_dep),
    ):
        require_studio(user)
        return await _store_file(
            file, user.email, kind="voiceover",
            allowed_mimes=ALLOWED_VOICE_MIMES, max_bytes=MAX_VOICE_BYTES, fs=fs,
        )

    @api.get("/studio/uploads")
    async def list_uploads(user=Depends(current_user_dep)):
        """Return the current user's uploaded media library."""
        require_studio(user)
        # NOTE: fs.find() yields GridOut objects (attribute-access), but we
        # need .get()-style dict access. Query the raw uploads.files
        # collection so we always get plain dicts.
        files = db["uploads.files"]
        cursor = files.find({
            "metadata.owner": user.email,
            "metadata.deleted": {"$ne": True},
        }).sort("uploadDate", -1)
        out = []
        async for doc in cursor:
            md = doc.get("metadata") or {}
            out.append({
                "id": str(doc["_id"]),
                "url": _public_url(str(doc["_id"]), md.get("ext", "")),
                "filename": md.get("original_filename") or doc.get("filename"),
                "kind": md.get("kind") or "broll",
                "content_type": md.get("content_type"),
                "size": doc.get("length"),
                "uploaded_at": doc.get("uploadDate").isoformat() if doc.get("uploadDate") else None,
            })
        return {"uploads": out}

    @api.delete("/studio/uploads/{file_id}")
    async def delete_upload(file_id: str, user=Depends(current_user_dep)):
        """Soft-delete (metadata flag). GridFS chunks remain until a cron
        sweep removes them — keeps deletes fast + reversible."""
        require_studio(user)
        try:
            from bson import ObjectId
            oid = ObjectId(file_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Bad file id")
        # Verify ownership before flagging
        files = db["uploads.files"]
        doc = await files.find_one({"_id": oid, "metadata.owner": user.email})
        if not doc:
            raise HTTPException(status_code=404, detail="File not found")
        await files.update_one(
            {"_id": oid},
            {"$set": {"metadata.deleted": True, "metadata.deleted_at": datetime.now(timezone.utc).isoformat()}},
        )
        return {"ok": True}

    @api.get("/files/{file_id}")
    async def get_file(file_id: str):
        """Stream a file from GridFS. NO AUTH — fal.ai's render workers
        need to fetch these. File IDs are UUIDs so unguessable. Soft-
        deleted files return 404."""
        try:
            from bson import ObjectId
            # Upload responses intentionally append a codec suffix so media
            # consumers can infer the format. GridFS stores only the ObjectId.
            oid = ObjectId(object_id_from_public_file_token(file_id))
        except Exception:
            raise HTTPException(status_code=400, detail="Bad file id")
        files = db["uploads.files"]
        doc = await files.find_one({"_id": oid})
        if not doc or (doc.get("metadata") or {}).get("deleted"):
            raise HTTPException(status_code=404, detail="File not found")

        async def _stream():
            stream = await fs.open_download_stream(oid)
            try:
                while True:
                    chunk = await stream.readchunk()
                    if not chunk:
                        break
                    yield chunk
            finally:
                # Motor's GridOut.close() is sync in some versions and returns
                # None — guard against awaiting a non-awaitable.
                try:
                    maybe_coro = stream.close()
                    if maybe_coro is not None:
                        await maybe_coro
                except Exception:
                    pass

        content_type = (doc.get("metadata") or {}).get("content_type") or "application/octet-stream"
        return StreamingResponse(
            _stream(),
            media_type=content_type,
            headers={
                "Content-Length": str(doc.get("length", 0)),
                "Cache-Control": "public, max-age=86400",
                "Accept-Ranges": "bytes",
            },
        )


async def _store_file(
    file: UploadFile,
    owner: str,
    kind: str,
    allowed_mimes: set,
    max_bytes: int,
    fs: AsyncIOMotorGridFSBucket,
) -> dict:
    """Validate + persist a single upload. Returns the public URL + metadata."""
    content_type = (file.content_type or "").lower().split(";")[0].strip()
    if content_type not in allowed_mimes:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type {content_type!r}. Allowed: {sorted(allowed_mimes)}",
        )

    # Stream-read with size check — read in 256KB chunks so we don't slurp
    # a 100 MB file into RAM. GridFS handles chunking on the storage side.
    data = bytearray()
    while True:
        chunk = await file.read(STREAM_CHUNK)
        if not chunk:
            break
        if len(data) + len(chunk) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {max_bytes // (1024*1024)} MB)",
            )
        data.extend(chunk)

    # Derive a clean extension for the public URL — fal.ai's compose step
    # uses the URL's suffix to guess the codec. Without an extension, ffmpeg
    # has to probe (slower) or guesses wrong.
    original = (file.filename or "").lower()
    ext = ""
    if "." in original:
        ext = original.rsplit(".", 1)[1][:8]
    if not ext:
        ext = _ext_from_mime(content_type)

    file_id = uuid.uuid4().hex
    filename = f"{file_id}.{ext}" if ext else file_id
    metadata = {
        "owner": owner,
        "kind": kind,
        "content_type": content_type,
        "original_filename": file.filename or "upload",
        "ext": ext,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    object_id = await fs.upload_from_stream(filename, bytes(data), metadata=metadata)

    return {
        "id": str(object_id),
        "url": _public_url(str(object_id), ext),
        "filename": file.filename,
        "kind": kind,
        "content_type": content_type,
        "size": len(data),
    }


def _public_url(file_id: str, ext: str) -> str:
    """Build a CDN-friendly public URL for the uploaded file.

    Includes the file extension as a query-string hint so downstream
    ffmpeg + fal.ai recognize the codec from the URL. Backend URL is read
    from the request host so it works on both preview + production.
    """
    base = os.environ.get("PUBLIC_BACKEND_URL", "").rstrip("/")
    suffix = f".{ext}" if ext else ""
    if base:
        return f"{base}/api/files/{file_id}{suffix}"
    # Relative URL — fine for in-app previews, the frontend will prepend
    # REACT_APP_BACKEND_URL when sending to fal.ai via the render endpoint.
    return f"/api/files/{file_id}{suffix}"


def _ext_from_mime(mime: str) -> str:
    """Best-effort extension lookup for common upload MIMEs."""
    return {
        "video/mp4": "mp4",
        "video/quicktime": "mov",
        "video/webm": "webm",
        "video/x-matroska": "mkv",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
        "audio/webm": "webm",
        "audio/mp4": "m4a",
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/ogg": "ogg",
        "audio/aac": "aac",
        "audio/x-m4a": "m4a",
        "audio/m4a": "m4a",
    }.get(mime, "")
