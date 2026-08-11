from __future__ import annotations

import json
import urllib.error
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.bootstrap import (
    _runtime_model_probe_for_service,
    _runtime_model_probes_for_service,
)
from app.modules.model_connection.infrastructure.runtime_probe import (
    RuntimeModelProbeClient,
    RuntimeModelProbeSettings,
)
from app.shared.config import AgentRuntimeSettings
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import test_settings as build_settings


class FakeResponse:
    status = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _client(tmp_path: Path) -> RuntimeModelProbeClient:
    token = tmp_path / "probe-token"
    token.write_text("probe-token-" + "x" * 32, encoding="utf-8")
    return RuntimeModelProbeClient(
        RuntimeModelProbeSettings(
            base_url="http://agent-runtime:9102",
            allowed_hosts=("agent-runtime",),
            auth_token_file=str(token),
            allow_insecure_internal_http=True,
        )
    )


def test_runtime_probe_sends_only_fixed_binding_and_accepts_safe_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)
    observed: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        payload = json.loads(request.data)
        observed.update(
            {
                "url": request.full_url,
                "authorization": request.get_header("Authorization"),
                "payload": payload,
                "timeout": timeout,
            }
        )
        return FakeResponse(
            {
                "protocol_version": "1.0",
                "runtime_kind": "typescript-v1",
                "probe_id": payload["probe_id"],
                "success": True,
                "connection_revision_id": "revision-1",
                "provider_host": "api.deepseek.com",
                "model": "deepseek-chat",
                "runtime_version": "0.1.0",
                "sdk_version": "0.3.226",
                "duration_ms": 8,
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = client.probe(
        revision_id="revision-1",
        config_hash="a" * 64,
        timeout_seconds=15,
    )

    assert result["success"] is True
    assert observed["url"] == "http://agent-runtime:9102/internal/v1/model-probes"
    assert observed["authorization"].startswith("Bearer probe-token-")
    assert observed["payload"]["model_connection"] == {
        "revision_id": "revision-1",
        "config_hash": "a" * 64,
    }
    serialized = json.dumps(observed["payload"])
    assert "api_key" not in serialized
    assert "secret" not in serialized


@pytest.mark.parametrize(
    "base_url,allowed_hosts",
    [
        ("http://attacker.invalid:9102", ("agent-runtime",)),
        ("http://user:pass@agent-runtime:9102", ("agent-runtime",)),
        ("http://agent-runtime:9102/path", ("agent-runtime",)),
    ],
)
def test_runtime_probe_rejects_urls_outside_deployment_boundary(
    tmp_path: Path,
    base_url: str,
    allowed_hosts: tuple[str, ...],
) -> None:
    token = tmp_path / "probe-token"
    token.write_text("x" * 32, encoding="utf-8")
    with pytest.raises(ValueError):
        RuntimeModelProbeClient(
            RuntimeModelProbeSettings(
                base_url=base_url,
                allowed_hosts=allowed_hosts,
                auth_token_file=str(token),
                allow_insecure_internal_http=True,
            )
        )


def test_runtime_probe_maps_http_failure_without_exposing_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)

    def rejected(*_args: object, **_kwargs: object) -> Any:
        raise urllib.error.HTTPError(
            client.endpoint,
            503,
            "secret upstream detail",
            {},
            None,
        )

    monkeypatch.setattr("urllib.request.urlopen", rejected)
    with pytest.raises(NonRetryableExecutionError) as failure:
        client.probe(
            revision_id="revision-1",
            config_hash="a" * 64,
            timeout_seconds=15,
        )
    assert failure.value.error_code == "model_connection_test_unavailable"
    assert "secret upstream detail" not in failure.value.safe_message


def test_only_api_service_receives_model_probe_bearer_token(tmp_path: Path) -> None:
    token = tmp_path / "probe-token"
    token.write_text("probe-token-" + "x" * 32, encoding="utf-8")
    settings = replace(
        build_settings(),
        agent_runtime=AgentRuntimeSettings(
            python_base_url="http://python-agent-runtime:8091",
            python_allowed_hosts=("python-agent-runtime",),
            typescript_base_url="http://typescript-agent-runtime:9102",
            typescript_allowed_hosts=("typescript-agent-runtime",),
            model_probe_auth_token_file=str(token),
            allow_insecure_internal_http=True,
        ),
    )

    assert _runtime_model_probe_for_service(settings, "api-server") is not None
    probes = _runtime_model_probes_for_service(settings, "api-server")
    assert set(probes) == {"python-v1", "typescript-v1"}
    assert probes["python-v1"].endpoint.startswith("http://python-agent-runtime:8091/")
    assert probes["typescript-v1"].endpoint.startswith("http://typescript-agent-runtime:9102/")
    assert _runtime_model_probe_for_service(settings, "agent-worker") is None
    assert _runtime_model_probe_for_service(settings, "tool-mcp") is None
    assert _runtime_model_probes_for_service(settings, "agent-worker") == {}
