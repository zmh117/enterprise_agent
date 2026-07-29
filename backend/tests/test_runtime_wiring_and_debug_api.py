from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from app.bootstrap import (
    build_api_container,
    build_test_container,
    build_worker_container,
)
from app.main import create_app
from app.modules.agent.infrastructure.claude_code_agent_client import (
    RealClaudeCodeAgentClient,
    StubClaudeCodeAgentClient,
)
from app.modules.internal_tools.infrastructure.internal_api_client import (
    FakeInternalApiClient,
    HttpInternalApiClient,
    ToolRequestContext,
    ToolResult,
)
from app.modules.job.domain.job_status import JobStatus
from app.modules.message_bus.infrastructure.rabbitmq_consumer import RabbitMQConsumer
from app.modules.message_bus.infrastructure.rabbitmq_publisher import RabbitMQPublisher
from app.shared.config import Settings
from app.shared.database import Database, default_migrations_dir
from app.shared.feature_configuration import feature_configuration_from_values
from app.shared.migrations import Migrator
from backend.tests.helpers import (
    dingtalk_payload,
    dingtalk_sign,
    prepare_debug_application_access,
    publish_pending_agent_jobs,
    test_settings as make_settings,
)


def _debug_settings() -> Settings:
    settings = make_settings()
    return replace(
        settings,
        feature_configuration=feature_configuration_from_values(
            web_admin=True,
            published_agent_runtime=True,
            unified_identity=True,
            test_identity_headers=True,
        ),
        identity=replace(
            settings.identity,
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            test_identity_headers_enabled=True,
        ),
    )


def _debug_headers() -> dict[str, str]:
    return {"x-admin-user-id": "local-user"}


def _authorized_debug_payload(
    container: object,
    *,
    message: str,
    idempotency_key: str,
) -> dict[str, str]:
    stable = idempotency_key.replace("_", "-")
    selection = prepare_debug_application_access(
        container,
        application_code=f"debug-{stable}-application",
        role_code=f"debug-{stable}-role",
        capabilities=(
            "get_er_context",
            "get_business_flow_context",
            "diagnose_loki_probe",
        ),
    )
    return {
        "message": message,
        "idempotency_key": idempotency_key,
        "application_id": selection["application_id"],
        "execution_scope_id": selection["execution_scope_id"],
    }


class ContextMetadataInternalApiClient(FakeInternalApiClient):
    def get_er_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        summary = {"tables": ["ws_a_order"], "source": "mock-er"}
        return ToolResult(
            summary=summary,
            raw=summary,
            metadata={"request_id": context.correlation_id, "source": "mock-er"},
        )

    def get_business_flow_context(self, query: str, context: ToolRequestContext) -> ToolResult:
        summary = {"nodes": ["material_pick"], "source": "mock-flow"}
        return ToolResult(
            summary=summary,
            raw=summary,
            metadata={"request_id": context.correlation_id, "source": "mock-flow"},
        )


class FakeHttpResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _migrated_runtime_settings(
    settings: Settings,
    directory: Path,
) -> Settings:
    migrated = replace(
        settings,
        database_dsn=f"sqlite:///{directory / 'runtime.db'}",
    )
    database = Database(migrated.database_dsn)
    try:
        Migrator(
            database,
            default_migrations_dir(),
            migrator_build="runtime-wiring-test",
        ).run()
    finally:
        database.close()
    return migrated


