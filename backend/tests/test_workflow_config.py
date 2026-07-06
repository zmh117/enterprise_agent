from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.config import Settings
from backend.tests.helpers import container, test_settings as make_settings


class WorkflowConfigTests(unittest.TestCase):
    def test_workflow_template_nodes_edges_and_publication(self) -> None:
        settings = make_settings()

        def factory(_: Settings):
            return container()

        with TestClient(create_app(settings, container_factory=factory)) as client:
            headers = {"x-admin-user-id": "local-user"}
            created = client.post(
                "/api/agent/workflows",
                headers=headers,
                json={
                    "code": "order-diagnosis",
                    "name": "订单诊断",
                    "project_code": "default",
                },
            )
            self.assertEqual(200, created.status_code)

            start = client.post(
                "/api/agent/workflows/order-diagnosis/nodes",
                headers=headers,
                json={
                    "node_key": "start",
                    "node_type": "trigger",
                    "title": "入口",
                    "position": {"x": 0, "y": 0},
                },
            )
            report = client.post(
                "/api/agent/workflows/order-diagnosis/nodes",
                headers=headers,
                json={
                    "node_key": "report",
                    "node_type": "report",
                    "title": "报告",
                    "position": {"x": 320, "y": 0},
                },
            )
            self.assertEqual(200, start.status_code)
            self.assertEqual(200, report.status_code)

            updated = client.post(
                "/api/agent/workflows",
                headers=headers,
                json={
                    "code": "order-diagnosis",
                    "name": "订单诊断",
                    "project_code": "default",
                    "entry_node_key": "start",
                },
            )
            self.assertEqual(200, updated.status_code)

            edge = client.post(
                "/api/agent/workflows/order-diagnosis/edges",
                headers=headers,
                json={
                    "edge_key": "start-report",
                    "source_node_key": "start",
                    "target_node_key": "report",
                },
            )
            self.assertEqual(200, edge.status_code)

            publication = client.post(
                "/api/agent/workflows/order-diagnosis/publish",
                headers=headers,
            )
            self.assertEqual(200, publication.status_code)
            self.assertEqual(2, publication.json()["publication"]["version"])
            self.assertEqual(
                "start",
                publication.json()["publication"]["graph_snapshot"]["template"]["entry_node_key"],
            )

    def test_workflow_rejects_mutation_nodes_and_missing_edge_targets(self) -> None:
        settings = make_settings()

        def factory(_: Settings):
            return container()

        with TestClient(create_app(settings, container_factory=factory)) as client:
            headers = {"x-admin-user-id": "local-user"}
            client.post(
                "/api/agent/workflows",
                headers=headers,
                json={"code": "safe-flow", "name": "安全诊断"},
            )
            mutation = client.post(
                "/api/agent/workflows/safe-flow/nodes",
                headers=headers,
                json={
                    "node_key": "delete-redis",
                    "node_type": "tool_call",
                    "config": {"operation": "delete_redis_key"},
                },
            )
            self.assertEqual(400, mutation.status_code)
            self.assertIn("Mutation workflow node", mutation.json()["detail"])

            edge = client.post(
                "/api/agent/workflows/safe-flow/edges",
                headers=headers,
                json={
                    "edge_key": "missing",
                    "source_node_key": "start",
                    "target_node_key": "report",
                },
            )
            self.assertEqual(400, edge.status_code)
            self.assertIn("missing node", edge.json()["detail"])


if __name__ == "__main__":
    unittest.main()
