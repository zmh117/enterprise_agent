from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.shared.config import Settings
from app.shared.feature_configuration import feature_configuration_from_values
from backend.tests.helpers import (
    prepare_debug_application_access,
    publish_pending_agent_jobs,
    test_settings as make_test_settings,
)

ADMIN_ID = "user_local_admin"


def _settings() -> Settings:
    settings = make_test_settings()
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


def _admin_headers() -> dict[str, str]:
    return {"x-admin-user-id": "admin"}


def _container():
    return build_test_container(_settings(), migrate=True, seed=True)


def _selection_payload(selection: dict[str, str]) -> dict[str, str]:
    return {
        "application_id": selection["application_id"],
        "execution_scope_id": selection["execution_scope_id"],
    }


def test_debug_create_requires_login_and_does_not_create_job() -> None:
    runtime = _container()
    with TestClient(create_app(_settings(), container_factory=lambda _: runtime)) as client:
        response = client.post(
            "/api/agent/jobs",
            json={
                "message": "必须先登录",
                "application_id": "business_app_unknown",
                "execution_scope_id": "debug_scope_unknown",
            },
        )

        assert response.status_code == 401
        assert runtime.agent_repository.count_rows("agent_job") == 0


def test_debug_create_uses_authenticated_internal_user() -> None:
    runtime = _container()
    selection = prepare_debug_application_access(
        runtime,
        application_code="debug-secure-application",
        role_code="debug-secure-role",
    )
    with TestClient(create_app(_settings(), container_factory=lambda _: runtime)) as client:
        first = client.post(
            "/api/agent/jobs",
            headers=_admin_headers(),
            json={
                "message": "检查服务端身份",
                "idempotency_key": "secure-identity",
                **_selection_payload(selection),
            },
        )
        second = client.post(
            "/api/agent/jobs",
            headers=_admin_headers(),
            json={
                "message": "检查服务端身份",
                "idempotency_key": "secure-identity",
                **_selection_payload(selection),
            },
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["job_id"] == second.json()["job_id"]
        assert runtime.agent_repository.count_rows("agent_session") == 1
        assert runtime.agent_repository.count_rows("agent_job") == 1
        assert runtime.agent_repository.count_rows("agent_message") == 1
        assert runtime.message_bus is not None
        assert not runtime.message_bus.jobs
        publish_pending_agent_jobs(runtime)
        assert len(runtime.message_bus.jobs) == 1
        job = runtime.agent_repository.get_job(first.json()["job_id"])
        assert job.user_id == "user_local_admin"
        assert job.requester_id == "user_local_admin"
        assert job.source_connector_id == "connector-debug-api"
        assert job.reply_route["type"] == "none"
        assert job.business_application_id == selection["application_id"]
        assert job.business_application_publication_id == selection["publication_id"]
        assert job.routing_context == {
            "project_code": "default",
            "environment": "local",
            "base": "debug-base",
            "workshop": "",
            "service": "",
            "execution_scope_id": selection["execution_scope_id"],
            "environment_id": selection["environment_id"],
            "base_id": selection["base_id"],
            "workshop_id": "",
        }
        assert job.business_application_route_decision["legacy_fallback"] is False
        assert (
            job.business_application_route_decision["authorization_snapshot"]["reason"]
            == "application_role_allow"
        )
        session = runtime.agent_repository.get_session(job.session_id)
        assert session.session_policy["continuous_conversation_enabled"] is False
        assert session.application_publication_id == selection["publication_id"]
        assert len(session.execution_scope_hash) == 64
        assert session.isolation_key_version == 2
        assert job.business_application_route_decision["idempotency_context"] == {
            "user_id": "user_local_admin",
            "publication_id": selection["publication_id"],
            "execution_scope_id": selection["execution_scope_id"],
        }
        assert job.business_application_route_decision["delivery_binding"] == {
            "binding_id": "",
            "type": "none",
            "connector_id": "",
        }
        independent = client.post(
            "/api/agent/jobs",
            headers=_admin_headers(),
            json={
                "message": "另一次独立调试",
                "idempotency_key": "secure-identity-independent",
                **_selection_payload(selection),
            },
        )
        assert independent.status_code == 200
        independent_job = runtime.agent_repository.get_job(independent.json()["job_id"])
        assert independent_job.session_id != job.session_id
        continued = client.post(
            "/api/agent/jobs",
            headers=_admin_headers(),
            json={
                "message": "显式继续原调试会话",
                "idempotency_key": "secure-identity-continued",
                "continue_session_id": job.session_id,
                **_selection_payload(selection),
            },
        )
        assert continued.status_code == 200
        continued_job = runtime.agent_repository.get_job(continued.json()["job_id"])
        assert continued_job.session_id == job.session_id

        runtime.database.execute(
            "update agent_session set execution_scope_hash = ? where id = ?",
            ("changed-scope", job.session_id),
        )
        before_denied = runtime.agent_repository.count_rows("agent_job")
        denied = client.post(
            "/api/agent/jobs",
            headers=_admin_headers(),
            json={
                "message": "范围变化后不得继续",
                "idempotency_key": "secure-identity-denied-continue",
                "continue_session_id": job.session_id,
                **_selection_payload(selection),
            },
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == ("无法继续该调试会话，请使用当前应用和数据范围创建新会话")
        assert runtime.agent_repository.count_rows("agent_job") == before_denied


def test_debug_create_requires_agent_debug_execute_capability() -> None:
    runtime = _container()
    runtime.identity_repository.create_user(
        username="debug-no-capability",
        display_name="无调试能力",
    )
    with TestClient(create_app(_settings(), container_factory=lambda _: runtime)) as client:
        response = client.post(
            "/api/agent/jobs",
            headers={"x-admin-user-id": "debug-no-capability"},
            json={
                "message": "不应创建",
                "application_id": "business_app_unknown",
                "execution_scope_id": "debug_scope_unknown",
            },
        )

        assert response.status_code == 403
        assert runtime.agent_repository.count_rows("agent_job") == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", "another-user"),
        ("agent_code", "arbitrary-agent"),
        ("agent_publication_id", "agent-publication-other"),
        ("resource_id", "resource-other"),
        ("resources", ["resource-other"]),
        ("connector_id", "connector-other"),
        ("delivery", {"type": "webhook"}),
        ("reply_route", {"type": "webhook"}),
        ("routing", {"environment": "other"}),
        ("project_code", "other"),
        ("conversation_id", "caller-controlled-session"),
    ],
)
def test_debug_create_rejects_authority_expanding_fields(
    field: str,
    value: object,
) -> None:
    runtime = _container()
    selection = prepare_debug_application_access(
        runtime,
        application_code="debug-reject-fields-application",
        role_code="debug-reject-fields-role",
    )
    with TestClient(create_app(_settings(), container_factory=lambda _: runtime)) as client:
        response = client.post(
            "/api/agent/jobs",
            headers=_admin_headers(),
            json={
                "message": "字段必须拒绝",
                **_selection_payload(selection),
                field: value,
            },
        )

        assert response.status_code == 422
        assert runtime.agent_repository.count_rows("agent_job") == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("application_id", "business_app_not_authorized"),
        ("execution_scope_id", "debug_scope_not_authorized"),
        ("delivery_binding_id", "delivery_binding_not_authorized"),
    ],
)
def test_debug_create_rejects_unavailable_selection_without_side_effects(
    field: str,
    value: str,
) -> None:
    runtime = _container()
    selection = prepare_debug_application_access(
        runtime,
        application_code="debug-denied-selection-application",
        role_code="debug-denied-selection-role",
    )
    payload = {
        "message": "不得扩大选择范围",
        **_selection_payload(selection),
        field: value,
    }
    before = {
        table: runtime.agent_repository.count_rows(table)
        for table in ("agent_session", "agent_job", "agent_message")
    }
    with TestClient(create_app(_settings(), container_factory=lambda _: runtime)) as client:
        response = client.post(
            "/api/agent/jobs",
            headers=_admin_headers(),
            json=payload,
        )
        after = {table: runtime.agent_repository.count_rows(table) for table in before}

    assert response.status_code == 403
    assert response.json() == {"detail": "无权使用所选业务应用、执行范围或投递方式"}
    assert after == before
    assert runtime.message_bus is not None
    assert not runtime.message_bus.jobs


