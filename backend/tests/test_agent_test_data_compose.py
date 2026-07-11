from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class AgentTestDataComposeTests(unittest.TestCase):
    def _compose(self) -> dict[str, object]:
        return yaml.safe_load((ROOT / "docker-compose.yml").read_text())

    def test_agent_test_data_profile_has_four_persistent_services_and_seeder(self) -> None:
        compose = self._compose()
        services = compose["services"]  # type: ignore[index]
        expected = {
            "agent-test-mysql",
            "agent-test-sqlserver",
            "agent-test-redis-mysql",
            "agent-test-redis-sqlserver",
            "agent-test-data-seeder",
        }
        self.assertTrue(expected.issubset(services))
        for name in expected:
            self.assertEqual(["agent-test-data"], services[name]["profiles"])
        self.assertIn("linux/amd64", services["agent-test-sqlserver"]["platform"])
        volumes = compose["volumes"]  # type: ignore[index]
        self.assertEqual(
            {
                "enterprise_agent_agent_test_mysql_data",
                "enterprise_agent_agent_test_sqlserver_data",
                "enterprise_agent_agent_test_redis_mysql_data",
                "enterprise_agent_agent_test_redis_sqlserver_data",
            },
            {value["name"] for value in volumes.values()},
        )

    def test_runtime_services_do_not_receive_agent_test_admin_credentials(self) -> None:
        services = self._compose()["services"]  # type: ignore[index]
        forbidden_prefixes = (
            "AGENT_TEST_MYSQL_ROOT_PASSWORD",
            "AGENT_TEST_SQLSERVER_SA_PASSWORD",
            "AGENT_TEST_REDIS_",
        )
        for service_name in ("internal-api-platform", "agent-worker"):
            environment = services[service_name]["environment"]
            for key in environment:
                self.assertFalse(
                    key.startswith(forbidden_prefixes),
                    f"{service_name} leaked management credential variable {key}",
                )


class AgentTestDataLifecycleScriptTests(unittest.TestCase):
    def test_reset_uses_allowlisted_volumes_and_not_project_down_v(self) -> None:
        script = (ROOT / "scripts" / "agent_test_data.sh").read_text()
        self.assertIn("reset --yes", script)
        self.assertNotIn("down -v", script)
        for volume in (
            "enterprise_agent_agent_test_mysql_data",
            "enterprise_agent_agent_test_sqlserver_data",
            "enterprise_agent_agent_test_redis_mysql_data",
            "enterprise_agent_agent_test_redis_sqlserver_data",
        ):
            self.assertIn(volume, script)


if __name__ == "__main__":
    unittest.main()
