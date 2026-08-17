from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.model_connection.api import controller as model_connection_controller
from app.modules.model_connection.application.service import (
    MAX_DISCOVERY_BYTES,
    _deepseek_models_url,
    _fetch_deepseek_models,
)
from app.modules.model_connection.domain import DEFAULT_MODEL_CONNECTION_CODE
from app.shared.config import IdentitySettings
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import test_settings as build_settings


ADMIN_ID = "user_local_admin"
BASE_URL = "https://api.deepseek.com/anthropic"
MODEL = "deepseek-chat"


def make_container(*, web: bool = False):
    settings = replace(
        build_settings(),
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=web,
            published_agent_runtime_enabled=True,
            cookie_secure=False,
            allowed_origins=("http://admin.test",) if web else (),
        ),
    )
    value = build_test_container(settings, migrate=True, seed=True)
    value.model_connection_service.dns_resolver = lambda *args, **kwargs: [
        (2, 1, 6, "", ("1.1.1.1", 443))
    ]
    return settings, value


def config(
    model: str = MODEL,
    *,
    opus: str = "",
    sonnet: str = "",
    haiku: str = "",
    subagent: str = "",
    effort: str = "max",
) -> dict[str, str]:
    return {
        "protocol": "anthropic_compatible",
        "base_url": BASE_URL,
        "model": model,
        "default_opus_model": opus,
        "default_sonnet_model": sonnet,
        "default_haiku_model": haiku,
        "subagent_model": subagent,
        "effort_level": effort,
    }


def secret_value(label: str) -> str:
    return f"sk-test-{label}-" + "x" * 40


class PythonRuntimeProbe:
    def __init__(
        self,
        draft_handler: Callable[[Any, str, int], dict[str, Any]] | None = None,
    ) -> None:
        self.draft_handler = draft_handler

    def probe_draft(
        self,
        *,
        binding: Any,
        api_key: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        result = (
            self.draft_handler(binding, api_key, timeout_seconds)
            if self.draft_handler is not None
            else {}
        )
        return {
            "runtime_kind": "python-v1",
            "success": True,
            "provider_host": binding.provider_host,
            "model": binding.model,
            **result,
        }


def install_successful_probes(c, *models: str) -> None:
    available = models or (MODEL,)
    c.model_connection_service.model_discoverer = lambda models_url, api_key, timeout_seconds: [
        {"id": model_id} for model_id in available
    ]
    c.model_connection_service.runtime_probes = {"python-v1": PythonRuntimeProbe()}


def table_counts(c) -> dict[str, int]:
    return {
        table: int(c.database.execute_one(f"select count(*) as count from {table}")["count"])
        for table in (
            "platform_secret",
            "platform_secret_version",
            "model_connection_revision",
            "agent_revision",
            "agent_publication",
        )
    }


def test_legacy_three_step_flow_reproduces_stale_expected_revision_conflict() -> None:
    _, c = make_container()
    try:
        connection = c.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)
        saved = c.model_connection_service.save_revision(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            expected_revision=connection["revision"],
            config=config(),
        )
        with pytest.raises(NonRetryableExecutionError) as rejected:
            c.model_connection_service.rotate_credential(
                actor_id=ADMIN_ID,
                code=DEFAULT_MODEL_CONNECTION_CODE,
                expected_revision=connection["revision"],
                api_key=secret_value("stale"),
            )
        assert saved["revision"] == connection["revision"] + 1
        assert rejected.value.error_code == "revision_conflict"
        assert rejected.value.diagnostics["current_revision"] == saved["revision"]
    finally:
        c.database.close()


def test_deepseek_url_derivation_supports_prefix_and_rejects_unsafe_shapes() -> None:
    _, c = make_container()
    service = c.model_connection_service
    try:
        prefixed = service.normalize_base_url(
            "https://api.deepseek.com/v1/anthropic/",
            validate_dns=True,
        )
        assert prefixed == "https://api.deepseek.com/v1/anthropic"
        assert _deepseek_models_url(prefixed) == "https://api.deepseek.com/v1/models"

        for value in (
            "https://api.deepseek.com/models",
            "https://api.deepseek.com:444/anthropic",
            "https://other.example/anthropic",
            "https://user@api.deepseek.com/anthropic",
            "https://api.deepseek.com/a/../anthropic",
            "https://api.deepseek.com//anthropic",
        ):
            with pytest.raises(NonRetryableExecutionError) as rejected:
                service.normalize_base_url(value, validate_dns=True)
            assert rejected.value.error_code == "deepseek_url_invalid"

        service.dns_resolver = lambda *args, **kwargs: [(2, 1, 6, "", ("10.0.0.2", 443))]
        with pytest.raises(NonRetryableExecutionError) as private:
            service.normalize_base_url(BASE_URL, validate_dns=True)
        assert private.value.error_code == "deepseek_url_invalid"
    finally:
        c.database.close()


