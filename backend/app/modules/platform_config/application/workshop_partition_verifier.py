from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import json
from time import monotonic
from typing import Any, Protocol

from app.modules.platform_config.domain.provider_contracts import (
    ProviderContractRegistry,
)
from app.shared.database import assert_external_io_allowed


@dataclass(frozen=True)
class WorkshopPartitionVerificationOutcome:
    status: str
    verifier_version: str
    redis_summary: dict[str, Any] = field(default_factory=dict)
    zero_match_warning: bool = False
    safe_error_summary: str = ""


class WorkshopPartitionTechnicalVerifier(Protocol):
    def verify_redis(
        self,
        *,
        resource_revision: dict[str, Any],
        prefixes: tuple[str, ...],
    ) -> WorkshopPartitionVerificationOutcome: ...


class RedisWorkshopPartitionTechnicalVerifier:
    """Probe exact namespaces without persisting Redis business keys."""

    verifier_version = "workshop-partition-redis-scan.v1"

    def __init__(
        self,
        *,
        resolve_secret: Callable[[str], str],
        connect_factory: Callable[..., Any] | None = None,
        provider_contracts: ProviderContractRegistry | None = None,
        timeout_seconds: int = 5,
        scan_count: int = 100,
    ) -> None:
        self._resolve_secret = resolve_secret
        self._connect_factory = connect_factory
        self._provider_contracts = provider_contracts or ProviderContractRegistry()
        self._timeout_seconds = max(1, min(int(timeout_seconds), 10))
        self._scan_count = max(1, min(int(scan_count), 200))

    def verify_redis(
        self,
        *,
        resource_revision: dict[str, Any],
        prefixes: tuple[str, ...],
    ) -> WorkshopPartitionVerificationOutcome:
        assert_external_io_allowed("workshop_partition_verify.redis")
        client: Any | None = None
        runtime: dict[str, Any] = {}
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
            connect = self._connect_factory
            if connect is None:
                import redis

                connect = redis.Redis
            tls = dict(runtime.get("tls") or {})
            client = connect(
                host=runtime["host"],
                port=int(runtime["port"]),
                db=int(runtime["db"]),
                username=runtime.get("username") or None,
                password=runtime.get("password") or None,
                socket_connect_timeout=self._timeout_seconds,
                socket_timeout=self._timeout_seconds,
                ssl=bool(tls.get("enabled", False)),
                ssl_cert_reqs=("required" if tls.get("verify_certificate", True) else None),
                ssl_check_hostname=bool(
                    tls.get("enabled", False) and tls.get("verify_certificate", True)
                ),
                decode_responses=True,
            )
            summaries: list[dict[str, Any]] = []
            zero_match = False
            for prefix in prefixes:
                started = monotonic()
                cursor, keys = client.scan(
                    cursor=0,
                    match=f"{prefix}*",
                    count=self._scan_count,
                )
                bounded_keys = [str(key) for key in list(keys)[: self._scan_count]]
                truncated = str(cursor) not in {"0", "b'0'"} or len(keys) > self._scan_count
                zero_match = zero_match or not bounded_keys
                summaries.append(
                    {
                        "prefix_hash": _hash_text(prefix),
                        "match_count": len(bounded_keys),
                        "truncated": truncated,
                        "match_hash": _hash_values(bounded_keys),
                        "duration_ms": max(0, int((monotonic() - started) * 1000)),
                    }
                )
            return WorkshopPartitionVerificationOutcome(
                status="PASSED",
                verifier_version=self.verifier_version,
                redis_summary={
                    "enabled": True,
                    "prefix_count": len(prefixes),
                    "probes": summaries,
                },
                zero_match_warning=zero_match,
                safe_error_summary=(
                    "一个或多个 Redis namespace 当前未匹配到数据" if zero_match else ""
                ),
            )
        except ModuleNotFoundError:
            return self._failure("BLOCKED", "Redis 客户端未安装，无法验证 namespace")
        except Exception:
            return self._failure("FAILED", "Redis namespace 有界验证失败")
        finally:
            runtime.pop("password", None)
            if client is not None:
                close = getattr(client, "close", None)
                if close is not None:
                    close()

    def _failure(
        self,
        status: str,
        safe_error_summary: str,
    ) -> WorkshopPartitionVerificationOutcome:
        return WorkshopPartitionVerificationOutcome(
            status=status,
            verifier_version=self.verifier_version,
            redis_summary={"enabled": True, "prefix_count": 0, "probes": []},
            safe_error_summary=safe_error_summary,
        )


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_values(values: list[str]) -> str:
    canonical = json.dumps(sorted(values), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
