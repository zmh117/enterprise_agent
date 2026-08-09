from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from dataclasses import replace
from typing import Any

import pytest
from app.bootstrap import (
    _ensure_default_model_connection_for_service,
    _runtime_model_probe_for_service,
    build_test_container,
)
from app.modules.agent.domain.runtime import AgentExecutionContext, AgentRunRequest
from app.modules.agent.infrastructure.claude_code_agent_client import (
    ClaudeSdk,
    RealClaudeCodeAgentClient,
)
from app.modules.model_connection.domain import (
    DEFAULT_MODEL_CONNECTION_CODE,
    ModelRuntimeBinding,
)
from app.shared.config import AgentRuntimeSettings, ExecutionSettings, IdentitySettings
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
    # Model connection writes no longer have a web/admin route after the MCP
    # cutover.  These tests exercise the retained internal runtime service, so
    # isolate them from the retired management capability catalog.
    value.model_connection_service.authorization = _InternalServiceAuthorization()
    value.model_connection_service.dns_resolver = lambda *args, **kwargs: [
        (2, 1, 6, "", ("1.1.1.1", 443))
    ]
    return value


class _InternalServiceAuthorization:
    @staticmethod
    def require(**_: object) -> None:
        return None


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


def fake_secret(label: str) -> str:
    return hashlib.sha256(f"runtime-generated-test-value:{label}".encode()).hexdigest()


def test_model_probe_token_is_required_only_by_api_control_plane() -> None:
    settings = replace(
        build_settings(),
        agent_runtime=AgentRuntimeSettings(
            base_url="http://agent-runtime:8090",
            allowed_hosts=("agent-runtime",),
            model_probe_auth_token_file="/run/secrets/missing-model-probe-token",
            allow_insecure_internal_http=True,
        ),
    )

    assert _runtime_model_probe_for_service(settings, "agent-worker") is None
    with pytest.raises(ValueError, match="Model probe auth token is unreadable"):
        _runtime_model_probe_for_service(settings, "api-server")


def test_default_model_connection_bootstrap_is_not_run_by_workers() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.configs: list[dict[str, Any]] = []

        def ensure_default_connection(self, *, config: dict[str, Any]) -> None:
            self.configs.append(config)

    recorder = Recorder()
    settings = build_settings()

    _ensure_default_model_connection_for_service(recorder, settings, "agent-worker")
    assert recorder.configs == []

    _ensure_default_model_connection_for_service(recorder, settings, "api-server")
    assert recorder.configs == [
        {
            "protocol": "anthropic_compatible",
            "base_url": "https://api.deepseek.com/anthropic",
            "model": settings.claude_model,
            "default_opus_model": settings.claude_model,
            "default_sonnet_model": settings.claude_model,
            "default_haiku_model": settings.claude_model,
            "subagent_model": settings.claude_model,
            "effort_level": "max",
        }
    ]


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


def test_credential_rotation_idempotency_does_not_create_a_second_revision() -> None:
    c = container()
    current = ready_connection(c)
    rotated = c.model_connection_service.rotate_credential(
        actor_id=ADMIN_ID,
        code=DEFAULT_MODEL_CONNECTION_CODE,
        expected_revision=int(current["revision"]),
        api_key=fake_secret("idempotent-rotation"),
        idempotency_key="model-credential-idempotency",
    )
    replayed = c.model_connection_service.rotate_credential(
        actor_id=ADMIN_ID,
        code=DEFAULT_MODEL_CONNECTION_CODE,
        expected_revision=int(current["revision"]),
        api_key=fake_secret("idempotent-rotation"),
        idempotency_key="model-credential-idempotency",
    )

    assert replayed == rotated
    assert (
        c.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)["revision"]
        == int(current["revision"]) + 1
    )


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
    assert private.value.error_code == "deepseek_url_invalid"

    bad = deepseek_config()
    bad["base_url"] = "https://example.com/anthropic"
    with pytest.raises(NonRetryableExecutionError) as host:
        c.model_connection_service.save_revision(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            expected_revision=connection["revision"],
            config=bad,
        )
    assert host.value.error_code == "deepseek_url_invalid"


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
    assert rejected.value.error_code == "deepseek_url_invalid"


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
            expected_revision=int(revision["revision"]),
        )
    assert rejected.value.error_code == "model_connection_redirect_rejected"
    assert invoked is False


def test_saved_connection_probe_delegates_revision_hash_to_typescript_runtime() -> None:
    c = container()
    revision = ready_connection(c)
    observed: dict[str, Any] = {}

    class Probe:
        def probe(self, **kwargs: Any) -> dict[str, Any]:
            observed.update(kwargs)
            return {
                "protocol_version": "1.0",
                "probe_id": "probe-safe-result",
                "success": True,
                "connection_revision_id": revision["id"],
                "provider_host": "api.deepseek.com",
                "model": "deepseek-v4-flash",
                "runtime_version": "0.1.0",
                "sdk_version": "0.3.226",
                "duration_ms": 12,
            }

    c.model_connection_service.runtime_probe = Probe()
    c.model_connection_service.redirect_checker = lambda *_args, **_kwargs: None
    result = c.model_connection_service.test_saved_revision(
        actor_id=ADMIN_ID,
        revision_id=str(revision["id"]),
        expected_revision=int(revision["revision"]),
        idempotency_key="saved-revision-probe",
    )
    replayed = c.model_connection_service.test_saved_revision(
        actor_id=ADMIN_ID,
        revision_id=str(revision["id"]),
        expected_revision=int(revision["revision"]),
        idempotency_key="saved-revision-probe",
    )

    assert observed == {
        "revision_id": revision["id"],
        "config_hash": revision["config_hash"],
        "timeout_seconds": 15,
    }
    assert result["runtime"] == "typescript-v1"
    assert result["sdk_version"] == "0.3.226"
    assert replayed == result
    serialized = json.dumps(result)
    assert "secret" not in serialized.lower()
    assert "key" not in serialized.lower()


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
    )
    client = RealClaudeCodeAgentClient(
        model="legacy",
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