class _Response:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class _Opener:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.request: urllib.request.Request | None = None

    def open(self, request: urllib.request.Request, timeout: int):
        del timeout
        self.request = request
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def test_bounded_discovery_client_uses_bearer_and_projects_safe_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = _Opener(_Response(json.dumps({"data": [{"id": MODEL}]}).encode("utf-8")))
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: opener)
    assert _fetch_deepseek_models(
        "https://api.deepseek.com/models",
        secret_value("bearer"),
        5,
    ) == [{"id": MODEL}]
    assert opener.request is not None
    assert opener.request.get_header("Authorization") == (f"Bearer {secret_value('bearer')}")

    cases = [
        (
            urllib.error.HTTPError("https://api.deepseek.com/models", 401, "denied", {}, None),
            "deepseek_credential_rejected",
        ),
        (
            urllib.error.HTTPError("https://api.deepseek.com/models", 302, "redirect", {}, None),
            "deepseek_url_invalid",
        ),
        (socket.timeout("upstream timeout"), "deepseek_model_discovery_failed"),
        (_Response(b"not-json"), "deepseek_model_discovery_failed"),
        (
            _Response(b"x" * (MAX_DISCOVERY_BYTES + 1)),
            "deepseek_model_discovery_failed",
        ),
    ]
    for outcome, error_code in cases:
        monkeypatch.setattr(
            urllib.request,
            "build_opener",
            lambda *args, outcome=outcome: _Opener(outcome),
        )
        with pytest.raises(NonRetryableExecutionError) as rejected:
            _fetch_deepseek_models(
                "https://api.deepseek.com/models",
                secret_value("never-leak"),
                5,
            )
        assert rejected.value.error_code == error_code
        assert secret_value("never-leak") not in rejected.value.safe_message


def test_discover_and_test_draft_are_non_persistent_and_normalize_inheritance() -> None:
    _, c = make_container()
    before = table_counts(c)
    observed: list[tuple[str, bool]] = []

    def discover(models_url: str, api_key: str, timeout_seconds: int):
        del models_url, api_key, timeout_seconds
        observed.append(("discover", c.database.current_unit_of_work is None))
        return [{"id": "z-model"}, {"id": MODEL}, {"id": MODEL}]

    def tester(binding, api_key: str, timeout_seconds: int):
        del api_key, timeout_seconds
        observed.append(("tester", c.database.current_unit_of_work is None))
        assert binding.default_opus_model == MODEL
        assert binding.default_sonnet_model == MODEL
        assert binding.default_haiku_model == MODEL
        assert binding.subagent_model == MODEL
        assert binding.secret_ref == ""
        return {"detail": secret_value("provider-output")}

    c.model_connection_service.model_discoverer = discover
    c.model_connection_service.runtime_probes = {
        "python-v1": PythonRuntimeProbe(tester)
    }
    try:
        discovered = c.model_connection_service.discover_models(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            base_url=BASE_URL,
            credential_source="submitted",
            api_key=secret_value("temporary"),
        )
        assert [item["id"] for item in discovered["models"]] == [MODEL, "z-model"]
        tested = c.model_connection_service.test_draft(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            credential_source="submitted",
            api_key=secret_value("temporary"),
            config=config(),
        )
        assert tested["detail"] == "连接成功"
        assert secret_value("provider-output") not in json.dumps(tested)
        assert table_counts(c) == before
        assert observed == [
            ("discover", True),
            ("discover", True),
            ("tester", True),
        ]
    finally:
        c.database.close()


