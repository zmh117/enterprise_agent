from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.agent_test_data import manifest
from app.agent_test_data import seeder


class AgentTestManifestTests(unittest.TestCase):
    def test_manifest_tables_rows_and_redis_fixture_are_deterministic(self) -> None:
        manifest.assert_manifest_consistent()
        self.assertEqual(
            {
                "production_order",
                "equipment",
                "equipment_alarm",
                "material_inventory",
                "quality_inspection",
                "production_event",
            },
            {table.name for table in manifest.TABLES},
        )
        self.assertEqual(2, manifest.EXPECTED_ROW_COUNTS["production_order"])
        self.assertEqual("PO-STUCK-001", manifest.EXPECTED_ANOMALIES["stuck_order"])
        mysql_keys = {item.key for item in manifest.redis_fixtures("mysql")}
        sqlserver_keys = {item.key for item in manifest.redis_fixtures("sqlserver")}
        self.assertTrue(all(key.startswith("agent_test:mysql:") for key in mysql_keys))
        self.assertTrue(all(key.startswith("agent_test:sqlserver:") for key in sqlserver_keys))
        self.assertTrue(mysql_keys.isdisjoint(sqlserver_keys))


class FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, object | None]] = []
        self._fetch_values: list[tuple[object, ...]] = []

    def execute(self, sql: str, params: object | None = None) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> tuple[object, ...]:
        return self._fetch_values.pop(0)

    def fetchall(self) -> list[tuple[object, ...]]:
        return []

    def close(self) -> None:
        return None


class AgentTestSeederSqlTests(unittest.TestCase):
    def test_dialect_schema_statements_cover_all_fixture_tables(self) -> None:
        for statements in (
            seeder.mysql_schema_statements(),
            seeder.sqlserver_schema_statements(),
        ):
            joined = "\n".join(statements).lower()
            for table in manifest.TABLES:
                self.assertIn(table.name, joined)

    def test_seed_statement_order_deletes_before_inserting_fixed_rows(self) -> None:
        cursor = FakeCursor()
        seeder._delete_fixture_rows(cursor, "%s")
        seeder._insert_fixture_rows(cursor, "%s")
        first_insert = next(
            index for index, (sql, _params) in enumerate(cursor.executed) if "INSERT INTO" in sql
        )
        self.assertTrue(all("DELETE FROM" in sql for sql, _params in cursor.executed[:first_insert]))
        self.assertEqual(
            sum(manifest.EXPECTED_ROW_COUNTS.values()),
            sum(1 for sql, _params in cursor.executed if "INSERT INTO" in sql),
        )


class FakeRedisClient:
    def __init__(self) -> None:
        self.values = {
            "agent_test:mysql:old": "stale",
            "unrelated:key": "keep",
        }
        self.acl_calls: list[tuple[str, object]] = []

    def acl_setuser(self, user: str, **kwargs: object) -> None:
        self.acl_calls.append((user, kwargs))

    def scan_iter(self, *, match: str, count: int) -> list[str]:
        prefix = match.rstrip("*")
        return [key for key in self.values if key.startswith(prefix)]

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value


class AgentTestRedisSeederTests(unittest.TestCase):
    def test_redis_seed_clears_only_base_namespace_and_creates_acl_users(self) -> None:
        client = FakeRedisClient()
        redis_seeder = seeder.RedisSeeder("mysql")
        with (
            patch.object(redis_seeder, "connect_admin", return_value=client),
            patch.dict(
                os.environ,
                {
                    "SECRET_AGENT_TEST_MYSQL_REDIS_USER": "reader",
                    "SECRET_AGENT_TEST_MYSQL_REDIS_PASSWORD": "reader-pw",
                    "AGENT_TEST_REDIS_MYSQL_SEEDER_USER": "seed",
                    "AGENT_TEST_REDIS_MYSQL_SEEDER_PASSWORD": "seed-pw",
                },
                clear=False,
            ),
        ):
            redis_seeder.seed()
        self.assertIn("unrelated:key", client.values)
        self.assertNotIn("agent_test:mysql:old", client.values)
        self.assertEqual({"reader", "seed"}, {user for user, _kwargs in client.acl_calls})
        self.assertEqual(
            {item.key: item.value for item in manifest.redis_fixtures("mysql")},
            {key: value for key, value in client.values.items() if key.startswith("agent_test:mysql:")},
        )


class AgentTestSeederCliTests(unittest.TestCase):
    def test_run_sources_reports_all_failures_and_masks_environment_secrets(self) -> None:
        class BrokenSource:
            name = "broken"

            def seed(self) -> None:
                raise RuntimeError("password is clear-secret-value")

        with patch.dict(os.environ, {"AGENT_TEST_MYSQL_ROOT_PASSWORD": "clear-secret-value"}):
            [result] = seeder.run_sources("seed", sources=[BrokenSource()])
        self.assertFalse(result.ok)
        self.assertNotIn("clear-secret-value", result.message)

    def test_architecture_warning_is_arm64_only(self) -> None:
        lines: list[str] = []
        with patch("platform.machine", return_value="arm64"):
            seeder.warn_architecture(lines.append)
        self.assertEqual(1, len(lines))

        lines.clear()
        with patch("platform.machine", return_value="x86_64"):
            seeder.warn_architecture(lines.append)
        self.assertEqual([], lines)


if __name__ == "__main__":
    unittest.main()
