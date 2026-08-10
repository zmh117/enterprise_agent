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
from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import NonRetryableExecutionError


@dataclass(frozen=True)
class RuntimeModelProbeSettings:
    base_url: str
    allowed_hosts: tuple[str, ...]
    auth_token_file: str
    allow_insecure_internal_http: bool = False

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
            "probe_id": f"probe-{uuid.uuid4().hex}",
            "model_connection": {
                "revision_id": revision_id,
                "config_hash": config_hash,
            },
            "timeout_seconds": timeout,
        }
        validate_contract("ModelProbeRequest", payload)
        request = urllib.request.Request(
            self.endpoint,
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
                "TypeScript Runtime model connection probe is unavailable",
                safe_message="模型连接测试运行时不可用",
                error_code="model_connection_test_unavailable",
            ) from exc
        if not isinstance(result, dict) or result.get("probe_id") != payload["probe_id"]:
            raise NonRetryableExecutionError(
                "TypeScript Runtime model probe identity mismatch",
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
        "TypeScript Runtime rejected model connection probe",
        safe_message="模型连接当前不可用于测试",
        error_code=error_code,
    )
