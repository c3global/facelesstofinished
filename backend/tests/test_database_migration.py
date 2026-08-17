from collections import OrderedDict

from database_migration import index_create_spec, migration_collection_names


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
