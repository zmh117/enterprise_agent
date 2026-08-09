from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from services.mcp_common import McpAuthenticationError, McpTokenIssuer, McpTokenVerifier
from services.mcp_common.platform_store import PlatformRuntimeStore
from services.mcp_common.tool_catalog import get_catalog_entry


KEY = b"platform-store-signing-key-at-least-32-bytes"


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


class FakePlatformQuery:
    def __init__(self, *, server_code: str = "ones-mcp") -> None:
        self.revoked = False
        self.job_status = "RUNNING"
        self.job_user = "user-1"
        self.publication_status = "ACTIVE"
        self.resource_active = True
        self.snapshot = {
            "id": "snapshot-1",
            "job_id": "job-1",
            "app_user_id": "user-1",
            "external_identity_id": "identity-1",
            "external_subject": "ones-user-1",
            "provider_instance_id": "provider-1",
            "default_team_id": "team-1",
            "binding_revision": 3,
        }
        self.snapshot["snapshot_hash"] = _hash(
            {key: value for key, value in self.snapshot.items() if key != "id"}
        )
        catalog_key = (
            "ones-mcp/ones_work_item_search"
            if server_code == "ones-mcp"
            else "data-mcp/data_sample_rows"
        )
        catalog = get_catalog_entry(catalog_key)
        binding_payload = {
            "job_id": "job-1",
            "tool_publication_id": "publication-tool-1",
            "server_code": server_code,
            "tool_name": catalog.tool_name,
            "required_scope": catalog.required_scope,
            "tool_schema_hash": catalog.tool_schema_hash,
            "resource_code": "mes_db" if server_code == "data-mcp" else "",
            "resource_deployment_id": "deployment-1" if server_code == "data-mcp" else "",
            "resource_revision_id": "resource-revision-1" if server_code == "data-mcp" else "",
            "status": "ELIGIBLE",
            "reason_code": "",
        }
        self.binding = {
            "id": "binding-1",
            **binding_payload,
            "snapshot_hash": _hash(binding_payload),
            "subject_snapshot_id": "snapshot-1",
        }
        self.writes: list[tuple[str, tuple[object, ...]]] = []

    def execute_one(self, sql: str, params=()):
        if "mcp_token_revocation" in sql:
            return {"jti": params[0]} if self.revoked else None
        if "from agent_job" in sql:
            return {
                "id": "job-1",
                "status": self.job_status,
                "user_id": self.job_user,
                "internal_user_id": self.job_user,
                "business_application_publication_id": "application-1",
            }
        if "publication_status" in sql:
            return {
                **self.binding,
                "publication_status": (
                    "PUBLISHED" if self.publication_status == "ACTIVE" else "DISABLED"
                ),
                "server_version": "0.1.0",
            }
        if "mcp_job_subject_snapshot" in sql:
            return dict(self.snapshot)
        if "from mcp_resource_deployment" in sql:
            status = "ACTIVE" if self.resource_active else "DISABLED"
            return {
                "status": status,
                "resource_revision_id": "resource-revision-1",
                "current_generation_id": "generation-1",
                "lifecycle_status": "ENABLED",
                "revision_status": "PUBLISHED",
                "generation_status": status,
                "generation_resource_revision_id": "resource-revision-1",
            }
        raise AssertionError(sql)

    def execute(self, sql: str, params=()):
        if "insert into mcp_tool_call" in sql:
            self.writes.append((sql, tuple(params)))
            return []
        if "mcp_job_tool_binding" in sql:
            return [dict(self.binding)] if self.publication_status == "ACTIVE" else []
        raise AssertionError(sql)

    @contextmanager
    def unit_of_work(self):
        yield


def _claims(*, audience: str = "ones-mcp", scopes=None):
    token = McpTokenIssuer(KEY).issue(
        audience=audience,
        app_user_id="user-1",
        job_id="job-1",
        application_publication_id="application-1",
        scopes=scopes or ["ones.work_items.search"],
        job_timeout_seconds=60,
        now=datetime.now(UTC),
    )
    return McpTokenVerifier(KEY, audience=audience).verify(token)


