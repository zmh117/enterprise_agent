from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.agent.domain.runtime import AgentExecutionContext, AgentRunRequest
from app.modules.agent.infrastructure.claude_code_agent_client import (
    ClaudeSdk,
    RealClaudeCodeAgentClient,
)
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.modules.model_connection.domain import (
    DEFAULT_MODEL_CONNECTION_CODE,
    ModelRuntimeBinding,
)
from app.shared.config import ExecutionSettings, IdentitySettings
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import test_settings as build_settings


ADMIN_ID = "user_local_admin"
AGENT_CODE = "default-diagnostic-agent"


def container():
    settings = replace(
        build_settings(),
        identity=IdentitySettings(
            enabled=True,
            published_agent_runtime_enabled=True,
            cookie_secure=False,
        ),
    )
    value = build_test_container(settings, migrate=True, seed=True)
    value.model_connection_service.dns_resolver = lambda *args, **kwargs: [
        (2, 1, 6, "", ("1.1.1.1", 443))
    ]
    return value


def web_container():
    settings = replace(
        build_settings(),
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            cookie_secure=False,
            allowed_origins=("http://admin.test",),
        ),
    )
    value = build_test_container(settings, migrate=True, seed=True)
    value.model_connection_service.dns_resolver = lambda *args, **kwargs: [
        (2, 1, 6, "", ("1.1.1.1", 443))
    ]
    return settings, value


def deepseek_config(model: str = "deepseek-v4-flash") -> dict[str, str]:
    return {
        "protocol": "anthropic_compatible",
        "base_url": "https://api.deepseek.com/anthropic",
        "model": model,
        "default_opus_model": model,
        "default_sonnet_model": model,
        "default_haiku_model": model,
        "subagent_model": model,
        "effort_level": "max",
    }


def agent_config(connection_revision_id: str) -> dict[str, object]:
    return {
        "business_role": "Enterprise diagnostic specialist",
        "business_instructions": "Use approved read-only evidence.",
        "model_policy": {
            "runtime": "claude_agent_sdk",
            "model": "deepseek-v4-flash",
            "model_connection_revision_id": connection_revision_id,
        },
        "execution": {"max_turns": 10, "timeout_seconds": 240},
        "tools": ["get_er_context"],
        "skills": [],
        "routing": {"project_code": "default"},
        "channels": {
            "ingress": ["connector-dingtalk-stream-default"],
            "delivery": ["connector-dingtalk-enterprise-default"],
        },
    }


def fake_secret(label: str) -> str:
    return hashlib.sha256(f"runtime-generated-test-value:{label}".encode()).hexdigest()


def ready_connection(c):
    connection = c.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)
    return c.model_connection_service.save_revision(
        actor_id=ADMIN_ID,
        code=DEFAULT_MODEL_CONNECTION_CODE,
        expected_revision=connection["revision"],
        config=deepseek_config(),
        api_key=fake_secret("connection-v1"),
    )


def test_model_connection_dns_validation_runs_outside_database_uow() -> None:
    c = container()
    observed: list[bool] = []

    def resolve(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        del args, kwargs
        observed.append(c.database.current_unit_of_work is None)
        return [(2, 1, 6, "", ("1.1.1.1", 443))]

    c.model_connection_service.dns_resolver = resolve
    try:
        ready_connection(c)
        assert observed == [True]
    finally:
        c.database.close()


def test_model_connection_secret_is_encrypted_and_public_projection_is_sanitized() -> None:
    c = container()
    revision = ready_connection(c)

    public_text = json.dumps(
        c.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE),
        ensure_ascii=False,
    )
    assert fake_secret("connection-v1") not in public_text
    assert "api_key_secret_id" not in public_text
    assert "secret://platform/" not in public_text
    assert revision["credential"]["configured"] is True
    assert revision["credential"]["masked"]

    rows = c.database.execute(
        """
        select v.ciphertext, v.nonce
          from platform_secret_version v
          join model_connection_revision r on r.api_key_secret_id = v.secret_id
         where r.id = ?
        """,
        (revision["id"],),
    )
    assert rows
    assert fake_secret("connection-v1") not in rows[0]["ciphertext"]
    assert fake_secret("connection-v1") not in rows[0]["nonce"]


