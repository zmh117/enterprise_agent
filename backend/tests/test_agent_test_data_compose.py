from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
MAIN_COMPOSE = ROOT / "docker-compose.yml"
AGENT_TEST_DATA_COMPOSE = ROOT / "ones_mock" / "docker-compose.ones-mock.yml"


class AgentTestDataComposeTests(unittest.TestCase):
    def _main_compose(self) -> dict[str, object]:
        return yaml.safe_load(MAIN_COMPOSE.read_text())

    def _agent_test_data_compose(self) -> dict[str, object]:
        return yaml.safe_load(AGENT_TEST_DATA_COMPOSE.read_text())

    def test_agent_test_data_profile_has_four_persistent_services_and_seeder(self) -> None:
        compose = self._agent_test_data_compose()
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
        agent_test_volume_keys = {
            "agent-test-mysql-data",
            "agent-test-sqlserver-data",
            "agent-test-redis-mysql-data",
            "agent-test-redis-sqlserver-data",
        }
        self.assertEqual(
            {
                "enterprise_agent_agent_test_mysql_data",
                "enterprise_agent_agent_test_sqlserver_data",
                "enterprise_agent_agent_test_redis_mysql_data",
                "enterprise_agent_agent_test_redis_sqlserver_data",
            },
            {volumes[key]["name"] for key in agent_test_volume_keys},
        )
        for key in agent_test_volume_keys:
            self.assertTrue(volumes[key].get("external") is True)

    def test_main_compose_does_not_define_agent_test_data_services(self) -> None:
        services = self._main_compose()["services"]  # type: ignore[index]
        for name in (
            "agent-test-mysql",
            "agent-test-sqlserver",
            "agent-test-redis-mysql",
            "agent-test-redis-sqlserver",
            "agent-test-data-seeder",
        ):
            self.assertNotIn(name, services)

    def test_main_compose_keeps_core_runtime_volumes(self) -> None:
        volumes = self._main_compose()["volumes"]  # type: ignore[index]
        self.assertEqual("enterprise_agent_postgres18_data", volumes["postgres18-data"]["name"])
        self.assertEqual("enterprise_agent_rabbitmq4_data", volumes["rabbitmq4-data"]["name"])

    def test_runtime_services_do_not_receive_agent_test_admin_credentials(self) -> None:
        services = self._main_compose()["services"]  # type: ignore[index]
        forbidden_prefixes = (
            "AGENT_TEST_MYSQL_ROOT_PASSWORD",
            "AGENT_TEST_SQLSERVER_SA_PASSWORD",
            "AGENT_TEST_REDIS_",
        )
        for service_name in ("tool-mcp", "agent-worker"):
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
        self.assertIn("ones_mock/docker-compose.ones-mock.yml", script)
        for volume in (
            "enterprise_agent_agent_test_mysql_data",
            "enterprise_agent_agent_test_sqlserver_data",
            "enterprise_agent_agent_test_redis_mysql_data",
            "enterprise_agent_agent_test_redis_sqlserver_data",
        ):
            self.assertIn(volume, script)


if __name__ == "__main__":
    unittest.main()