def test_store_rechecks_job_subject_snapshot_and_exact_tool_binding() -> None:
    query = FakePlatformQuery()
    store = PlatformRuntimeStore(query, server_code="ones-mcp")

    authorized = store.authorize_tool(
        claims=_claims(),
        tool_name="ones_work_item_search",
        required_scope="ones.work_items.search",
        correlation_id="correlation-1",
    )

    assert authorized.job.status == "RUNNING"
    assert authorized.job.subject.default_team_id == "team-1"
    assert authorized.binding.binding_id == "binding-1"
    assert (
        authorized.binding.tool_schema_hash
        == get_catalog_entry("ones-mcp/ones_work_item_search").tool_schema_hash
    )


@pytest.mark.parametrize(
    ("attack", "reason_code"),
    [
        ("revoked", "mcp_token_revoked"),
        ("terminal_job", "mcp_job_not_executable"),
        ("wrong_subject", "mcp_subject_denied"),
        ("unpublished", "mcp_tool_publication_revoked"),
    ],
)
def test_store_fails_closed_for_runtime_revocation_facts(
    attack: str,
    reason_code: str,
) -> None:
    query = FakePlatformQuery()
    if attack == "revoked":
        query.revoked = True
    elif attack == "terminal_job":
        query.job_status = "SUCCEEDED"
    elif attack == "wrong_subject":
        query.job_user = "user-2"
    elif attack == "unpublished":
        query.publication_status = "DISABLED"
    store = PlatformRuntimeStore(query, server_code="ones-mcp")

    with pytest.raises(McpAuthenticationError) as denied:
        store.authorize_tool(
            claims=_claims(),
            tool_name="ones_work_item_search",
            required_scope="ones.work_items.search",
            correlation_id="correlation-1",
        )
    assert denied.value.reason_code == reason_code
    attempt = next(params for sql, params in query.writes if "mcp_tool_call_attempt" in sql)
    assert attempt[2] == reason_code


def test_store_rejects_scope_escalation_before_provider_call() -> None:
    query = FakePlatformQuery()
    store = PlatformRuntimeStore(query, server_code="ones-mcp")
    with pytest.raises(McpAuthenticationError, match="scope") as denied:
        store.authorize_tool(
            claims=_claims(scopes=["ones.work_items.get"]),
            tool_name="ones_work_item_search",
            required_scope="ones.work_items.search",
            correlation_id="correlation-1",
        )
    assert denied.value.reason_code == "mcp_scope_denied"
    assert len(query.writes) == 2
    attempt = next(params for sql, params in query.writes if "mcp_tool_call_attempt" in sql)
    assert attempt[2] == "mcp_scope_denied"
    assert "ones.work_items.get" not in json.dumps(query.writes)


def test_store_records_revoked_publication_as_denied_without_request_payload() -> None:
    query = FakePlatformQuery()
    query.publication_status = "DISABLED"
    store = PlatformRuntimeStore(query, server_code="ones-mcp")

    with pytest.raises(McpAuthenticationError) as denied:
        store.authorize_tool(
            claims=_claims(),
            tool_name="ones_work_item_search",
            required_scope="ones.work_items.search",
            correlation_id="correlation-1",
        )

    assert denied.value.reason_code == "mcp_tool_publication_revoked"
    provenance = next(params for sql, params in query.writes if "mcp_tool_call_provenance" in sql)
    assert provenance[6] == "ones_work_item_search"
    assert "{}" not in json.dumps(provenance)


def test_store_records_unavailable_resource_as_denied_before_provider_call() -> None:
    query = FakePlatformQuery(server_code="data-mcp")
    query.resource_active = False
    store = PlatformRuntimeStore(query, server_code="data-mcp")

    with pytest.raises(McpAuthenticationError) as denied:
        store.authorize_tool(
            claims=_claims(
                audience="data-mcp",
                scopes=["data.database.sample"],
            ),
            tool_name="data_sample_rows",
            required_scope="data.database.sample",
            correlation_id="correlation-1",
        )

    assert denied.value.reason_code == "mcp_resource_unavailable"
    attempt = next(params for sql, params in query.writes if "mcp_tool_call_attempt" in sql)
    assert attempt[2] == "mcp_resource_unavailable"