def test_admin_api_manages_only_saved_connection_revisions_and_never_returns_key() -> None:
    settings, c = web_container()
    app = create_app(settings, container_factory=lambda _: c)
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "local-user", "password": "local-admin-change-me"},
        )
        assert login.status_code == 200
        csrf = client.cookies.get("enterprise_agent_csrf")
        assert csrf
        response = client.get(f"/api/admin/model-connections/{DEFAULT_MODEL_CONNECTION_CODE}")
        assert response.status_code == 200
        connection = response.json()["connection"]

        credential = client.put(
            f"/api/admin/model-connections/{DEFAULT_MODEL_CONNECTION_CODE}/credential",
            headers={
                "origin": "http://admin.test",
                "x-csrf-token": csrf,
            },
            json={
                "expected_revision": connection["revision"],
                "api_key": fake_secret("api-only"),
            },
        )
        assert credential.status_code == 200, credential.text
        saved = client.put(
            f"/api/admin/model-connections/{DEFAULT_MODEL_CONNECTION_CODE}/revision",
            headers={
                "origin": "http://admin.test",
                "x-csrf-token": csrf,
            },
            json={
                "expected_revision": credential.json()["revision"]["revision"],
                "config": deepseek_config(),
            },
        )
        rejected_probe = client.post(
            f"/api/admin/model-connections/{DEFAULT_MODEL_CONNECTION_CODE}/test",
            headers={
                "origin": "http://admin.test",
                "x-csrf-token": csrf,
            },
            json={
                "revision_id": saved.json()["revision"]["id"],
                "timeout_seconds": 15,
                "api_key": fake_secret("forbidden-temporary"),
                "base_url": "https://api.deepseek.com/anthropic",
            },
        )
    assert saved.status_code == 200, saved.text
    assert rejected_probe.status_code == 422
    body = saved.text
    assert fake_secret("api-only") not in body
    assert "api_key_secret_id" not in body
    assert "secret://platform/" not in body
    assert saved.json()["revision"]["credential"]["configured"] is True


def test_bootstrap_connection_stays_rotation_required_until_credential_is_rotated() -> None:
    c = container()
    connection = c.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)
    assert connection["current_revision"]["status"] == "rotation_required"
    assert connection["current_revision"]["credential"]["rotation_required"] is True

    config_only = c.model_connection_service.save_revision(
        actor_id=ADMIN_ID,
        code=DEFAULT_MODEL_CONNECTION_CODE,
        expected_revision=connection["revision"],
        config=deepseek_config(),
    )
    assert config_only["status"] == "rotation_required"
    with pytest.raises(NonRetryableExecutionError) as blocked:
        c.model_connection_service.runtime_binding(str(config_only["id"]))
    assert blocked.value.error_code == "model_connection_rotation_required"

    rotated = c.model_connection_service.rotate_credential(
        actor_id=ADMIN_ID,
        code=DEFAULT_MODEL_CONNECTION_CODE,
        expected_revision=config_only["revision"],
        api_key=fake_secret("after-rotation"),
    )
    assert rotated["status"] == "ready"
    assert rotated["credential"]["rotation_required"] is False


def test_model_connection_can_be_reinitialized_after_all_revisions_are_reset() -> None:
    c = container()
    connection = c.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)
    with c.database.unit_of_work():
        c.database.execute(
            """
            update model_connection
               set current_revision_id = null,
                   status = 'rotation_required',
                   revision = 0
             where id = ?
            """,
            (connection["id"],),
        )
        c.database.execute(
            "delete from model_connection_revision where connection_id = ?",
            (connection["id"],),
        )

    recreated = c.model_connection_service.save_revision(
        actor_id=ADMIN_ID,
        code=DEFAULT_MODEL_CONNECTION_CODE,
        expected_revision=0,
        config=deepseek_config(),
    )
    assert recreated["revision"] == 1
    assert recreated["status"] == "rotation_required"
    assert recreated["credential"]["configured"] is False

    rotated = c.model_connection_service.rotate_credential(
        actor_id=ADMIN_ID,
        code=DEFAULT_MODEL_CONNECTION_CODE,
        expected_revision=1,
        api_key=fake_secret("after-full-reset"),
    )
    assert rotated["revision"] == 2
    assert rotated["status"] == "ready"
    assert rotated["credential"]["configured"] is True