def test_debug_create_pins_existing_authorized_delivery_binding() -> None:
    runtime = _container()
    selection = prepare_debug_application_access(
        runtime,
        application_code="debug-delivery-application",
        role_code="debug-delivery-role",
        additional_deliveries=(
            {
                "delivery_type": "dingtalk_group",
                "connector_id": "connector-dingtalk-enterprise-default",
                "enabled": True,
                "config": {
                    "target_reference": "debug-open-conversation",
                    "reply_mode": "markdown",
                },
            },
        ),
    )
    assert selection["delivery_binding_id"]
    options = runtime.debug_job_access_service.available_options(
        user_id=ADMIN_ID,
        environment="local",
    )
    binding_option = options["applications"][0]["delivery_bindings"][0]
    assert set(binding_option) == {
        "binding_id",
        "binding_order",
        "delivery_type",
        "connector_id",
    }
    with TestClient(create_app(_settings(), container_factory=lambda _: runtime)) as client:
        response = client.post(
            "/api/agent/jobs",
            headers=_admin_headers(),
            json={
                "message": "固化现有投递绑定",
                **_selection_payload(selection),
                "delivery_binding_id": selection["delivery_binding_id"],
            },
        )
        job = runtime.agent_repository.get_job(str(response.json()["job_id"]))

    assert response.status_code == 200
    assert job.reply_route == {
        "type": "dingtalk_enterprise_robot",
        "connector_id": "connector-dingtalk-enterprise-default",
        "target": {"open_conversation_id": "debug-open-conversation"},
        "options": {
            "business_application_delivery_binding_id": (selection["delivery_binding_id"]),
            "business_application_delivery_type": "dingtalk_group",
        },
    }
    assert job.business_application_route_decision["delivery_binding"] == {
        "binding_id": selection["delivery_binding_id"],
        "type": "dingtalk_enterprise_robot",
        "connector_id": "connector-dingtalk-enterprise-default",
    }


