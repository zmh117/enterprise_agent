from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.modules.internal_api_platform.app import create_app
from app.modules.internal_api_platform.application.platform_service import PlatformService
from app.modules.internal_api_platform.domain.access import AccessPolicy
from app.modules.internal_api_platform.domain.topology import (
    Base,
    DatabaseConnection,
    DatabaseEngine,
    Environment,
    Topology,
)
from app.modules.internal_api_platform.infrastructure.db.executor import FakeQueryExecutor
from app.modules.internal_api_platform.infrastructure.db.schema_directory import (
    FakeSchemaInspector,
    SchemaInspectorFactory,
)
from app.modules.internal_api_platform.domain.schema_directory import (
    SchemaColumn,
    SchemaTable,
)
from app.modules.internal_api_platform.infrastructure.job_authorization import (
    BusinessApplicationJobAccessAuthorizer,
)
from app.modules.internal_api_platform.infrastructure.loki_gateway import FakeLokiClient
from app.modules.internal_api_platform.infrastructure.redis_gateway import FakeRedisGateway
from app.modules.internal_api_platform.infrastructure.registry import TopologyRegistry
from app.modules.job.domain.job_status import JobStatus
from app.shared.config import Settings
from backend.tests.helpers import container, prepare_debug_application_access


SERVICE_TOKEN = "job-fact-integration-token-0000000001"


def _database_base(code: str) -> Base:
    return Base(
        code=code,
        engine=DatabaseEngine.MYSQL,
        database=DatabaseConnection(
            host=f"{code}.database.test",
            port=3306,
            database="diagnostic",
            user="readonly",
            password="not-used-by-fake",
        ),
    )


def _headers(
    *,
    job_id: str,
    user_id: str = "user_local_admin",
    project_code: str = "default",
    application_id: str = "",
) -> dict[str, str]:
    headers = {
        "authorization": f"Bearer {SERVICE_TOKEN}",
        "x-agent-job-id": job_id,
        "x-agent-user-id": user_id,
        "x-agent-project-code": project_code,
    }
    if application_id:
        headers["x-agent-application-id"] = application_id
    return headers


def _query(
    client: TestClient,
    *,
    headers: dict[str, str],
    base: str = "debug-base",
):
    return client.post(
        "/tools/database/query",
        headers=headers,
        json={
            "environment": "local",
            "base": base,
            "sql": "select result from diagnostic_result",
        },
    )


def test_internal_api_requires_token_and_authoritative_job_facts(
    tmp_path: Path,
) -> None:
    runtime = container()
    selection = prepare_debug_application_access(
        runtime,
        application_code="job-fact-integration",
        role_code="job-fact-integration-role",
        capabilities=("query_database",),
    )
    timestamp = datetime.now(UTC).isoformat()
    runtime.database.execute(
        """
        insert into platform_resource_binding
          (id, code, scope_type, environment_id, base_id, resource_kind,
           engine, config_json, secret_refs_json, status, revision,
           created_at, updated_at)
        values ('resource-job-fact-database', 'database.debug-base', 'base',
                ?, ?, 'database', 'mysql', '{}', '{}', 'enabled', 1, ?, ?)
        """,
        (
            selection["environment_id"],
            selection["base_id"],
            timestamp,
            timestamp,
        ),
    )
    job, _ = runtime.debug_job_access_service.create_job(
        user_id="user_local_admin",
        display_name="本地管理员",
        message="验证 Job 事实授权",
        application_id=selection["application_id"],
        execution_scope_id=selection["execution_scope_id"],
        idempotency_key="job-fact-integration",
        correlation_id="correlation-job-fact-integration",
    )
    assert job.status is JobStatus.PENDING

    token_path = tmp_path / "internal-api-token.json"
    token_path.write_text(
        json.dumps({"current": SERVICE_TOKEN}),
        encoding="utf-8",
    )
    executor = FakeQueryExecutor(rows=[{"result": 1}])
    topology = Topology(
        environments={
            "local": Environment(
                code="local",
                bases={
                    "debug-base": _database_base("debug-base"),
                    "other-base": _database_base("other-base"),
                },
            )
        }
    )
    service = PlatformService(
        registry=TopologyRegistry(topology),
        access_policy=AccessPolicy(),
        executors={DatabaseEngine.MYSQL: executor},
        schema_inspector_factory=SchemaInspectorFactory(
            {
                DatabaseEngine.MYSQL: FakeSchemaInspector(
                    tables=[
                        SchemaTable(
                            name="diagnostic_result",
                            columns=[
                                SchemaColumn(
                                    name="result",
                                    data_type="integer",
                                    nullable=False,
                                )
                            ],
                        )
                    ]
                )
            }
        ),
        redis_gateway=FakeRedisGateway(),
        loki_client=FakeLokiClient(),
        job_access_authorizer=BusinessApplicationJobAccessAuthorizer(
            runtime.database
        ),
    )
    app = create_app(
        Settings(
            environment="test",
            internal_api_auth_token_file=str(token_path),
        ),
        service=service,
    )

    with TestClient(app) as client:
        no_token = _query(
            client,
            headers={
                key: value
                for key, value in _headers(job_id=job.id).items()
                if key != "authorization"
            },
        )
        unknown_job = _query(client, headers=_headers(job_id="job-unknown"))
        non_running = _query(client, headers=_headers(job_id=job.id))

        runtime.database.execute(
            "update agent_job set status = 'RUNNING' where id = ?",
            (job.id,),
        )
        forged_user = _query(
            client,
            headers=_headers(job_id=job.id, user_id="user-forged"),
        )
        forged_project = _query(
            client,
            headers=_headers(job_id=job.id, project_code="project-forged"),
        )
        forged_application = _query(
            client,
            headers=_headers(
                job_id=job.id,
                application_id="business-application-forged",
            ),
        )
        forged_scope_headers = {
            **_headers(job_id=job.id),
            "x-agent-environment": "local",
            "x-agent-base": "other-base",
        }
        forged_scope = _query(
            client,
            headers=forged_scope_headers,
        )
        unauthorized_resource = _query(
            client,
            headers=_headers(job_id=job.id),
            base="other-base",
        )

        assert executor.calls == []
        valid = _query(
            client,
            headers=_headers(
                job_id=job.id,
                application_id=selection["application_id"],
            ),
        )

    assert no_token.status_code == 401
    for denied in (
        unknown_job,
        non_running,
        forged_user,
        forged_project,
        forged_application,
        forged_scope,
        unauthorized_resource,
    ):
        assert denied.status_code == 403
        assert denied.json()["detail"]["error"]["code"] == "access_denied"
    assert valid.status_code == 200, valid.text
    assert valid.json()["summary"]["rows"] == [{"result": 1}]
    assert len(executor.calls) == 1
