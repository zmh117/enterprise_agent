from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier
import time

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.agent_config.application.bootstrap import AgentConfigBootstrapper
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import test_settings as make_test_settings
from backend.tests.test_unified_identity_rbac import (
    csrf_headers,
    login,
    unified_settings,
)


def _creation_payload(
    *,
    code: str = "operations-python-agent",
    runtime_kind: str = "python-v1",
) -> dict[str, str]:
    return {
        "code": code,
        "name": "运维 Agent",
        "description": "只读运维诊断",
        "project_code": "default",
        "runtime_kind": runtime_kind,
    }


def test_service_creates_runtime_fixed_definition_and_initial_draft_atomically() -> None:
    runtime = build_test_container(make_test_settings(), migrate=True, seed=True)

    created = runtime.agent_config_service.create_agent(
        actor_id="user_local_admin",
        **_creation_payload(),
    )

    definition = created["definition"]
    draft = created["draft"]
    assert definition["code"] == "operations-python-agent"
    assert definition["runtime_kind"] == "python-v1"
    assert definition["classification"] == "business"
    assert definition["status"] == "enabled"
    assert definition["current_publication_id"] is None
    assert draft["agent_id"] == definition["id"]
    assert draft["revision"] == 1
    assert draft["status"] == "draft"
    assert draft["config"]["routing"] == {"project_code": "default"}
    assert draft["config"]["mcp_tool_ids"] == []
    assert (
        runtime.database.execute_one(
            "select count(*) as count from agent_publication where agent_id = ?",
            (definition["id"],),
        )["count"]
        == 0
    )


def test_duplicate_agent_code_is_a_stable_conflict_without_orphan_rows() -> None:
    runtime = build_test_container(make_test_settings(), migrate=True, seed=True)
    runtime.agent_config_service.create_agent(
        actor_id="user_local_admin",
        **_creation_payload(code="duplicate-agent"),
    )

    with pytest.raises(NonRetryableExecutionError) as rejected:
        runtime.agent_config_service.create_agent(
            actor_id="user_local_admin",
            **_creation_payload(code="duplicate-agent"),
        )

    assert rejected.value.error_code == "agent_code_conflict"
    definition = runtime.agent_config_service.repository.get_definition("duplicate-agent")
    revisions = runtime.database.execute(
        "select id from agent_revision where agent_id = ?",
        (definition["id"],),
    )
    assert len(revisions) == 1


def test_concurrent_agent_code_creation_has_one_winner_and_no_orphan() -> None:
    runtime = build_test_container(make_test_settings(), migrate=True, seed=True)
    barrier = Barrier(2)

    def create(_attempt: int) -> str:
        barrier.wait(timeout=5)
        for _ in range(20):
            try:
                runtime.agent_config_service.create_agent(
                    actor_id="user_local_admin",
                    **_creation_payload(
                        code="concurrent-agent",
                    ),
                )
                return "created"
            except NonRetryableExecutionError as exc:
                return exc.error_code
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                time.sleep(0.01)
        return "sqlite_lock_retry_exhausted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, (1, 2)))

    assert sorted(results) == ["agent_code_conflict", "created"]
    definition = runtime.agent_config_service.repository.get_definition("concurrent-agent")
    assert (
        len(
            runtime.database.execute(
                "select id from agent_revision where agent_id = ?",
                (definition["id"],),
            )
        )
        == 1
    )


def test_builtin_agent_bootstrap_is_idempotent_and_preserves_existing_state() -> None:
    runtime = build_test_container(make_test_settings(), migrate=True, seed=False)
    bootstrapper = AgentConfigBootstrapper(
        runtime.agent_config_service.repository,
        runtime.audit_service,
    )

    first = bootstrapper.ensure_builtin_agents(model="claude-sonnet-4-20250514")
    python = runtime.agent_config_service.repository.get_definition("default-diagnostic-agent")
    runtime.database.execute(
        "update agent_definition set name = '自定义名称' where id = ?",
        (python["id"],),
    )
    second = bootstrapper.ensure_builtin_agents(model="another-model")

    assert first["created"] == ["default-diagnostic-agent"]
    assert python["runtime_kind"] == "python-v1"
    assert second["created"] == []
    assert second["drafts_created"] == []
    assert second["preserved"] == ["default-diagnostic-agent"]
    assert (
        runtime.agent_config_service.repository.get_definition("default-diagnostic-agent")["name"]
        == "自定义名称"
    )
    assert len(runtime.database.execute("select id from agent_definition")) == 1
    assert len(runtime.database.execute("select id from agent_revision")) == 1
    assert runtime.database.execute("select id from agent_publication") == []