def test_discovery_rejects_empty_malformed_and_over_limit_model_lists() -> None:
    _, c = make_container()
    service = c.model_connection_service
    try:
        cases = [
            ([], "deepseek_model_list_empty"),
            ([{"name": MODEL}], "deepseek_model_discovery_failed"),
            ([{"id": "x" * 201}], "deepseek_model_discovery_failed"),
            (
                [{"id": f"model-{index}"} for index in range(201)],
                "deepseek_model_discovery_failed",
            ),
        ]
        for models, expected_code in cases:
            service.model_discoverer = lambda models_url, api_key, timeout_seconds, models=models: (
                models
            )
            with pytest.raises(NonRetryableExecutionError) as rejected:
                service.discover_models(
                    actor_id=ADMIN_ID,
                    code=DEFAULT_MODEL_CONNECTION_CODE,
                    base_url=BASE_URL,
                    credential_source="submitted",
                    api_key=secret_value("bounded"),
                )
            assert rejected.value.error_code == expected_code
            assert secret_value("bounded") not in rejected.value.safe_message
    finally:
        c.database.close()


@pytest.mark.parametrize(
    ("error_code", "expected_code"),
    [
        ("model_connection_provider_rejected", "model_connection_test_failed"),
        ("model_connection_test_timeout", "model_connection_test_timeout"),
    ],
)
def test_draft_test_projects_sdk_failures_without_persistence(
    error_code: str,
    expected_code: str,
) -> None:
    _, c = make_container()
    install_successful_probes(c)
    before = table_counts(c)

    def failed_tester(binding, api_key: str, timeout_seconds: int):
        del binding, timeout_seconds
        raise NonRetryableExecutionError(
            f"upstream failed with {api_key}",
            safe_message=f"upstream failed with {api_key}",
            error_code=error_code,
        )

    c.model_connection_service.runtime_probes = {
        "python-v1": PythonRuntimeProbe(failed_tester)
    }
    try:
        with pytest.raises(NonRetryableExecutionError) as rejected:
            c.model_connection_service.test_draft(
                actor_id=ADMIN_ID,
                code=DEFAULT_MODEL_CONNECTION_CODE,
                credential_source="submitted",
                api_key=secret_value("sdk-error"),
                config=config(),
            )
        assert rejected.value.error_code == expected_code
        assert secret_value("sdk-error") not in rejected.value.safe_message
        assert table_counts(c) == before
    finally:
        c.database.close()


def test_configure_is_atomic_and_supports_create_reuse_and_rotation() -> None:
    _, c = make_container()
    install_successful_probes(c, MODEL, "deepseek-reasoner")
    try:
        connection = c.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)
        first = c.model_connection_service.configure(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            expected_revision=connection["revision"],
            credential_source="submitted",
            api_key=secret_value("first"),
            config=config(),
        )
        private_first = c.model_connection_service.repository.get_revision(first["id"])
        secret_id = str(private_first["api_key_secret_id"])
        first_secret = c.model_connection_service.platform_repository.get_platform_secret(secret_id)
        assert first["status"] == "ready"
        assert first_secret["metadata"] == {
            "kind": "model_connection",
            "connection_code": DEFAULT_MODEL_CONNECTION_CODE,
            "connection_id": connection["id"],
        }
        tested_existing = c.model_connection_service.test_draft(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            credential_source="existing",
            config=config(),
        )
        assert tested_existing["success"] is True
        assert (
            c.model_connection_service.platform_repository.get_platform_secret(secret_id)[
                "active_version"
            ]
            == first_secret["active_version"]
        )

        reused = c.model_connection_service.configure(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            expected_revision=first["revision"],
            credential_source="existing",
            config=config(effort="high"),
        )
        reused_private = c.model_connection_service.repository.get_revision(reused["id"])
        reused_secret = c.model_connection_service.platform_repository.get_platform_secret(
            secret_id
        )
        assert reused_private["api_key_secret_id"] == secret_id
        assert reused_secret["active_version"] == first_secret["active_version"]

        rotated = c.model_connection_service.configure(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            expected_revision=reused["revision"],
            credential_source="submitted",
            api_key=secret_value("rotated"),
            config=config(model="deepseek-reasoner"),
        )
        rotated_private = c.model_connection_service.repository.get_revision(rotated["id"])
        rotated_secret = c.model_connection_service.platform_repository.get_platform_secret(
            secret_id
        )
        assert rotated_private["api_key_secret_id"] == secret_id
        assert rotated_secret["active_version"] == first_secret["active_version"] + 1
        binding = c.model_connection_service.runtime_binding(rotated["id"])
        assert c.model_connection_service.resolve_api_key(binding) == secret_value("rotated")
    finally:
        c.database.close()


