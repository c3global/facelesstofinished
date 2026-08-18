from collections import OrderedDict

import pytest

from database_migration import (
    index_create_spec,
    migration_collection_names,
    resolve_database_settings,
)


def test_database_settings_keep_platform_database_by_default():
    assert resolve_database_settings(
        {"MONGO_URL": "mongodb://platform", "DB_NAME": "platform_db"}
    ) == ("mongodb://platform", "platform_db", False)


def test_database_settings_use_owner_target_in_cutover_mode():
    assert resolve_database_settings(
        {
            "MONGO_URL": "mongodb://platform",
            "DB_NAME": "platform_db",
            "DATABASE_MIGRATION_ENABLED": "cutover",
            "DATABASE_MIGRATION_TARGET_URL": "mongodb+srv://owner",
            "DATABASE_MIGRATION_TARGET_DB": "faceless48",
        }
    ) == ("mongodb+srv://owner", "faceless48", True)


def test_database_cutover_fails_closed_without_target_settings():
    with pytest.raises(RuntimeError, match="missing its target settings"):
        resolve_database_settings(
            {
                "MONGO_URL": "mongodb://platform",
                "DB_NAME": "platform_db",
                "DATABASE_MIGRATION_ENABLED": "cutover",
            }
        )


def test_migration_collection_names_excludes_internal_state():
    assert migration_collection_names(
        ["renders", "system.profile", "database_migrations", "buyers"]
    ) == ["buyers", "renders"]


def test_index_create_spec_preserves_supported_options():
    spec = index_create_spec(
        {
            "v": 2,
            "key": OrderedDict([("email", 1)]),
            "name": "email_1",
            "unique": True,
            "sparse": True,
        }
    )
    assert spec == (
        [("email", 1)],
        {"name": "email_1", "unique": True, "sparse": True},
    )


def test_index_create_spec_skips_id_index():
    assert index_create_spec({"key": {"_id": 1}, "name": "_id_", "v": 2}) is None