class RuntimeWiringAndDebugApiTests(unittest.TestCase):
    def test_compose_runtime_uses_rabbitmq_not_in_memory_bus(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = _migrated_runtime_settings(
                make_settings(),
                Path(temporary_directory),
            )
            api_container = build_api_container(settings, seed=True)
            worker_container = build_worker_container(settings, seed=True)
            test_container = build_test_container(settings, migrate=False, seed=True)
            try:
                self.assertIsInstance(api_container.publisher, RabbitMQPublisher)
                self.assertIsNone(api_container.consumer)
                self.assertIsNone(api_container.message_bus)

                self.assertIsInstance(worker_container.publisher, RabbitMQPublisher)
                self.assertIsInstance(worker_container.consumer, RabbitMQConsumer)
                self.assertIsNone(worker_container.message_bus)

                self.assertIsNotNone(test_container.message_bus)
            finally:
                api_container.database.close()
                worker_container.database.close()
                test_container.database.close()

    def test_feature_flag_selects_real_claude_only_for_production_runtime(self) -> None:
        real_settings = replace(
            make_settings(),
            feature_real_claude=True,
            anthropic_api_key="test-key",
        )
        with TemporaryDirectory() as temporary_directory:
            real_settings = _migrated_runtime_settings(
                real_settings,
                Path(temporary_directory),
            )
            api_container = build_api_container(real_settings, seed=True)
            test_container = build_test_container(
                real_settings,
                migrate=False,
                seed=True,
            )
            try:
                self.assertIsInstance(
                    api_container.agent_executor.claude_client,
                    RealClaudeCodeAgentClient,
                )
                self.assertIsInstance(
                    test_container.agent_executor.claude_client,
                    StubClaudeCodeAgentClient,
                )
            finally:
                api_container.database.close()
                test_container.database.close()

    def test_feature_flag_selects_real_internal_tools_only_for_production_runtime(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            token_path = Path(temporary_directory) / "internal-api-token.json"
            token_path.write_text(
                '{"current":"runtime-wiring-current-token-000001"}',
                encoding="utf-8",
            )
            real_settings = replace(
                make_settings(),
                feature_real_internal_tools=True,
                internal_api_base_url="http://internal.test",
                internal_api_auth_token_file=str(token_path),
            )
            real_settings = _migrated_runtime_settings(
                real_settings,
                Path(temporary_directory),
            )
            api_container = build_api_container(real_settings, seed=True)
            worker_container = build_worker_container(real_settings, seed=True)
            test_container = build_test_container(
                real_settings,
                migrate=False,
                seed=True,
            )
            try:
                self.assertIsInstance(
                    api_container.internal_api_client,
                    HttpInternalApiClient,
                )
                self.assertIsInstance(
                    worker_container.internal_api_client,
                    HttpInternalApiClient,
                )
                self.assertIsInstance(
                    test_container.internal_api_client,
                    FakeInternalApiClient,
                )
            finally:
                api_container.database.close()
                worker_container.database.close()
                test_container.database.close()

    def test_lifespan_builds_container_once_for_multiple_webhooks(self) -> None:
        base_settings = make_settings()
        settings = replace(
            base_settings,
            dingtalk=replace(base_settings.dingtalk, http_webhook_enabled=True),
        )
        built = []

        def factory(_: Settings):
            container = build_test_container(settings, migrate=True, seed=True)
            built.append(container)
            return container

        with TestClient(create_app(settings, container_factory=factory)) as client:
            timestamp = "1710000000000"
            for index in range(2):
                response = client.post(
                    "/webhooks/dingding/agent",
                    json=dingtalk_payload(msg_id=f"msg-{index}"),
                    headers={
                        "x-dingtalk-timestamp": timestamp,
                        "x-dingtalk-sign": dingtalk_sign("test-secret", timestamp),
                    },
                )
                self.assertEqual(200, response.status_code)

            container = built[0]
            self.assertEqual(1, len(built))
            self.assertEqual(2, container.agent_repository.count_rows("agent_job"))
            self.assertIsNotNone(container.message_bus)
            publish_pending_agent_jobs(container)
            self.assertEqual(2, len(container.message_bus.jobs))

    def test_debug_api_creates_idempotent_job_and_exposes_execution_trace(self) -> None:
        settings = _debug_settings()
        built = []

        def factory(_: Settings):
            container = build_test_container(settings, migrate=True, seed=True)
            built.append(container)
            return container

        with TestClient(create_app(settings, container_factory=factory)) as client:
            container = built[0]
            payload = _authorized_debug_payload(
                container,
                message="帮我查一下订单 MO20260627001 为什么一直待领料",
                idempotency_key="same-debug-job",
            )
            first = client.post(
                "/api/agent/jobs",
                headers=_debug_headers(),
                json=payload,
            )
            second = client.post(
                "/api/agent/jobs",
                headers=_debug_headers(),
                json=payload,
            )

            self.assertEqual(200, first.status_code)
            self.assertEqual(200, second.status_code)
            self.assertEqual(first.json()["job_id"], second.json()["job_id"])
            self.assertIsNotNone(container.message_bus)
            publish_pending_agent_jobs(container)
            self.assertEqual(1, len(container.message_bus.jobs))

            job_id = str(first.json()["job_id"])
            pending = client.get(
                f"/api/agent/jobs/{job_id}",
                headers=_debug_headers(),
            )
            self.assertEqual(JobStatus.PENDING.value, pending.json()["status"])

            container.message_bus.consume_agent_jobs(
                lambda message: container.agent_executor.execute(
                    message.job_id,
                    fail_on_error=True,
                )
            )

            completed = client.get(
                f"/api/agent/jobs/{job_id}",
                headers=_debug_headers(),
            )
            self.assertEqual(JobStatus.SUCCEEDED.value, completed.json()["status"])
            self.assertIn("read-only diagnostic", completed.json()["result"])

            steps = client.get(
                f"/api/agent/jobs/{job_id}/steps",
                headers=_debug_headers(),
            )
            tool_calls = client.get(
                f"/api/agent/jobs/{job_id}/tool-calls",
                headers=_debug_headers(),
            )
            self.assertEqual(200, steps.status_code)
            self.assertEqual(200, tool_calls.status_code)
            self.assertGreaterEqual(len(steps.json()["steps"]), 3)
            self.assertEqual(2, len(tool_calls.json()["tool_calls"]))

    def test_debug_api_worker_persists_mock_internal_platform_tool_metadata(self) -> None:
        settings = _debug_settings()
        built = []

        def factory(_: Settings):
            container = build_test_container(settings, migrate=True, seed=True)
            container.tool_service.internal_api_client = ContextMetadataInternalApiClient()
            built.append(container)
            return container

        with TestClient(create_app(settings, container_factory=factory)) as client:
            container = built[0]
            created = client.post(
                "/api/agent/jobs",
                headers=_debug_headers(),
                json=_authorized_debug_payload(
                    container,
                    message="帮我查一下订单 MO20260627001 为什么一直待领料",
                    idempotency_key="mock-platform-debug-job",
                ),
            )
            job_id = str(created.json()["job_id"])

            publish_pending_agent_jobs(container)
            container.message_bus.consume_agent_jobs(
                lambda message: container.agent_executor.execute(
                    message.job_id,
                    fail_on_error=True,
                )
            )

            completed = client.get(
                f"/api/agent/jobs/{job_id}",
                headers=_debug_headers(),
            )
            tool_calls = client.get(
                f"/api/agent/jobs/{job_id}/tool-calls",
                headers=_debug_headers(),
            )

            self.assertEqual(JobStatus.SUCCEEDED.value, completed.json()["status"])
            payloads = [
                call["response_summary"]["payload"] for call in tool_calls.json()["tool_calls"]
            ]
            self.assertTrue(any("mock-er" in payload for payload in payloads))

    def test_debug_api_worker_persists_local_platform_http_envelope(self) -> None:
        settings = _debug_settings()
        built = []

        def fake_urlopen(request: Any, timeout: int) -> FakeHttpResponse:
            if request.full_url.endswith("/tools/context/er"):
                source = "local-er-placeholder"
                summary = {"source": "local-placeholder-er-context", "tables": []}
            else:
                source = "local-business-flow-placeholder"
                summary = {"source": "local-placeholder-business-flow-context", "nodes": []}
            return FakeHttpResponse(
                {
                    "summary": summary,
                    "raw": summary,
                    "truncated": False,
                    "metadata": {"request_id": "corr-1", "source": source, "duration_ms": 1},
                }
            )

        def factory(_: Settings):
            container = build_test_container(settings, migrate=True, seed=True)
            container.tool_service.internal_api_client = HttpInternalApiClient(
                "http://local-platform.test",
                urlopen_func=fake_urlopen,
            )
            built.append(container)
            return container

        with TestClient(create_app(settings, container_factory=factory)) as client:
            container = built[0]
            created = client.post(
                "/api/agent/jobs",
                headers=_debug_headers(),
                json=_authorized_debug_payload(
                    container,
                    message="帮我查一下订单 MO20260627001 为什么一直待领料",
                    idempotency_key="local-platform-debug-job",
                ),
            )
            job_id = str(created.json()["job_id"])

            publish_pending_agent_jobs(container)
            container.message_bus.consume_agent_jobs(
                lambda message: container.agent_executor.execute(
                    message.job_id,
                    fail_on_error=True,
                )
            )

            tool_calls = client.get(
                f"/api/agent/jobs/{job_id}/tool-calls",
                headers=_debug_headers(),
            )
            payloads = [
                call["response_summary"]["payload"] for call in tool_calls.json()["tool_calls"]
            ]

            self.assertTrue(any("local-er-placeholder" in payload for payload in payloads))
            self.assertTrue(
                any("local-business-flow-placeholder" in payload for payload in payloads)
            )

    def test_debug_api_exposes_loki_diagnostic_tool_metadata(self) -> None:
        settings = _debug_settings()
        built = []

        def factory(_: Settings):
            container = build_test_container(settings, migrate=True, seed=True)
            built.append(container)
            return container

        with TestClient(create_app(settings, container_factory=factory)) as client:
            container = built[0]
            created = client.post(
                "/api/agent/jobs",
                headers=_debug_headers(),
                json=_authorized_debug_payload(
                    container,
                    message="用合成日志检查 Loki selector",
                    idempotency_key="loki-diagnostic-tool-job",
                ),
            )
            job_id = str(created.json()["job_id"])

            # This assertion targets the synthetic legacy Loki adapter metadata.
            # Platform-scope authorization has dedicated coverage elsewhere.
            container.permission_service.unified_enabled = False
            container.database.execute_script(
                """
                insert into permission_policy
                  (id, subject_type, subject_code, resource_type, resource_code,
                   effect, action, status, priority, revision, created_at, updated_at)
                values
                  ('test-debug-project', 'user', 'user_local_admin', 'project',
                   'default', 'allow', 'use', 'enabled', 10, 1,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                  ('test-debug-tools', 'user', 'user_local_admin', 'tool',
                   '*', 'allow', 'use', 'enabled', 10, 1,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
                """
            )
            container.tool_service.call_tool(
                job_id=job_id,
                user_id="user_local_admin",
                project_code="default",
                tool_name="diagnose_loki_probe",
                arguments={
                    "environment": "local",
                    "base": "debug-base",
                    "selector": {"service": "order-service"},
                    "query": "synthetic-test-error",
                    "minutes": 5,
                    "limit": 10,
                },
            )

            tool_calls = client.get(
                f"/api/agent/jobs/{job_id}/tool-calls",
                headers=_debug_headers(),
            )
            self.assertEqual(200, tool_calls.status_code)
            diagnostic = tool_calls.json()["tool_calls"][0]
            self.assertEqual("diagnose_loki_probe", diagnostic["tool_name"])
            self.assertEqual("low", diagnostic["risk_level"])
            payload = diagnostic["response_summary"]["payload"]
            self.assertIn("fake-loki-diagnostics", payload)
            self.assertIn("empty_result_hints", payload)

    def test_debug_api_rejects_unauthorized_user_and_missing_job(self) -> None:
        settings = _debug_settings()
        built = []

        def factory(_: Settings):
            container = build_test_container(settings, migrate=True, seed=True)
            built.append(container)
            return container

        with TestClient(create_app(settings, container_factory=factory)) as client:
            forbidden = client.post(
                "/api/agent/jobs",
                json={
                    "message": "check order",
                    "application_id": "business_app_unknown",
                    "execution_scope_id": "debug_scope_unknown",
                },
            )
            missing = client.get(
                "/api/agent/jobs/job_missing",
                headers=_debug_headers(),
            )

            self.assertEqual(401, forbidden.status_code)
            self.assertEqual(404, missing.status_code)


if __name__ == "__main__":
    unittest.main()
