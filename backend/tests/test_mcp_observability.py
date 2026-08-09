from __future__ import annotations

import json
from types import SimpleNamespace

from services.mcp_common.observability import (
    collect_call_metrics,
    collect_data_generation_health,
    safe_observability_failure,
)
from services.mcp_common.provenance import McpProvenanceRecorder


class MetricsQuery:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def execute_one(self, sql: str, params=()):
        self.sql.append(sql)
        assert params == ("data-mcp",)
        return {
            "call_count": 4,
            "duration_ms_total": 100,
            "duration_ms_max": 70,
            "succeeded_count": 2,
            "failed_count": 1,
            "denied_count": 1,
            "correlation_count": 4,
        }

    def execute(self, sql: str, params=()):
        self.sql.append(sql)
        assert params == ("data-mcp",)
        return [
            {"error_code": "provider_timeout", "count": 1},
            {"error_code": "Bearer secret-token", "count": 2},
        ]


def test_metrics_are_bounded_aggregates_without_ids_headers_or_results() -> None:
    query = MetricsQuery()
    metrics = collect_call_metrics(
        query,
        server_code="data-mcp",
        server_version="2.0.0",
    )
    assert metrics["duration_ms_average"] == 25
    assert metrics["errors"] == {"provider_timeout": 1, "other": 2}
    assert metrics["correlation_count"] == 4
    encoded = json.dumps(metrics)
    for forbidden in (
        "secret-token",
        "correlation_id",
        "authorization",
        "request_summary",
        "result_hash",
    ):
        assert forbidden not in encoded.lower()
    assert all("mcp_tool_call" in sql for sql in query.sql)


class HealthQuery:
    def __init__(self, *, deployments: int, active: int, lkg: int) -> None:
        self.row = {
            "deployment_count": deployments,
            "active_count": active,
            "lkg_count": lkg,
        }
        self.sql = ""

    def execute_one(self, sql: str, params=()):
        assert not params
        self.sql = sql
        return self.row


def test_data_health_reports_unconfigured_ready_and_degraded_lkg_without_provider_io() -> None:
    unconfigured_query = HealthQuery(deployments=0, active=0, lkg=0)
    unconfigured = collect_data_generation_health(unconfigured_query, None)
    assert unconfigured["generation_status"] == "unconfigured"

    ready_query = HealthQuery(deployments=2, active=2, lkg=2)
    ready = collect_data_generation_health(ready_query, None)
    assert ready["generation_status"] == "ready"
    assert ready["last_known_good_generation_count"] == 2

    degraded_query = HealthQuery(deployments=2, active=2, lkg=1)
    degraded = collect_data_generation_health(degraded_query, None)
    assert degraded["generation_status"] == "degraded"

    for query in (unconfigured_query, ready_query, degraded_query):
        normalized = query.sql.lower()
        assert "mcp_resource_generation" in normalized
        assert "mysql" not in normalized
        assert "redis" not in normalized
        assert "loki" not in normalized


def test_observability_failure_is_fixed_and_does_not_echo_exception_material() -> None:
    payload = safe_observability_failure(
        server_code="ones-mcp",
        server_version="2.0.0",
    )
    assert payload == {
        "status": "degraded",
        "server_code": "ones-mcp",
        "server_version": "2.0.0",
        "error_code": "platform_observability_unavailable",
        "provider_query_executed": False,
    }


class ProvenanceQuery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, params=()):
        self.calls.append((sql, tuple(params)))
        return []


def test_provenance_boundary_redacts_headers_tokens_and_connection_uris() -> None:
    query = ProvenanceQuery()
    context = SimpleNamespace(
        job=SimpleNamespace(
            job_id="job-1",
            app_user_id="user-1",
            application_publication_id="publication-1",
        ),
        binding=SimpleNamespace(
            tool_name="data_sample_rows",
            tool_schema_hash="a" * 64,
            subject_snapshot_id="snapshot-1",
            resource_deployment_id="deployment-1",
            resource_revision_id="revision-1",
        ),
        principal=SimpleNamespace(correlation_id="correlation-1"),
    )
    McpProvenanceRecorder(query, server_code="data-mcp", server_version="2.0.0").record(
        context=context,
        request_summary={
            "headers": {"Authorization": "Bearer secret-token-value"},
            "diagnostic": "postgresql://db-user:db-password@10.0.0.5/app",
        },
        result_payload={"not_persisted": "Bearer result-token-value"},
        status="SUCCEEDED",
        duration_ms=2,
    )

    provenance = next(params for sql, params in query.calls if "mcp_tool_call_provenance" in sql)
    stored_summary = str(provenance[12])
    assert "[REDACTED]" in stored_summary
    for forbidden in (
        "secret-token-value",
        "db-password",
        "10.0.0.5",
        'authorization"',
    ):
        assert forbidden not in stored_summary.lower()