def test_configure_recovers_owned_orphan_and_disabled_bound_secret() -> None:
    _, c = make_container()
    install_successful_probes(c)
    try:
        connection = c.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)
        secret_code = f"model-{DEFAULT_MODEL_CONNECTION_CODE}-api-key"
        orphan = c.model_connection_service.secret_provider.create_secret(
            code=secret_code,
            value=secret_value("owned-orphan"),
            actor_id=ADMIN_ID,
            metadata={
                "kind": "model_connection",
                "connection_code": DEFAULT_MODEL_CONNECTION_CODE,
                "connection_id": connection["id"],
            },
        )
        recovered = c.model_connection_service.configure(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            expected_revision=connection["revision"],
            credential_source="submitted",
            api_key=secret_value("recovered"),
            config=config(),
        )
        recovered_private = c.model_connection_service.repository.get_revision(recovered["id"])
        assert recovered_private["api_key_secret_id"] == orphan["id"]
        recovered_secret = c.model_connection_service.platform_repository.get_platform_secret(
            str(orphan["id"])
        )
        assert recovered_secret["active_version"] == 2

        c.model_connection_service.secret_provider.disable_secret(
            code=secret_code,
            actor_id=ADMIN_ID,
        )
        with pytest.raises(NonRetryableExecutionError) as unavailable:
            c.model_connection_service.discover_models(
                actor_id=ADMIN_ID,
                code=DEFAULT_MODEL_CONNECTION_CODE,
                base_url=BASE_URL,
                credential_source="existing",
            )
        assert unavailable.value.error_code == "model_connection_credential_unavailable"

        enabled = c.model_connection_service.configure(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            expected_revision=recovered["revision"],
            credential_source="submitted",
            api_key=secret_value("reenabled"),
            config=config(),
        )
        assert enabled["status"] == "ready"
        assert enabled["credential"]["rotation_required"] is False
        assert enabled["credential"]["version"] == 3
    finally:
        c.database.close()


def test_configure_rejects_orphan_ownership_and_rolls_back_audit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, conflict_container = make_container()
    install_successful_probes(conflict_container)
    try:
        connection = conflict_container.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)
        conflict_container.model_connection_service.secret_provider.create_secret(
            code=f"model-{DEFAULT_MODEL_CONNECTION_CODE}-api-key",
            value=secret_value("orphan"),
            actor_id=ADMIN_ID,
            metadata={
                "kind": "model_connection",
                "connection_code": "another-connection",
                "connection_id": "another-id",
            },
        )
        before_conflict = table_counts(conflict_container)
        with pytest.raises(NonRetryableExecutionError) as conflict:
            conflict_container.model_connection_service.configure(
                actor_id=ADMIN_ID,
                code=DEFAULT_MODEL_CONNECTION_CODE,
                expected_revision=connection["revision"],
                credential_source="submitted",
                api_key=secret_value("must-not-rotate"),
                config=config(),
            )
        assert conflict.value.error_code == "credential_ownership_conflict"
        assert table_counts(conflict_container) == before_conflict
    finally:
        conflict_container.database.close()

    _, c = make_container()
    install_successful_probes(c)
    try:
        connection = c.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)
        before_audit = table_counts(c)
        monkeypatch.setattr(
            c.model_connection_service.audit_service,
            "record",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
        )
        with pytest.raises(RuntimeError, match="audit failed"):
            c.model_connection_service.configure(
                actor_id=ADMIN_ID,
                code=DEFAULT_MODEL_CONNECTION_CODE,
                expected_revision=connection["revision"],
                credential_source="submitted",
                api_key=secret_value("rollback"),
                config=config(),
            )
        assert table_counts(c) == before_audit
    finally:
        c.database.close()


def test_configure_rechecks_revision_after_external_test_without_partial_secret() -> None:
    _, c = make_container()
    connection = c.model_connection_service.get(DEFAULT_MODEL_CONNECTION_CODE)
    c.model_connection_service.model_discoverer = lambda models_url, api_key, timeout_seconds: [
        {"id": MODEL}
    ]

    def concurrent_update(binding, api_key: str, timeout_seconds: int):
        del binding, api_key, timeout_seconds
        c.model_connection_service.save_revision(
            actor_id=ADMIN_ID,
            code=DEFAULT_MODEL_CONNECTION_CODE,
            expected_revision=connection["revision"],
            config=config(),
        )
        return {"detail": "连接成功"}

    c.model_connection_service.runtime_probes = {
        "python-v1": PythonRuntimeProbe(concurrent_update)
    }
    before_secrets = table_counts(c)
    try:
        with pytest.raises(NonRetryableExecutionError) as conflict:
            c.model_connection_service.configure(
                actor_id=ADMIN_ID,
                code=DEFAULT_MODEL_CONNECTION_CODE,
                expected_revision=connection["revision"],
                credential_source="submitted",
                api_key=secret_value("concurrent"),
                config=config(),
            )
        assert conflict.value.error_code == "revision_conflict"
        after = table_counts(c)
        assert after["platform_secret"] == before_secrets["platform_secret"]
        assert after["platform_secret_version"] == before_secrets["platform_secret_version"]
        assert after["model_connection_revision"] == (
            before_secrets["model_connection_revision"] + 1
        )
    finally:
        c.database.close()


