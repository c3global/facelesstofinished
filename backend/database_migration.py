"""One-time, BSON-preserving database migration helpers.

This module intentionally contains no HTTP or authentication logic.  The
production API owns the one-time gate; these helpers only copy MongoDB data
from one already-authorized database handle to another.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from pymongo import ReplaceOne


MIGRATION_STATE_COLLECTION = "database_migrations"
_SKIPPED_COLLECTIONS = {MIGRATION_STATE_COLLECTION}

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


def migration_collection_names(names: Iterable[str]) -> list[str]:
    """Return deterministic application collections safe to copy."""
    return sorted(
        name
        for name in names
        if name not in _SKIPPED_COLLECTIONS and not name.startswith("system.")
    )


def index_create_spec(index: dict[str, Any]) -> tuple[list[tuple[str, Any]], dict[str, Any]] | None:
    """Convert ``list_indexes`` output into ``create_index`` arguments."""
    if index.get("name") == "_id_":
        return None
    raw_keys = index.get("key") or {}
    keys = list(raw_keys.items()) if hasattr(raw_keys, "items") else list(raw_keys)
    options = {
        key: value
        for key, value in index.items()
        if key not in {"key", "ns", "v"}
    }
    return keys, options


async def copy_collection(
    source_collection: Any,
    target_collection: Any,
    *,
    batch_size: int = 100,
    progress: ProgressCallback | None = None,
) -> dict[str, int]:
    """Upsert one collection while preserving native BSON values and indexes."""
    source_count = await source_collection.count_documents({})
    copied = 0
    operations: list[ReplaceOne] = []

    cursor = source_collection.find({}).batch_size(batch_size)
    async for document in cursor:
        operations.append(ReplaceOne({"_id": document["_id"]}, document, upsert=True))
        if len(operations) >= batch_size:
            await target_collection.bulk_write(operations, ordered=False)
            copied += len(operations)
            operations.clear()
            if progress:
                await progress({"copied": copied, "source_count": source_count})

    if operations:
        await target_collection.bulk_write(operations, ordered=False)
        copied += len(operations)
        if progress:
            await progress({"copied": copied, "source_count": source_count})

    async for raw_index in source_collection.list_indexes():
        spec = index_create_spec(dict(raw_index))
        if spec is None:
            continue
        keys, options = spec
        await target_collection.create_index(keys, **options)

    target_count = await target_collection.count_documents({})
    if target_count != source_count:
        raise RuntimeError(
            f"collection verification failed: source={source_count}, target={target_count}"
        )
    return {
        "source_count": source_count,
        "copied": copied,
        "target_count": target_count,
    }


async def copy_database(
    source_database: Any,
    target_database: Any,
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Copy every application collection and verify document counts."""
    names = migration_collection_names(await source_database.list_collection_names())
    results: dict[str, dict[str, int]] = {}
    for position, name in enumerate(names, start=1):
        if progress:
            await progress(
                {
                    "phase": "copying",
                    "collection": name,
                    "collection_number": position,
                    "collection_total": len(names),
                }
            )

        async def collection_progress(update: dict[str, Any]) -> None:
            if progress:
                await progress({"collection": name, **update})

        results[name] = await copy_collection(
            source_database[name],
            target_database[name],
            progress=collection_progress,
        )

    source_total = sum(item["source_count"] for item in results.values())
    target_total = sum(item["target_count"] for item in results.values())
    return {
        "collections": results,
        "collection_count": len(results),
        "source_total": source_total,
        "target_total": target_total,
    }
