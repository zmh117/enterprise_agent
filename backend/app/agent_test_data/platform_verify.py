from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from app.agent_test_data.manifest import BASE_CODES, TABLES, redis_namespace
from app.modules.internal_api_platform.application.platform_service import PlatformService
from app.modules.internal_api_platform.domain.errors import PlatformError
from app.modules.internal_api_platform.domain.topology import DatabaseEngine, ResourceKind
from app.modules.internal_api_platform.infrastructure.config import load_platform_config
from app.modules.internal_api_platform.infrastructure.db.drivers import (
    MysqlExecutor,
    OracleExecutor,
    SqlServerExecutor,
)
from app.modules.internal_api_platform.infrastructure.db.schema_directory import (
    MySqlSchemaInspector,
    OracleSchemaInspector,
    SchemaInspectorFactory,
    SqlServerSchemaInspector,
)
from app.modules.internal_api_platform.infrastructure.loki_gateway import FakeLokiClient
from app.modules.internal_api_platform.infrastructure.redis_gateway import RealRedisGateway
from app.modules.internal_api_platform.infrastructure.registry import TopologyRegistry


@dataclass(frozen=True)
class PlatformCheckResult:
    name: str
    ok: bool
    message: str


def _build_service() -> PlatformService:
    topology_file = os.getenv(
        "INTERNAL_PLATFORM_TOPOLOGY_FILE",
        "/app/backend/config/internal_platform_topology.example.yaml",
    )
    topology, access = load_platform_config(topology_file)
    return PlatformService(
        registry=TopologyRegistry(topology),
        access_policy=access,
        executors={
            DatabaseEngine.MYSQL: MysqlExecutor(),
            DatabaseEngine.SQLSERVER: SqlServerExecutor(),
            DatabaseEngine.ORACLE: OracleExecutor(),
        },
        schema_inspector_factory=SchemaInspectorFactory(
            {
                DatabaseEngine.MYSQL: MySqlSchemaInspector(),
                DatabaseEngine.SQLSERVER: SqlServerSchemaInspector(),
                DatabaseEngine.ORACLE: OracleSchemaInspector(),
            }
        ),
        redis_gateway=RealRedisGateway(),
        loki_client=FakeLokiClient(),
        max_rows=20,
        query_timeout_seconds=15,
        redis_scan_limit=50,
        config_source="agent-test-data-platform-verify",
    )


def _check_base(service: PlatformService, base: str) -> None:
    user_id = "local-user"
    service.describe_target(
        user_id=user_id,
        environment="agent_test",
        base=base,
        workshop=None,
        kind=ResourceKind.DATABASE,
    )
    schema = service.schema_directory(
        user_id=user_id,
        environment="agent_test",
        base=base,
        workshop=None,
        query="",
        limit=20,
    )
    table_names = {str(table["name"]).lower() for table in schema.summary["tables"]}
    expected = {table.name for table in TABLES}
    if not expected.issubset(table_names):
        raise RuntimeError(f"schema missing tables: {sorted(expected - table_names)}")

    query = service.query_database(
        user_id=user_id,
        environment="agent_test",
        base=base,
        workshop=None,
        sql="SELECT order_no, completed_qty FROM production_order WHERE order_no = 'PO-STUCK-001'",
        limit=5,
    )
    if not query.summary["rows"]:
        raise RuntimeError("stuck order query returned no rows")

    try:
        service.query_database(
            user_id=user_id,
            environment="agent_test",
            base=base,
            workshop=None,
            sql="INSERT INTO production_order (order_no) VALUES ('FORBIDDEN')",
            limit=5,
        )
    except PlatformError:
        pass
    else:
        raise RuntimeError("platform accepted a write SQL statement")

    redis_key = f"{redis_namespace(base)}:equipment:EQ-MIX-01:status"
    redis_value = service.redis_get(
        user_id=user_id,
        environment="agent_test",
        base=base,
        workshop=None,
        key=redis_key,
    )
    if redis_value.summary.get("value_summary") != "ONLINE":
        raise RuntimeError("redis sentinel value mismatch")
    scanned = service.redis_scan(
        user_id=user_id,
        environment="agent_test",
        base=base,
        workshop=None,
        pattern=f"{redis_namespace(base)}:*",
        limit=20,
    )
    keys = scanned.summary.get("keys", [])
    if redis_key not in keys:
        raise RuntimeError("redis scan did not return sentinel key")


def run() -> list[PlatformCheckResult]:
    service = _build_service()
    results: list[PlatformCheckResult] = []
    for base in BASE_CODES:
        try:
            _check_base(service, base)
        except Exception as exc:
            results.append(PlatformCheckResult(base, False, str(exc)))
        else:
            results.append(PlatformCheckResult(base, True, "ok"))
    return results


def main() -> int:
    failed = False
    for result in run():
        status = "ok" if result.ok else "failed"
        print(f"platform-{result.name}: {status} - {result.message}")
        failed = failed or not result.ok
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