def test_management_api_schema_revision_conflict_rate_limit_and_secret_redaction() -> None:
    settings, c = make_container(web=True)
    install_successful_probes(c)
    calls = 0

    def discover(models_url: str, api_key: str, timeout_seconds: int):
        nonlocal calls
        del models_url, api_key, timeout_seconds
        calls += 1
        return [{"id": MODEL}]

    c.model_connection_service.model_discoverer = discover
    app = create_app(settings, container_factory=lambda _: c)
    model_connection_controller._MODEL_PROBE_RATE_WINDOWS.clear()
    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={
                    "username": "admin",
                    "password": "111111111111",
                },
            )
            assert login.status_code == 200
            csrf = client.cookies.get("enterprise_agent_csrf")
            headers = {"origin": "http://admin.test", "x-csrf-token": csrf}
            path = f"/api/admin/model-connections/{DEFAULT_MODEL_CONNECTION_CODE}"
            current = client.get(path).json()["connection"]

            stale = client.put(
                f"{path}/configure",
                headers=headers,
                json={
                    "expected_revision": current["revision"] - 1,
                    "credential_source": "submitted",
                    "api_key": secret_value("stale-api"),
                    "config": config(),
                    "timeout_seconds": 15,
                },
            )
            assert stale.status_code == 409
            assert stale.json()["detail"]["current_revision"] == current["revision"]
            assert calls == 0

            extra = client.post(
                f"{path}/discover",
                headers=headers,
                json={
                    "base_url": BASE_URL,
                    "credential_source": "submitted",
                    "api_key": secret_value("strict"),
                    "unexpected": True,
                },
            )
            assert extra.status_code == 422
            assert calls == 0

            no_csrf = client.post(
                f"{path}/discover",
                headers={"origin": "http://admin.test"},
                json={
                    "base_url": BASE_URL,
                    "credential_source": "submitted",
                    "api_key": secret_value("csrf"),
                },
            )
            assert no_csrf.status_code == 403
            assert calls == 0

            model_connection_controller._MODEL_PROBE_RATE_WINDOWS.clear()
            responses = [
                client.post(
                    f"{path}/discover",
                    headers=headers,
                    json={
                        "base_url": BASE_URL,
                        "credential_source": "submitted",
                        "api_key": secret_value(f"rate-{index}"),
                    },
                )
                for index in range(model_connection_controller.MODEL_PROBE_REQUESTS_PER_MINUTE)
            ]
            assert all(response.status_code == 200 for response in responses)
            limited = client.post(
                f"{path}/discover",
                headers=headers,
                json={
                    "base_url": BASE_URL,
                    "credential_source": "submitted",
                    "api_key": secret_value("limited"),
                },
            )
            assert limited.status_code == 429
            assert calls == model_connection_controller.MODEL_PROBE_REQUESTS_PER_MINUTE

            combined = "\n".join(response.text for response in responses)
            for index in range(model_connection_controller.MODEL_PROBE_REQUESTS_PER_MINUTE):
                assert secret_value(f"rate-{index}") not in combined
            audit_text = json.dumps(
                c.database.execute(
                    "select event_type, summary, payload_summary from audit_event "
                    "where event_type like 'model.connection.%'"
                ),
                ensure_ascii=False,
            )
            assert "Authorization" not in audit_text
            assert "secret://platform/" not in audit_text
            for index in range(model_connection_controller.MODEL_PROBE_REQUESTS_PER_MINUTE):
                assert secret_value(f"rate-{index}") not in audit_text
    finally:
        model_connection_controller._MODEL_PROBE_RATE_WINDOWS.clear()
        c.database.close()
