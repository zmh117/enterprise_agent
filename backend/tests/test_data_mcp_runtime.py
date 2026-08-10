from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from services.data_mcp_server.contracts import SERVER_CODE, SERVER_VERSION
from services.data_mcp_server.runtime import (
    DatabaseProvider,
    DataResourceResolver,
    DataToolService,
    ResolvedDataCall,
    ResourceRuntime,
)
from services.mcp_common import (
    AuthorizedToolContext,
    JobContext,
    PrincipalContext,
    SubjectSnapshot,
    ToolBindingContext,
)
from services.mcp_common.provenance import McpProvenanceRecorder
from services.mcp_common.secret_crypto import PlatformSecretDecryptor


MASTER_BYTES = b"d" * 32
MASTER_KEY = base64.urlsafe_b64encode(MASTER_BYTES).decode().rstrip("=")
PASSWORD = "database-password-not-for-model"


def _context(*, resource_code="mes_db", revision_id="revision-1"):
    return AuthorizedToolContext(
        principal=PrincipalContext(
            app_user_id="user-1",
            job_id="job-1",
            application_publication_id="application-1",
            audience="data-mcp",
            scopes=("data.schema.read", "data.database.sample"),
            token_id="jti-1",
            correlation_id="correlation-1",
        ),
        job=JobContext(
            job_id="job-1",
            app_user_id="user-1",
            application_publication_id="application-1",
            status="RUNNING",
            subject=SubjectSnapshot(),
        ),
        binding=ToolBindingContext(
            binding_id="binding-1",
            subject_snapshot_id="snapshot-1",
            server_code="data-mcp",
            tool_name="data_schema_directory",
            required_scope="data.schema.read",
            tool_schema_hash="b" * 64,
            resource_code=resource_code,
            resource_deployment_id="deployment-1",
            resource_revision_id=revision_id,
        ),
    )


def _manifest(kind="DATABASE"):
    if kind == "DATABASE":
        spec = {
            "provider": "mysql",
            "host": "mysql.internal",
            "port": 3306,
            "database": "mes",
            "username": "readonly",
            "password_ref": "secret://platform/mes_password",
            "allowed_tables": ["work_order"],
            "max_rows": 25,
            "timeout_seconds": 5,
        }
    elif kind == "REDIS":
        spec = {
            "host": "redis.internal",
            "port": 6379,
            "database": 0,
            "key_prefixes": ["mes:order:"],
            "scan_limit": 20,
            "timeout_seconds": 5,
        }
    else:
        spec = {
            "base_url": "https://loki.internal",
            "label_scope": {"cluster": "prod"},
            "max_minutes": 60,
            "max_lines": 100,
            "timeout_seconds": 5,
        }
    return {
        "api_version": "enterprise-agent/v1",
        "kind": kind,
        "metadata": {"code": "mes_db", "name": "MES"},
        "spec": spec,
    }