def test_agent_publication_pins_connection_and_job_records_safe_provenance() -> None:
    c = container()
    connection_revision = ready_connection(c)
    agent = c.agent_config_service.get(AGENT_CODE)
    draft = c.agent_config_service.save_draft(
        actor_id=ADMIN_ID,
        agent_code=AGENT_CODE,
        expected_revision=int(agent["draft"]["revision"]),
        config=agent_config(str(connection_revision["id"])),
    )
    validated = c.agent_config_service.validate_revision(
        actor_id=ADMIN_ID,
        agent_code=AGENT_CODE,
        revision_id=str(draft["id"]),
    )
    assert validated["validation"]["valid"] is True
    publication = c.agent_config_service.publish(
        actor_id=ADMIN_ID,
        agent_code=AGENT_CODE,
        revision_id=str(draft["id"]),
    )
    assert publication["snapshot"]["model_connection"]["revision_id"] == connection_revision["id"]
    assert "credential" not in publication["snapshot"]["model_connection"]

    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="model-provenance-job",
            requester_id=ADMIN_ID,
            external_conversation_id="model-provenance-conversation",
            external_event_id="model-provenance-event",
            user_message="check current order state",
        )
    )
    assert job.model_runtime_provenance["legacy"] is False
    assert job.model_runtime_provenance["connection_revision_id"] == connection_revision["id"]
    detail = c.agent_repository.get_job_detail(job.id)
    detail_text = json.dumps(detail, ensure_ascii=False)
    assert detail["model_runtime_provenance"]["provider_host"] == "api.deepseek.com"
    assert fake_secret("connection-v1") not in detail_text
    assert "secret://platform/" not in detail_text

    context = c.agent_executor.context_builder.build(job)
    assert context.model_runtime_binding is not None
    assert context.model_runtime_binding.model == "deepseek-v4-flash"
    assert c.model_connection_service.resolve_api_key(context.model_runtime_binding) == fake_secret(
        "connection-v1"
    )


def test_agent_list_degrades_missing_published_model_revision_instead_of_500() -> None:
    settings, c = web_container()
    connection_revision = ready_connection(c)
    agent = c.agent_config_service.get(AGENT_CODE)
    draft = c.agent_config_service.save_draft(
        actor_id=ADMIN_ID,
        agent_code=AGENT_CODE,
        expected_revision=int(agent["draft"]["revision"]),
        config=agent_config(str(connection_revision["id"])),
    )
    c.agent_config_service.publish(
        actor_id=ADMIN_ID,
        agent_code=AGENT_CODE,
        revision_id=str(draft["id"]),
    )
    with c.database.unit_of_work():
        c.database.execute(
            """
            update model_connection
               set current_revision_id = null,
                   status = 'rotation_required',
                   revision = 0
             where id = ?
            """,
            (connection_revision["connection_id"],),
        )
        c.database.execute(
            "delete from model_connection_revision where id = ?",
            (connection_revision["id"],),
        )

    app = create_app(settings, container_factory=lambda _: c)
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "local-user", "password": "local-admin-change-me"},
        )
        assert login.status_code == 200
        response = client.get("/api/admin/agents")

    assert response.status_code == 200, response.text
    summary = next(
        item for item in response.json()["agents"] if item["code"] == AGENT_CODE
    )
    assert summary["model_connection_status"] == "missing_revision"


def test_agent_publication_is_idempotent_and_published_revision_stays_published() -> None:
    c = container()
    connection_revision = ready_connection(c)
    agent = c.agent_config_service.get(AGENT_CODE)
    draft = c.agent_config_service.save_draft(
        actor_id=ADMIN_ID,
        agent_code=AGENT_CODE,
        expected_revision=int(agent["draft"]["revision"]),
        config=agent_config(str(connection_revision["id"])),
    )

    first = c.agent_config_service.publish(
        actor_id=ADMIN_ID,
        agent_code=AGENT_CODE,
        revision_id=str(draft["id"]),
    )
    revalidated = c.agent_config_service.validate_revision(
        actor_id=ADMIN_ID,
        agent_code=AGENT_CODE,
        revision_id=str(draft["id"]),
    )
    c.database.execute(
        "update agent_revision set status = 'validated' where id = ?",
        (draft["id"],),
    )
    second = c.agent_config_service.publish(
        actor_id=ADMIN_ID,
        agent_code=AGENT_CODE,
        revision_id=str(draft["id"]),
    )

    assert revalidated["status"] == "published"
    assert second["id"] == first["id"]
    assert c.agent_config_service.get(AGENT_CODE)["draft"]["status"] == "published"
    assert c.database.execute_one(
        """
        select count(*) as count from agent_publication
        where agent_id = ? and revision_id = ?
        """,
        (agent["definition"]["id"], draft["id"]),
    ) == {"count": 1}


