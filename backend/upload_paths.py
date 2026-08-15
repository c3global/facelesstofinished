"""Pure helpers for public GridFS upload URLs."""

from __future__ import annotations


def object_id_from_public_file_token(file_token: str) -> str:
    """Remove the optional codec extension from ``<object-id>.<ext>`` URLs."""

    return str(file_token or "").split(".", 1)[0]
