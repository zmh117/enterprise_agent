from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import socket
from time import monotonic
from typing import Any
import urllib.error
import urllib.parse
from urllib.request import Request, urlopen

from app.modules.platform_config.domain.provider_contracts import ProviderContractRegistry
from app.shared.database import assert_external_io_allowed


@dataclass(frozen=True)
class LokiScopePolicyVerificationOutcome:
    status: str
    verifier_version: str
    match_count: int = 0
    truncated: bool = False
    zero_match_warning: bool = False
    result_summary: dict[str, Any] = field(default_factory=dict)
    safe_error_summary: str = ""


class LokiScopePolicyTechnicalVerifier:
    verifier_version = "loki-scope-series.v1"

    def __init__(
        self,
        *,
        resolve_secret: Callable[[str], str],
        urlopen_func: Callable[..., Any] = urlopen,
        provider_contracts: ProviderContractRegistry | None = None,
        timeout_seconds: int = 5,
        minutes: int = 15,
        stream_limit: int = 100,
    ) -> None:
        self._resolve_secret = resolve_secret
        self._urlopen = urlopen_func
        self._provider_contracts = provider_contracts or ProviderContractRegistry()
        self._timeout_seconds = max(1, min(int(timeout_seconds), 10))
        self._minutes = max(1, min(int(minutes), 60))
        self._stream_limit = max(1, min(int(stream_limit), 100))

    def verify(
        self,
        *,
        resource_revision: dict[str, Any],
        conditions: tuple[tuple[str, str], ...],
    ) -> LokiScopePolicyVerificationOutcome:
        assert_external_io_allowed("loki_scope_policy_verify.http")
        runtime: dict[str, Any] = {}
        started = monotonic()
        try:
            document = self._provider_contracts.normalize(
                provider_type=str(resource_revision["provider_type"]),
                config=dict(resource_revision["config"]),
                secret_refs=dict(resource_revision["secret_refs"]),
            )
            runtime = self._provider_contracts.runtime_projection(
                document,
                resolve_secret=self._resolve_secret,
            )
            end_ns = int(datetime.now(UTC).timestamp() * 1_000_000_000)
            params = [
                ("start", str(end_ns - self._minutes * 60 * 1_000_000_000)),
                ("end", str(end_ns)),
                ("match[]", _selector(conditions)),
            ]
            url = (
                f"{str(runtime['base_url']).rstrip('/')}/loki/api/v1/series?"
                f"{urllib.parse.urlencode(params)}"
            )
            headers = {"accept": "application/json"}
            if runtime.get("tenant"):
                headers["X-Scope-OrgID"] = str(runtime["tenant"])
            if runtime.get("auth_token"):
                headers["Authorization"] = f"Bearer {runtime['auth_token']}"
            request = Request(url, headers=headers, method="GET")
            maximum_bytes = min(int(runtime["max_response_bytes"]), 64 * 1024)
            with self._urlopen(
                request,
                timeout=min(int(runtime["timeout_seconds"]), self._timeout_seconds),
            ) as response:
                raw = response.read(maximum_bytes + 1)
            if len(raw) > maximum_bytes:
                raise ValueError("response too large")
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict) or parsed.get("status") not in {None, "success"}:
                raise ValueError("invalid Loki response")
            data = parsed.get("data")
            series = data if isinstance(data, list) else []
            bounded = series[: self._stream_limit]
            truncated = len(series) > self._stream_limit
            match_count = len(bounded)
            zero_match = match_count == 0
            return LokiScopePolicyVerificationOutcome(
                status="PASSED",
                verifier_version=self.verifier_version,
                match_count=match_count,
                truncated=truncated,
                zero_match_warning=zero_match,
                result_summary={
                    "match_hash": _hash_series(bounded),
                    "duration_ms": max(0, int((monotonic() - started) * 1000)),
                },
                safe_error_summary=("Loki selector 当前未匹配到日志流" if zero_match else ""),
            )
        except ModuleNotFoundError:
            return self._failure("BLOCKED", "Loki Scope Policy 验证器不可用", started)
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ):
            return self._failure("FAILED", "Loki selector 有界验证失败", started)
        except Exception:
            return self._failure("FAILED", "Loki selector 有界验证失败", started)
        finally:
            runtime.pop("auth_token", None)

    def _failure(
        self,
        status: str,
        safe_error_summary: str,
        started: float,
    ) -> LokiScopePolicyVerificationOutcome:
        return LokiScopePolicyVerificationOutcome(
            status=status,
            verifier_version=self.verifier_version,
            result_summary={
                "match_hash": hashlib.sha256(b"[]").hexdigest(),
                "duration_ms": max(0, int((monotonic() - started) * 1000)),
            },
            safe_error_summary=safe_error_summary,
        )


def _selector(conditions: tuple[tuple[str, str], ...]) -> str:
    return (
        "{"
        + ",".join(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in conditions)
        + "}"
    )


def _hash_series(series: list[Any]) -> str:
    canonical = json.dumps(
        series,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
