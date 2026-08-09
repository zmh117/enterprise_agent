from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from services.mcp_common import McpAuthenticationError, McpTokenIssuer, McpTokenVerifier
from services.mcp_common.platform_store import PlatformRuntimeStore


KEY = b"platform-store-signing-key-at-least-32-bytes"


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


class FakePlatformQuery:
    def __init__(self) -> None:
        self.revoked = False
        self.job_status = "RUNNING"
        self.job_user = "user-1"
        self.publication_status = "ACTIVE"
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
        binding_payload = {
            "job_id": "job-1",
            "tool_publication_id": "publication-tool-1",
            "server_code": "ones-mcp",
            "tool_name": "ones_work_item_search",
            "required_scope": "ones.work_items.search",
            "tool_schema_hash": "a" * 64,
            "resource_code": "",
            "resource_deployment_id": "",
            "resource_revision_id": "",
            "status": "ELIGIBLE",
            "reason_code": "",
        }
        self.binding = {
            "id": "binding-1",
            **binding_payload,
            "snapshot_hash": _hash(binding_payload),
            "subject_snapshot_id": "snapshot-1",
        }

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
        if "mcp_job_subject_snapshot" in sql:
            return dict(self.snapshot)
        raise AssertionError(sql)

    def execute(self, sql: str, params=()):
        if "mcp_job_tool_binding" in sql:
            return [dict(self.binding)] if self.publication_status == "ACTIVE" else []
        raise AssertionError(sql)


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
    assert authorized.binding.tool_schema_hash == "a" * 64


@pytest.mark.parametrize("attack", ["revoked", "terminal_job", "wrong_subject", "unpublished"])
def test_store_fails_closed_for_runtime_revocation_facts(attack: str) -> None:
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

    with pytest.raises(McpAuthenticationError):
        store.authorize_tool(
            claims=_claims(),
            tool_name="ones_work_item_search",
            required_scope="ones.work_items.search",
            correlation_id="correlation-1",
        )


def test_store_rejects_scope_escalation_before_provider_call() -> None:
    store = PlatformRuntimeStore(FakePlatformQuery(), server_code="ones-mcp")
    with pytest.raises(McpAuthenticationError, match="scope"):
        store.authorize_tool(
            claims=_claims(scopes=["ones.work_items.get"]),
            tool_name="ones_work_item_search",
            required_scope="ones.work_items.search",
            correlation_id="correlation-1",
        )