class FakeQuery:
    def __init__(self):
        manifest = _manifest()
        canonical = json.dumps(manifest, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        self.resource_row = {
            "code": "mes_db",
            "kind": "DATABASE",
            "lifecycle_status": "ENABLED",
            "revision_id": "revision-1",
            "manifest_json": canonical,
            "content_hash": hashlib.sha256(canonical.encode()).hexdigest(),
            "revision_status": "PUBLISHED",
            "deployment_id": "deployment-1",
            "deployment_status": "ACTIVE",
            "current_generation_id": "generation-1",
            "generation_id": "generation-1",
            "generation_status": "ACTIVE",
            "generation_revision_id": "revision-1",
        }
        secret_id = "secret-1"
        version = 1
        nonce = os.urandom(12)
        encrypted = AESGCM(MASTER_BYTES).encrypt(
            nonce,
            PASSWORD.encode(),
            f"platform-secret|v1|{secret_id}|{version}".encode(),
        )
        self.secret_rows = [
            {
                "id": secret_id,
                "ref": "secret://platform/mes_password",
                "secret_status": "enabled",
                "secret_version": version,
                "ciphertext": base64.urlsafe_b64encode(encrypted).decode().rstrip("="),
                "nonce": base64.urlsafe_b64encode(nonce).decode().rstrip("="),
                "algorithm": "AES-256-GCM-AAD-V1",
                "status": "active",
            }
        ]
        self.resource_row["secret_versions_hash"] = hashlib.sha256(
            json.dumps({secret_id: version}, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def execute_one(self, sql, params=()):
        if "mcp_resource_deployment" in sql:
            return dict(self.resource_row) if self.resource_row is not None else None
        raise AssertionError(sql)

    def execute(self, sql, params=()):
        if "mcp_resource_generation_secret_version" in sql:
            return [dict(item) for item in self.secret_rows]
        self.executed.append((sql, tuple(params)))
        return []


class FakeProvider:
    async def schema_directory(self, query, limit):
        return [{"name": "work_order", "comment": "untrusted comment"}], False

    async def describe_table(self, table):
        return [{"name": "status", "data_type": "varchar", "nullable": False, "comment": ""}]

    async def sample_rows(self, table, columns, filters, limit):
        return ["status"], [{"status": "FAILED", "payload": "x" * 2000}], False

    async def redis_get(self, key):
        return True, "value"

    async def redis_scan_prefix(self, prefix, limit):
        return [prefix + "1"], False

    async def loki_search(self, service, keyword, minutes, limit):
        return [{"timestamp": "1", "labels": {"service": service}, "line": "log"}], False


def test_resource_resolver_pins_generation_and_decrypts_secret_only_for_provider() -> None:
    query = FakeQuery()
    captured: dict[str, Any] = {}

    def factory(resource):
        captured["password"] = resource.secrets["secret://platform/mes_password"]
        return FakeProvider()

    resolved = DataResourceResolver(
        SimpleNamespace(query=query),
        PlatformSecretDecryptor(MASTER_KEY),
        provider_factory=factory,
    ).resolve(_context())

    assert resolved.resource.revision_id == "revision-1"
    assert resolved.resource.generation_id == "generation-1"
    assert captured["password"] == PASSWORD
    assert PASSWORD not in json.dumps(query.executed, default=str)


def test_resource_resolver_accepts_superseded_secret_pinned_by_frozen_generation() -> None:
    query = FakeQuery()
    query.secret_rows[0]["status"] = "superseded"

    resolved = DataResourceResolver(
        SimpleNamespace(query=query),
        PlatformSecretDecryptor(MASTER_KEY),
        provider_factory=lambda resource: FakeProvider(),
    ).resolve(_context())

    assert resolved.resource.secrets["secret://platform/mes_password"] == PASSWORD


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("unconfigured", "unavailable"),
        ("unpublished", "unavailable"),
        ("wrong_revision", "unavailable"),
        ("invalid_secret", "Secret is unavailable"),
    ],
)
def test_resource_resolver_fails_closed_for_unavailable_runtime_facts(
    mutation: str,
    expected: str,
) -> None:
    query = FakeQuery()
    if mutation == "unconfigured":
        query.resource_row = None
    elif mutation == "unpublished":
        query.resource_row["deployment_status"] = "DISABLED"
    elif mutation == "wrong_revision":
        query.resource_row["generation_revision_id"] = "revision-other"
    else:
        query.secret_rows[0]["secret_status"] = "disabled"

    with pytest.raises(Exception, match=expected):
        DataResourceResolver(
            SimpleNamespace(query=query),
            PlatformSecretDecryptor(MASTER_KEY),
            provider_factory=lambda resource: FakeProvider(),
        ).resolve(_context())


def _resolved(kind="DATABASE"):
    resource = ResourceRuntime(
        code="mes_db",
        kind=kind,
        revision_id="revision-1",
        deployment_id="deployment-1",
        generation_id="generation-1",
        manifest=_manifest(kind),
        secrets={},
    )
    return ResolvedDataCall(
        authorized=_context(),
        resource=resource,
        provider=FakeProvider(),
    )


def _service(query):
    return DataToolService(
        resolver=SimpleNamespace(),
        recorder=McpProvenanceRecorder(
            query, server_code=SERVER_CODE, server_version=SERVER_VERSION
        ),
    )


def test_database_tools_are_bounded_and_never_accept_sql() -> None:
    query = FakeQuery()
    service = _service(query)
    resolved = _resolved()
    schema = asyncio.run(service.schema_directory(resolved, query="work", limit=10))
    rows = asyncio.run(
        service.sample_rows(
            resolved,
            table="work_order",
            columns=["status"],
            filters={"status": "FAILED"},
            limit=100,
        )
    )
    assert schema.untrusted_data is True
    assert len(rows.rows) == 1
    assert len(rows.rows[0]["payload"]) == 1000
    assert all("select " not in json.dumps(params).lower() for _, params in query.executed)

    with pytest.raises(Exception, match="outside"):
        asyncio.run(service.describe_table(resolved, table="secret_table"))


def test_database_provider_accepts_uppercase_information_schema_mapping_keys() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.sql = ""

        def execute(self, sql, params=()) -> None:
            del params
            self.sql = sql

        def fetchall(self):
            if "information_schema.columns" in self.sql:
                return [
                    {
                        "COLUMN_NAME": "order_no",
                        "DATA_TYPE": "varchar",
                        "IS_NULLABLE": "NO",
                    }
                ]
            return [{"order_no": "PO-001"}]

    class Connection:
        def __init__(self) -> None:
            self.cursor_value = Cursor()

        def cursor(self):
            return self.cursor_value

        def close(self) -> None:
            return None

    resource = ResourceRuntime(
        code="mes_db",
        kind="DATABASE",
        revision_id="revision-1",
        deployment_id="deployment-1",
        generation_id="generation-1",
        manifest=_manifest(),
        secrets={},
    )
    provider = DatabaseProvider(resource)
    provider._connect = Connection  # type: ignore[method-assign]

    columns, rows, truncated = provider._sample_rows(
        "work_order", [], {}, 5
    )

    assert columns == ["order_no"]
    assert rows == [{"order_no": "PO-001"}]
    assert truncated is False


def test_redis_prefix_and_loki_limits_are_server_enforced() -> None:
    query = FakeQuery()
    service = _service(query)
    redis = _resolved("REDIS")
    loki = _resolved("LOKI")

    with pytest.raises(Exception, match="prefix"):
        asyncio.run(service.redis_scan_prefix(redis, prefix="other:", limit=10))
    keys = asyncio.run(service.redis_scan_prefix(redis, prefix="mes:order:", limit=500))
    logs = asyncio.run(
        service.loki_search(
            loki,
            service="orders",
            keyword="error",
            minutes=500,
            limit=500,
        )
    )
    assert keys.keys == ("mes:order:1",)
    assert logs.lines[0].line == "log"
    summaries = [
        json.loads(params[12])
        for sql, params in query.executed
        if "mcp_tool_call_provenance" in sql
    ]
    assert summaries[-1]["minutes"] == 60
    assert summaries[-1]["limit"] == 100


def test_tool_results_redact_auth_headers_connection_uris_and_sensitive_fields() -> None:
    class SensitiveProvider(FakeProvider):
        async def sample_rows(self, table, columns, filters, limit):
            del table, columns, filters, limit
            return (
                ["authorization", "diagnostic"],
                [
                    {
                        "authorization": "Bearer provider-secret-value",
                        "diagnostic": "postgresql://db-user:db-pass@10.0.0.8/app",
                    }
                ],
                False,
            )

    query = FakeQuery()
    resolved = _resolved()
    resolved = ResolvedDataCall(
        authorized=resolved.authorized,
        resource=resolved.resource,
        provider=SensitiveProvider(),
    )
    result = asyncio.run(
        _service(query).sample_rows(
            resolved,
            table="work_order",
            columns=[],
            filters={},
            limit=10,
        )
    )
    encoded = json.dumps(result.model_dump())
    assert "[REDACTED]" in encoded
    for forbidden in (
        "provider-secret-value",
        "db-pass",
        "10.0.0.8",
        "postgresql://",
    ):
        assert forbidden not in encoded
