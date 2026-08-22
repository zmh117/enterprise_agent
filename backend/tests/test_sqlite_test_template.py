from __future__ import annotations

from pathlib import Path

import pytest

from app.bootstrap import _MigratedSQLiteTemplateCache, build_test_container
from app.shared.database import Database
from backend.tests.helpers import test_settings as make_test_settings


def _database_from_template(template_path: Path) -> Database:
    return Database(
        "sqlite:///:memory:",
        pool_min_size=1,
        pool_max_size=2,
        sqlite_template_path=template_path,
    )


def test_sqlite_template_restores_isolated_shared_memory_databases(tmp_path: Path) -> None:
    template_path = tmp_path / "template.sqlite3"
    template = Database(f"sqlite:///{template_path}")
    template.execute("create table template_fact (id text primary key, value text not null)")
    template.execute(
        "insert into template_fact (id, value) values (?, ?)",
        ("baseline", "immutable"),
    )
    template.close()

    first = _database_from_template(template_path)
    second = _database_from_template(template_path)
    try:
        assert first.execute_one(
            "select value from template_fact where id = ?",
            ("baseline",),
        ) == {"value": "immutable"}
        assert second.execute_one(
            "select value from template_fact where id = ?",
            ("baseline",),
        ) == {"value": "immutable"}

        first.execute(
            "insert into template_fact (id, value) values (?, ?)",
            ("first-only", "isolated"),
        )
        assert first.execute_one(
            "select value from template_fact where id = ?",
            ("first-only",),
        ) == {"value": "isolated"}
        assert (
            second.execute_one(
                "select value from template_fact where id = ?",
                ("first-only",),
            )
            is None
        )
    finally:
        first.close()
        second.close()


def test_sqlite_template_is_visible_to_additional_pool_connections(tmp_path: Path) -> None:
    template_path = tmp_path / "template.sqlite3"
    template = Database(f"sqlite:///{template_path}")
    template.execute("create table shared_fact (id integer primary key)")
    template.close()

    database = _database_from_template(template_path)
    try:
        with database.session() as first_connection:
            first_connection.execute("insert into shared_fact (id) values (1)")
            first_connection.commit()
            with database._connection_pool().connection() as second_connection:
                row = second_connection.execute("select count(*) from shared_fact").fetchone()
                assert row is not None
                assert int(row[0]) == 1
    finally:
        database.close()


def test_migrated_template_cache_reuses_identity_and_rebuilds_after_change(
    tmp_path: Path,
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    migration = migrations_dir / "001_create_template_fact.sql"
    migration.write_text(
        "create table template_fact (id text primary key);\n",
        encoding="utf-8",
    )
    cache = _MigratedSQLiteTemplateCache()

    first = cache.get(migrations_dir)
    same = cache.get(migrations_dir)
    assert same == first

    migration.write_text(
        "create table template_fact (id text primary key, value text);\n",
        encoding="utf-8",
    )
    changed = cache.get(migrations_dir)

    assert changed.identity != first.identity
    assert changed.path != first.path
    database = _database_from_template(changed.path)
    try:
        columns = {str(row["name"]) for row in database.execute("pragma table_info(template_fact)")}
        assert columns == {"id", "value"}
    finally:
        database.close()


def test_test_container_template_keeps_seed_and_writes_isolated() -> None:
    first = build_test_container(make_test_settings(), migrate=True, seed=True)
    second = build_test_container(make_test_settings(), migrate=True, seed=True)
    try:
        first.database.execute("create table first_container_only (id integer primary key)")
        assert (
            second.database.execute_one(
                "select name from sqlite_master where type = 'table' and name = ?",
                ("first_container_only",),
            )
            is None
        )
        assert first.database.execute_one("select count(*) as count from app_user") == {"count": 2}
        assert second.database.execute_one("select count(*) as count from app_user") == {"count": 2}
    finally:
        first.database.close()
        second.database.close()


def test_test_container_can_bypass_migrated_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_template_is_requested(migrations_dir: Path) -> None:
        del migrations_dir
        raise AssertionError("template cache must be bypassed")

    monkeypatch.setattr(
        "app.bootstrap._MIGRATED_SQLITE_TEMPLATE_CACHE.get",
        fail_if_template_is_requested,
    )
    runtime = build_test_container(
        make_test_settings(),
        migrate=True,
        seed=False,
        reuse_migrated_sqlite_template=False,
    )
    try:
        assert (
            runtime.database.execute_one(
                "select version from schema_migration order by version desc limit 1"
            )
            is not None
        )
    finally:
        runtime.database.close()


def test_sqlite_template_rejects_missing_or_non_memory_targets(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(ValueError, match="existing file"):
        Database("sqlite:///:memory:", sqlite_template_path=missing)

    template = tmp_path / "template.sqlite3"
    template.touch()
    with pytest.raises(ValueError, match="sqlite:///:memory:"):
        Database(f"sqlite:///{tmp_path / 'target.sqlite3'}", sqlite_template_path=template)
