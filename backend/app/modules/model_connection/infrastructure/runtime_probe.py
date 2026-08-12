from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jsonschema import ValidationError

from app.modules.agent.infrastructure.generated_runtime_contracts import validate_contract
from app.modules.model_connection.domain import ModelRuntimeBinding
from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.model_probe_envelope import ModelProbeEnvelopeCipher


@dataclass(frozen=True)
class RuntimeModelProbeSettings:
    base_url: str
    allowed_hosts: tuple[str, ...]
    auth_token_file: str
    master_key: str = ""
    allow_insecure_internal_http: bool = False
    runtime_kind: str = "typescript-v1"

    def endpoint(self) -> str:
        normalized = self.base_url.strip().rstrip("/")
        parsed = urlsplit(normalized)
        host = (parsed.hostname or "").lower()
        allowed = {item.strip().lower() for item in self.allowed_hosts if item.strip()}
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or host not in allowed
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Agent Runtime model probe URL is outside the deployment boundary")
        if (
            parsed.scheme == "http"
            and host not in {"localhost", "127.0.0.1", "::1"}
            and not self.allow_insecure_internal_http
        ):
            raise ValueError("Agent Runtime model probe requires HTTPS outside local development")
        return f"{normalized}/internal/v1/model-probes"


class RuntimeModelProbeClient:
    def __init__(self, settings: RuntimeModelProbeSettings) -> None:
        self.endpoint = settings.endpoint()
        self.draft_endpoint = f"{self.endpoint}/draft"
        if settings.runtime_kind not in {"python-v1", "typescript-v1"}:
            raise ValueError("Agent Runtime model probe kind is unsupported")
        self.runtime_kind = settings.runtime_kind
        token_path = Path(settings.auth_token_file.strip())
        if not token_path.is_absolute():
            raise ValueError("MODEL_PROBE_AUTH_TOKEN_FILE must be an absolute path")
        try:
            if not 32 <= token_path.stat().st_size <= 4096:
                raise ValueError("Model probe auth token size is invalid")
            self._token = token_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError("Model probe auth token is unreadable") from exc
        if len(self._token) < 32:
            raise ValueError("Model probe auth token is too short")
        self._envelopes = (
            ModelProbeEnvelopeCipher(settings.master_key) if settings.master_key else None
        )

    def probe(
        self,
        *,
        revision_id: str,
        config_hash: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        timeout = max(3, min(int(timeout_seconds), 20))
        payload: dict[str, Any] = {
            "protocol_version": "1.0",
            "runtime_kind": self.runtime_kind,
            "probe_id": f"probe-{uuid.uuid4().hex}",
            "model_connection": {
                "revision_id": revision_id,
                "config_hash": config_hash,
            },
            "timeout_seconds": timeout,
        }
        return self._send_probe(
            endpoint=self.endpoint,
            contract_name="ModelProbeRequest",
            payload=payload,
            expected_revision_id=revision_id,
            timeout=timeout,
        )

    def probe_draft(
        self,
        *,
        binding: ModelRuntimeBinding,
        api_key: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        if self._envelopes is None:
            raise NonRetryableExecutionError(
                "Draft model probe encryption is unavailable",
                safe_message="模型连接测试运行时不可用",
                error_code="model_connection_test_unavailable",
            )
        timeout = max(3, min(int(timeout_seconds), 20))
        probe_id = f"probe-{uuid.uuid4().hex}"
        config: dict[str, Any] = {
            "schema_version": 1,
            "protocol": binding.protocol,
            "base_url": binding.base_url,
            "model": binding.model,
            "default_opus_model": binding.default_opus_model,
            "default_sonnet_model": binding.default_sonnet_model,
            "default_haiku_model": binding.default_haiku_model,
            "subagent_model": binding.subagent_model,
            "effort_level": binding.effort_level,
        }
        payload: dict[str, Any] = {
            "protocol_version": "1.0",
            "runtime_kind": self.runtime_kind,
            "probe_id": probe_id,
            "config_hash": binding.config_hash,
            "credential_envelope": self._envelopes.encrypt(
                probe_id=probe_id,
                runtime_kind=self.runtime_kind,
                config_hash=binding.config_hash,
                config=config,
                api_key=api_key,
                lifetime_seconds=timeout + 10,
            ),
            "timeout_seconds": timeout,
        }
        return self._send_probe(
            endpoint=self.draft_endpoint,
            contract_name="DraftModelProbeRequest",
            payload=payload,
            expected_revision_id=f"draft-{probe_id}",
            timeout=timeout,
        )

    def _send_probe(
        self,
        *,
        endpoint: str,
        contract_name: str,
        payload: dict[str, Any],
        expected_revision_id: str,
        timeout: int,
    ) -> dict[str, Any]:
        validate_contract(contract_name, payload)
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Correlation-Id": payload["probe_id"],
            },
            method="POST",
        )
        assert_external_io_allowed("model.runtime_probe")
        try:
            with urllib.request.urlopen(request, timeout=timeout + 5) as response:
                raw = response.read(65_537)
                if response.status != 200 or len(raw) > 65_536:
                    raise ValueError("invalid model probe response")
                result = json.loads(raw.decode("utf-8"))
            validate_contract("ModelProbeResponse", result)
        except urllib.error.HTTPError as exc:
            raise _safe_http_error(exc) from exc
        except (OSError, TimeoutError, UnicodeError, ValueError, ValidationError) as exc:
            raise NonRetryableExecutionError(
                "Agent Runtime model connection probe is unavailable",
                safe_message="模型连接测试运行时不可用",
                error_code="model_connection_test_unavailable",
            ) from exc
        if (
            not isinstance(result, dict)
            or result.get("probe_id") != payload["probe_id"]
            or result.get("runtime_kind") != self.runtime_kind
            or result.get("connection_revision_id") != expected_revision_id
        ):
            raise NonRetryableExecutionError(
                "Agent Runtime model probe identity mismatch",
                safe_message="模型连接测试响应无效",
                error_code="model_connection_test_invalid_response",
            )
        return result


def _safe_http_error(exc: urllib.error.HTTPError) -> NonRetryableExecutionError:
    error_code = "model_connection_test_unavailable"
    try:
        body = json.loads(exc.read(8192).decode("utf-8"))
        candidate = str(body.get("code") or "") if isinstance(body, dict) else ""
        if candidate.startswith(("runtime_model_", "model_connection_")):
            error_code = candidate
    except (OSError, UnicodeError, ValueError):
        pass
    return NonRetryableExecutionError(
        "Agent Runtime rejected model connection probe",
        safe_message="模型连接当前不可用于测试",
        error_code=error_code,
    )