def test_connection_revision_is_immutable_while_credential_rotation_is_active() -> None:
    c = container()
    first = ready_connection(c)
    second = c.model_connection_service.save_revision(
        actor_id=ADMIN_ID,
        code=DEFAULT_MODEL_CONNECTION_CODE,
        expected_revision=first["revision"],
        config=deepseek_config("deepseek-v4-flash"),
        api_key=fake_secret("connection-v2"),
    )
    assert first["id"] != second["id"]
    assert first["config_hash"] == second["config_hash"]
    assert second["credential"]["version"] == first["credential"]["version"] + 1
    binding = c.model_connection_service.runtime_binding(str(first["id"]))
    assert c.model_connection_service.resolve_api_key(binding) == fake_secret("connection-v2")


def test_provider_url_rejects_private_dns_and_unapproved_hosts() -> None:
    c = container()
    connection = c.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)
    c.model_connection_service.dns_resolver = lambda *args, **kwargs: [
        (2, 1, 6, "", ("127.0.0.1", 443))
    ]
    with pytest.raises(NonRetryableExecutionError) as private:
        c.model_connection_service.save_revision(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            expected_revision=connection["revision"],
            config=deepseek_config(),
        )
    assert private.value.error_code == "validation_failed"

    bad = deepseek_config()
    bad["base_url"] = "https://example.com/anthropic"
    with pytest.raises(NonRetryableExecutionError) as host:
        c.model_connection_service.save_revision(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            expected_revision=connection["revision"],
            config=bad,
        )
    assert host.value.error_code == "validation_failed"


@pytest.mark.parametrize(
    "url",
    [
        "http://api.deepseek.com/anthropic",
        "https://user:password@api.deepseek.com/anthropic",
        "https://api.deepseek.com/anthropic#fragment",
        "https://api.deepseek.com/anthropic?redirect=1",
    ],
)
def test_provider_url_rejects_unsafe_url_shapes(url: str) -> None:
    c = container()
    connection = c.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)
    config = deepseek_config()
    config["base_url"] = url
    with pytest.raises(NonRetryableExecutionError) as rejected:
        c.model_connection_service.save_revision(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            expected_revision=connection["revision"],
            config=config,
        )
    assert rejected.value.error_code == "validation_failed"


def test_revision_conflict_hash_integrity_and_disabled_credential_fail_closed() -> None:
    c = container()
    first = ready_connection(c)
    with pytest.raises(NonRetryableExecutionError) as conflict:
        c.model_connection_service.save_revision(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            expected_revision=first["revision"] - 1,
            config=deepseek_config(),
        )
    assert conflict.value.error_code == "revision_conflict"

    binding = c.model_connection_service.runtime_binding(str(first["id"]))
    private_revision = c.model_connection_service.repository.get_revision(str(first["id"]))
    secret = c.model_connection_service.platform_repository.get_platform_secret(
        str(private_revision["api_key_secret_id"])
    )
    c.model_connection_service.secret_provider.disable_secret(
        code=str(secret["code"]),
        actor_id=ADMIN_ID,
    )
    with pytest.raises(NonRetryableExecutionError):
        c.model_connection_service.resolve_api_key(binding)

    c.database.execute(
        "update model_connection_revision set config_hash = ? where id = ?",
        ("tampered", first["id"]),
    )
    with pytest.raises(NonRetryableExecutionError) as integrity:
        c.model_connection_service.public_revision(str(first["id"]))
    assert integrity.value.error_code == "model_connection_integrity_failed"