def test_debug_create_rechecks_active_publication_before_writing() -> None:
    runtime = _container()
    selection = prepare_debug_application_access(
        runtime,
        application_code="debug-inactive-application",
        role_code="debug-inactive-role",
    )
    runtime.database.execute(
        """
        update business_application_deployment
           set active = 0
         where application_id = ? and publication_id = ?
        """,
        (selection["application_id"], selection["publication_id"]),
    )
    with TestClient(create_app(_settings(), container_factory=lambda _: runtime)) as client:
        response = client.post(
            "/api/agent/jobs",
            headers=_admin_headers(),
            json={
                "message": "停用发布不得创建",
                **_selection_payload(selection),
            },
        )
        job_count = runtime.agent_repository.count_rows("agent_job")

    assert response.status_code == 403
    assert job_count == 0


def test_debug_create_requires_current_business_application_access() -> None:
    runtime = _container()
    selection = prepare_debug_application_access(
        runtime,
        application_code="debug-strict-application",
        role_code="debug-strict-admin-role",
    )
    user = runtime.identity_repository.create_user(
        username="debug-legacy-only",
        display_name="仅旧授权用户",
    )
    role = runtime.authorization_center_service.create_role(
        actor_id=ADMIN_ID,
        code="debug-legacy-only-role",
        name="仅旧授权调试角色",
        description="",
        purpose_tags=["业务诊断"],
    )["role"]
    runtime.authorization_center_service.replace_admin_capabilities(
        actor_id=ADMIN_ID,
        role_id=str(role["id"]),
        expected_revision=1,
        bindings=[
            {
                "capability_code": "agent.debug.execute",
                "resource_code": "*",
            }
        ],
        confirmed=True,
        reason="严格授权回归测试",
    )
    runtime.identity_repository.assign_role(
        user_id=str(user["id"]),
        role_id=str(role["id"]),
        assigned_by=ADMIN_ID,
    )
    with TestClient(create_app(_settings(), container_factory=lambda _: runtime)) as client:
        response = client.post(
            "/api/agent/jobs",
            headers={"x-admin-user-id": "debug-legacy-only"},
            json={
                "message": "缺少应用访问不得放行",
                **_selection_payload(selection),
            },
        )
        job_count = runtime.agent_repository.count_rows("agent_job")

    assert response.status_code == 403
    assert job_count == 0