def test_builtin_agent_bootstrap_fails_closed_on_runtime_drift() -> None:
    runtime = build_test_container(make_test_settings(), migrate=True, seed=False)
    bootstrapper = AgentConfigBootstrapper(
        runtime.agent_config_service.repository,
        runtime.audit_service,
    )
    bootstrapper.ensure_builtin_agents(model="claude-sonnet-4-20250514")
    runtime.database.execute(
        "update agent_definition set runtime_kind = 'typescript-v1' where code = ?",
        ("default-diagnostic-agent",),
    )

    with pytest.raises(NonRetryableExecutionError) as rejected:
        bootstrapper.ensure_builtin_agents(model="claude-sonnet-4-20250514")

    assert rejected.value.error_code == "agent_runtime_kind_mismatch"


def test_agent_creation_api_reports_permission_and_retires_typescript_runtime() -> None:
    settings = unified_settings()
    runtime = build_test_container(settings, migrate=True, seed=True)
    app = create_app(settings, container_factory=lambda _: runtime)

    with TestClient(app) as client:
        csrf = login(client)
        listed = client.get("/api/admin/agents")
        python = client.post(
            "/api/admin/agents",
            headers=csrf_headers(csrf),
            json=_creation_payload(code="api-python-agent"),
        )
        typescript = client.post(
            "/api/admin/agents",
            headers=csrf_headers(csrf),
            json=_creation_payload(
                code="api-typescript-agent",
                runtime_kind="typescript-v1",
            ),
        )
        typescript_missing = (
            runtime.agent_config_service.repository.find_definition("api-typescript-agent") is None
        )

    assert listed.status_code == 200
    assert listed.json()["permissions"] == {"can_create": True}
    assert python.status_code == 200
    assert typescript.status_code == 400
    assert python.json()["definition"]["runtime_kind"] == "python-v1"
    assert typescript.json()["detail"]["code"] == "typescript_agent_runtime_retired"
    assert python.json()["draft"]["revision"] == 1
    assert typescript_missing


def test_agent_creation_api_rejects_conflict_runtime_and_platform_fields() -> None:
    settings = unified_settings()
    runtime = build_test_container(settings, migrate=True, seed=True)
    app = create_app(settings, container_factory=lambda _: runtime)

    with TestClient(app) as client:
        csrf = login(client)
        headers = csrf_headers(csrf)
        created = client.post(
            "/api/admin/agents",
            headers=headers,
            json=_creation_payload(code="strict-agent"),
        )
        duplicate = client.post(
            "/api/admin/agents",
            headers=headers,
            json=_creation_payload(code="strict-agent"),
        )
        invalid_runtime = client.post(
            "/api/admin/agents",
            headers=headers,
            json=_creation_payload(code="invalid-runtime-agent", runtime_kind="node-v1"),
        )
        forged = client.post(
            "/api/admin/agents",
            headers=headers,
            json={**_creation_payload(code="forged-agent"), "status": "published"},
        )
        invalid_missing = (
            runtime.agent_config_service.repository.find_definition("invalid-runtime-agent") is None
        )
        forged_missing = (
            runtime.agent_config_service.repository.find_definition("forged-agent") is None
        )

    assert created.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "agent_code_conflict"
    assert invalid_runtime.status_code == 422
    assert forged.status_code == 422
    assert invalid_missing
    assert forged_missing


def test_specific_agent_editor_cannot_create_new_agent() -> None:
    settings = unified_settings()
    runtime = build_test_container(settings, migrate=True, seed=True)
    limited = runtime.identity_admin_service.create_user(
        actor_id="user_local_admin",
        username="specific-agent-editor",
        display_name="Specific Agent Editor",
        email="",
        password="specific-agent-editor-password",
    )
    role = runtime.authorization_center_service.create_role(
        actor_id="user_local_admin",
        code="specific-agent-editor-role",
        name="Specific Agent Editor",
        description="",
        purpose_tags=["Agent 管理"],
    )["role"]
    runtime.authorization_center_service.replace_admin_capabilities(
        actor_id="user_local_admin",
        role_id=str(role["id"]),
        expected_revision=1,
        bindings=[
            {"capability_code": "agents.read", "resource_code": "*"},
            {
                "capability_code": "agents.edit",
                "resource_code": "default-diagnostic-agent",
            },
        ],
        confirmed=True,
        reason="验证 Agent 创建需要全局编辑权限",
    )
    runtime.identity_repository.assign_role(
        user_id=str(limited["id"]),
        role_id=str(role["id"]),
        assigned_by="user_local_admin",
    )
    app = create_app(settings, container_factory=lambda _: runtime)

    with TestClient(app) as client:
        csrf = login(
            client,
            "specific-agent-editor",
            "specific-agent-editor-password",
        )
        listed = client.get("/api/admin/agents")
        denied = client.post(
            "/api/admin/agents",
            headers=csrf_headers(csrf),
            json=_creation_payload(code="denied-agent"),
        )
        denied_missing = (
            runtime.agent_config_service.repository.find_definition("denied-agent") is None
        )

    assert listed.status_code == 200
    assert listed.json()["permissions"] == {"can_create": False}
    assert denied.status_code == 403
    assert denied_missing