def test_saved_connection_probe_rejects_redirect_before_invoking_sdk() -> None:
    c = container()
    revision = ready_connection(c)
    invoked = False

    def tester(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal invoked
        del args, kwargs
        invoked = True
        return {"detail": "not expected"}

    def reject_redirect(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise NonRetryableExecutionError(
            "redirect",
            safe_message="Model provider Base URL must not redirect",
            error_code="model_connection_redirect_rejected",
        )

    c.model_connection_service.tester = tester
    c.model_connection_service.redirect_checker = reject_redirect
    with pytest.raises(NonRetryableExecutionError) as rejected:
        c.model_connection_service.test_saved_revision(
            actor_id=ADMIN_ID,
            revision_id=str(revision["id"]),
        )
    assert rejected.value.error_code == "model_connection_redirect_rejected"
    assert invoked is False


def test_concurrent_jobs_do_not_leak_process_environment_between_connections() -> None:
    observations: dict[str, list[tuple[str, str, str]]] = {}

    class Options:
        def __init__(self, **kwargs: Any) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    async def query(prompt: str, options: Options):
        del prompt
        model = options.model
        observations.setdefault(model, []).append(
            (
                os.environ.get("ANTHROPIC_API_KEY", ""),
                os.environ.get("ANTHROPIC_MODEL", ""),
                os.environ.get("CLAUDE_CODE_EFFORT_LEVEL", ""),
            )
        )
        await asyncio.sleep(0.03)
        observations[model].append(
            (
                os.environ.get("ANTHROPIC_API_KEY", ""),
                os.environ.get("ANTHROPIC_MODEL", ""),
                os.environ.get("CLAUDE_CODE_EFFORT_LEVEL", ""),
            )
        )
        yield {"result": f"{model}-done"}

    sdk = ClaudeSdk(
        query=query,
        options=Options,
        tool=lambda *args, **kwargs: None,
        create_sdk_mcp_server=lambda name, tools: {"name": name, "tools": tools},
        tool_annotations=None,
    )
    client = RealClaudeCodeAgentClient(
        model="legacy",
        tool_registry=object(),  # no tools are assigned in this isolation test
        limits=ExecutionSettings(timeout_seconds=5),
        api_key="",
        sdk_loader=lambda: sdk,
        secret_resolver=lambda ref: {
            "secret://platform/one": fake_secret("isolation-one"),
            "secret://platform/two": fake_secret("isolation-two"),
        }[ref],
    )

    def request(binding: ModelRuntimeBinding, job_id: str) -> AgentRunRequest:
        return AgentRunRequest(
            job_id=job_id,
            user_id="user",
            project_code="default",
            context=AgentExecutionContext(
                system_role="test",
                safety_rules=["read only"],
                user_question="ping",
                project_code="default",
                allowed_tools=[],
                tool_restrictions=[],
                skills={},
                retrieved_context={},
                conversation_summary="",
                model=binding.model,
                timeout_seconds=5,
                model_runtime_binding=binding,
            ),
        )

    first = ModelRuntimeBinding(
        protocol="anthropic_compatible",
        base_url="https://api.deepseek.com/anthropic",
        model="model-one",
        default_opus_model="model-one",
        default_sonnet_model="model-one",
        default_haiku_model="model-one",
        subagent_model="model-one",
        effort_level="high",
        secret_ref="secret://platform/one",
    )
    second = replace(
        first,
        model="model-two",
        default_opus_model="model-two",
        default_sonnet_model="model-two",
        default_haiku_model="model-two",
        subagent_model="model-two",
        effort_level="max",
        secret_ref="secret://platform/two",
    )
    errors: list[BaseException] = []

    def run(binding: ModelRuntimeBinding, job_id: str) -> None:
        try:
            client.run(request(binding, job_id))
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=(first, "job-one")),
        threading.Thread(target=run, args=(second, "job-two")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert observations["model-one"] == [
        (fake_secret("isolation-one"), "model-one", "high"),
        (fake_secret("isolation-one"), "model-one", "high"),
    ]
    assert observations["model-two"] == [
        (fake_secret("isolation-two"), "model-two", "max"),
        (fake_secret("isolation-two"), "model-two", "max"),
    ]
