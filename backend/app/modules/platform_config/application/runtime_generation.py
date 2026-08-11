from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, replace
from typing import Any, Protocol

from app.modules.mcp_tool_runtime.domain.addressing import RevisionResource
from app.modules.mcp_tool_runtime.domain.topology import (
    Base,
    DatabaseConnection,
    DatabaseEngine,
    Environment,
    LokiConnection,
    OracleClientMode,
    OracleCompat,
    RedisConnection,
    ResourceKind,
    Topology,
    Workshop,
)
from app.modules.mcp_tool_runtime.infrastructure.secrets import SecretResolver
from app.modules.platform_config.domain.provider_contracts import (
    ProviderContractRegistry,
)
from app.modules.platform_config.infrastructure.repository import (
    PlatformConfigRepository,
)
from app.modules.platform_config.infrastructure.runtime_generation_repository import (
    GenerationTicket,
    RuntimeGenerationRepository,
)
from app.shared.secret_redaction import redact_sensitive_text

from .snapshot import RuntimeTopologySnapshot


class RuntimeGenerationTarget(Protocol):
    def apply_runtime_snapshot(
        self,
        snapshot: RuntimeTopologySnapshot,
    ) -> bool: ...

    def capture_runtime_snapshot(self) -> RuntimeTopologySnapshot: ...


@dataclass(frozen=True)
class RuntimeGenerationPollResult:
    observed: bool
    activated: bool
    retained_lkg: bool
    generation_id: str = ""
    generation_no: int = 0
    published_digest: str = ""
    error_code: str = ""


@dataclass(frozen=True)
class RuntimeGenerationBuild:
    snapshot: RuntimeTopologySnapshot
    snapshot_digest: str
    snapshot_metadata: dict[str, Any]


class GovernedRuntimeGenerationBuilder:
    """Build one complete in-memory generation from published DB facts."""

    def __init__(
        self,
        repository: RuntimeGenerationRepository,
        config_repository: PlatformConfigRepository,
        *,
        resolver: SecretResolver,
        provider_contracts: ProviderContractRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.config_repository = config_repository
        self.resolver = resolver
        self.provider_contracts = (
            provider_contracts or ProviderContractRegistry()
        )

    def build(
        self,
        ticket: GenerationTicket,
        *,
        previous: RuntimeTopologySnapshot,
    ) -> RuntimeGenerationBuild:
        resources = self.repository.published_resources()
        application_bindings = (
            self.repository.active_application_bindings()
        )
        topology = self._topology()
        revision_resources: dict[str, RevisionResource] = {}
        resource_states: list[dict[str, Any]] = []

        previous_by_resource = {
            str(state.get("resource_id") or ""): state
            for state in previous.resource_states
            if state.get("status") in {"READY", "DEGRADED"}
        }
        for resource in resources:
            revision_id = str(resource["resource_revision_id"])
            resource_id = str(resource["resource_id"])
            refs = {
                str(key): str(value)
                for key, value in resource["secret_refs"].items()
            }
            secret_versions = self.repository.active_secret_versions(
                refs.values()
            )
            try:
                if set(secret_versions) != set(refs.values()):
                    raise RuntimeError(
                        "Required platform Secret is unavailable"
                    )
                document = self.provider_contracts.normalize(
                    provider_type=str(resource["provider_type"]),
                    config=dict(resource["config"]),
                    secret_refs=refs,
                )
                projection = self.provider_contracts.runtime_projection(
                    document,
                    resolve_secret=self._resolve_nonempty,
                )
                revision_resources[revision_id] = (
                    self._revision_resource(resource, projection)
                )
                resource_states.append(
                    {
                        "resource_revision_id": revision_id,
                        "resource_id": resource_id,
                        "resource_code": str(resource["resource_code"]),
                        "effective_revision_id": revision_id,
                        "status": "READY",
                        "resolved_secret_versions": secret_versions,
                        "last_known_good_generation_id": ticket.id,
                        "error_code": "",
                        "error_summary": "",
                    }
                )
            except Exception as exc:
                previous_state = previous_by_resource.get(resource_id)
                effective_revision_id = (
                    str(
                        previous_state.get("effective_revision_id")
                        or previous_state.get("resource_revision_id")
                        or ""
                    )
                    if previous_state
                    else ""
                )
                lkg = previous.revision_resources.get(
                    effective_revision_id
                )
                if lkg is not None:
                    revision_resources[revision_id] = lkg
                status = "DEGRADED" if lkg is not None else "BLOCKED"
                resource_states.append(
                    {
                        "resource_revision_id": revision_id,
                        "resource_id": resource_id,
                        "resource_code": str(resource["resource_code"]),
                        "effective_revision_id": (
                            effective_revision_id if lkg else ""
                        ),
                        "status": status,
                        "resolved_secret_versions": {},
                        "last_known_good_generation_id": (
                            previous.generation_id if lkg else ""
                        ),
                        "error_code": "resource_load_failed",
                        "error_summary": self._safe_error(exc),
                    }
                )

        state_by_revision = {
            str(state["resource_revision_id"]): state
            for state in resource_states
        }
        application_states = self._application_states(
            application_bindings,
            state_by_revision=state_by_revision,
            previous=previous,
            generation_id=ticket.id,
        )
        snapshot_metadata = {
            "generation_id": ticket.id,
            "generation_no": ticket.generation_no,
            "published_digest": ticket.published_digest,
            "resources": [
                {
                    key: value
                    for key, value in state.items()
                    if key != "resolved_secret_versions"
                }
                | {
                    "resolved_secret_versions": state[
                        "resolved_secret_versions"
                    ]
                }
                for state in resource_states
            ],
            "applications": application_states,
        }
        canonical = json.dumps(
            snapshot_metadata,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        snapshot_digest = hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()
        snapshot = RuntimeTopologySnapshot(
            topology=topology,
            access_policy=self._access_policy(),
            source="database",
            revision=ticket.generation_no,
            config_hash=ticket.published_digest,
            resource_count=len(resources),
            generation_id=ticket.id,
            generation_no=ticket.generation_no,
            published_digest=ticket.published_digest,
            effective_digest=snapshot_digest,
            revision_resources=revision_resources,
            resource_states=tuple(resource_states),
            application_states=tuple(application_states),
        )
        return RuntimeGenerationBuild(
            snapshot=snapshot,
            snapshot_digest=snapshot_digest,
            snapshot_metadata=snapshot_metadata,
        )

    def _application_states(
        self,
        bindings: list[dict[str, Any]],
        *,
        state_by_revision: dict[str, dict[str, Any]],
        previous: RuntimeTopologySnapshot,
        generation_id: str,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for binding in bindings:
            publication_id = str(
                binding["application_publication_id"]
            )
            item = grouped.setdefault(
                publication_id,
                {
                    "application_publication_id": publication_id,
                    "application_id": str(binding["application_id"]),
                    "application_code": str(binding["application_code"]),
                    "resource_revision_ids": [],
                },
            )
            item["resource_revision_ids"].append(
                str(binding["resource_revision_id"])
            )
        previous_by_application = {
            str(state.get("application_id") or ""): state
            for state in previous.application_states
            if state.get("status") in {"READY", "DEGRADED"}
        }
        result: list[dict[str, Any]] = []
        for publication_id, item in sorted(grouped.items()):
            states = [
                state_by_revision.get(revision_id)
                for revision_id in item["resource_revision_ids"]
            ]
            reasons: list[str] = []
            if any(
                state is None or state["status"] == "BLOCKED"
                for state in states
            ):
                status = "BLOCKED"
                reasons.append("required_resource_unavailable")
            elif any(
                state is not None and state["status"] == "DEGRADED"
                for state in states
            ):
                status = "DEGRADED"
                reasons.append("resource_lkg_retained")
            else:
                status = "READY"
            previous_state = previous_by_application.get(
                str(item["application_id"])
            )
            lkg_generation_id = (
                str(
                    previous_state.get("last_known_good_generation_id")
                    or previous.generation_id
                    or ""
                )
                if previous_state
                else ""
            )
            result.append(
                {
                    "application_publication_id": publication_id,
                    "application_id": str(item["application_id"]),
                    "application_code": str(item["application_code"]),
                    "effective_application_publication_id": (
                        publication_id if status != "BLOCKED" else ""
                    ),
                    "status": status,
                    "last_known_good_generation_id": (
                        generation_id
                        if status == "READY"
                        else lkg_generation_id
                    ),
                    "reason_codes": reasons,
                }
            )
        return result

    def _topology(self) -> Topology:
        bases = self.config_repository.list_bases(
            include_disabled=False
        )
        workshops = self.config_repository.list_workshops(
            include_disabled=False
        )
        workshops_by_base: dict[str, dict[str, Workshop]] = {}
        for workshop in workshops:
            workshops_by_base.setdefault(
                str(workshop["base_id"]),
                {},
            )[str(workshop["code"])] = Workshop(
                code=str(workshop["code"]),
                table_prefix=str(workshop.get("table_prefix") or ""),
                redis_key_prefix=str(
                    workshop.get("redis_key_prefix") or ""
                ),
                loki_label={
                    str(key): str(value)
                    for key, value in (
                        workshop.get("loki_labels") or {}
                    ).items()
                },
                display_name=str(
                    workshop.get("display_name") or ""
                ),
                aliases=tuple(
                    str(value)
                    for value in workshop.get("aliases") or []
                ),
            )
        bases_by_environment: dict[str, dict[str, Base]] = {}
        for base in bases:
            try:
                engine = DatabaseEngine(str(base["engine"]))
            except ValueError:
                continue
            bases_by_environment.setdefault(
                str(base["environment_id"]),
                {},
            )[str(base["code"])] = Base(
                code=str(base["code"]),
                engine=engine,
                workshops=workshops_by_base.get(
                    str(base["id"]),
                    {},
                ),
                display_name=str(base.get("display_name") or ""),
                aliases=tuple(
                    str(value) for value in base.get("aliases") or []
                ),
            )
        environments = {
            str(environment["code"]): Environment(
                code=str(environment["code"]),
                bases=bases_by_environment.get(
                    str(environment["id"]),
                    {},
                ),
                display_name=str(
                    environment.get("display_name") or ""
                ),
                aliases=tuple(
                    str(value)
                    for value in environment.get("aliases") or []
                ),
            )
            for environment in self.config_repository.list_environments(
                include_disabled=False
            )
        }
        return Topology(environments=environments)

    def _access_policy(self) -> Any:
        from .snapshot import PlatformTopologySnapshotBuilder

        return PlatformTopologySnapshotBuilder(
            self.config_repository
        ).build_access_policy()

    def _revision_resource(
        self,
        resource: dict[str, Any],
        projection: dict[str, Any],
    ) -> RevisionResource:
        provider = str(resource["provider_type"])
        kind = ResourceKind(str(resource["resource_kind"]))
        engine = (
            DatabaseEngine(provider)
            if kind is ResourceKind.DATABASE
            else self._scope_engine(resource)
        )
        database = None
        redis = None
        loki = None
        if kind is ResourceKind.DATABASE:
            use_sid = provider == "oracle" and bool(
                projection.get("sid")
            )
            database = DatabaseConnection(
                host=str(projection["host"]),
                port=int(projection["port"]),
                database=str(
                    projection.get("database")
                    or projection.get("service_name")
                    or projection.get("sid")
                    or ""
                ),
                user=str(projection["user"]),
                password=str(projection["password"]),
                schema=str(projection.get("schema") or ""),
                oracle_client_mode=OracleClientMode.THICK,
                oracle_compat=OracleCompat.LEGACY,
                use_sid=use_sid,
            )
        elif kind is ResourceKind.REDIS:
            tls = projection.get("tls") or {}
            redis = RedisConnection(
                host=str(projection["host"]),
                port=int(projection["port"]),
                db=int(projection["db"]),
                username=str(projection.get("username") or ""),
                password=str(projection.get("password") or ""),
                tls_enabled=bool(tls.get("enabled", False)),
                tls_verify_certificate=bool(
                    tls.get("verify_certificate", True)
                ),
            )
        else:
            loki = LokiConnection(
                base_url=str(projection["base_url"]),
                tenant_id=str(projection.get("tenant") or ""),
                auth_token=str(projection.get("auth_token") or ""),
                timeout_seconds=int(projection["timeout_seconds"]),
                max_minutes=int(projection["max_minutes"]),
                max_lines=int(projection["max_lines"]),
                max_response_bytes=int(
                    projection["max_response_bytes"]
                ),
            )
        return RevisionResource(
            resource_revision_id=str(
                resource["resource_revision_id"]
            ),
            resource_id=str(resource["resource_id"]),
            environment_code=str(resource["environment_code"]),
            base_code=str(resource["base_code"]),
            workshop_code=str(resource["workshop_code"]),
            kind=kind,
            engine=engine,
            database=database,
            redis=redis,
            loki=loki,
        )

    def _scope_engine(
        self,
        resource: dict[str, Any],
    ) -> DatabaseEngine:
        base_code = str(resource.get("base_code") or "")
        environment_code = str(resource["environment_code"])
        if base_code:
            base = self.config_repository.get_base_by_code(
                environment_code=environment_code,
                code=base_code,
            )
            if base is not None:
                return DatabaseEngine(str(base["engine"]))
        for base in self.config_repository.list_bases(
            environment_code=environment_code,
            include_disabled=False,
        ):
            try:
                return DatabaseEngine(str(base["engine"]))
            except ValueError:
                continue
        return DatabaseEngine.MYSQL

    def _resolve_nonempty(self, ref: str) -> str:
        value = self.resolver.resolve(ref)
        if not value:
            raise RuntimeError("Required platform Secret is unavailable")
        return value

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        del exc
        return redact_sensitive_text(
            "相关资源加载失败，已保留 Last Known Good 或阻止依赖应用"
        )


class PublishedRuntimeGenerationReloader:
    """Poll published facts and atomically activate complete generations."""

    def __init__(
        self,
        repository: RuntimeGenerationRepository,
        builder: GovernedRuntimeGenerationBuilder,
        target: RuntimeGenerationTarget,
    ) -> None:
        self.repository = repository
        self.builder = builder
        self.target = target
        self._lock = threading.Lock()

    def poll_once(self, *, force: bool = False) -> RuntimeGenerationPollResult:
        with self._lock:
            published_digest = self.repository.published_digest()
            previous = self.target.capture_runtime_snapshot()
            if (
                not force
                and previous.published_digest == published_digest
            ):
                return RuntimeGenerationPollResult(
                    observed=False,
                    activated=False,
                    retained_lkg=False,
                    generation_id=previous.generation_id,
                    generation_no=previous.generation_no,
                    published_digest=published_digest,
                )
            ticket = self.repository.begin_generation(
                published_digest
            )
            try:
                build = self.builder.build(
                    ticket,
                    previous=previous,
                )
                authoritative = ticket
                if not ticket.existing:
                    authoritative = self.repository.activate_generation(
                        ticket,
                        snapshot_digest=build.snapshot_digest,
                        snapshot_metadata=build.snapshot_metadata,
                        resource_states=build.snapshot.resource_states,
                        application_states=(
                            build.snapshot.application_states
                        ),
                    )
                snapshot = build.snapshot
                if authoritative.id != ticket.id:
                    snapshot = replace(
                        snapshot,
                        generation_id=authoritative.id,
                        generation_no=authoritative.generation_no,
                    )
                if not self.target.apply_runtime_snapshot(snapshot):
                    raise RuntimeError(
                        "Runtime target rejected complete generation"
                    )
                retained_lkg = any(
                    state["status"] == "DEGRADED"
                    for state in snapshot.resource_states
                )
                return RuntimeGenerationPollResult(
                    observed=True,
                    activated=True,
                    retained_lkg=retained_lkg,
                    generation_id=authoritative.id,
                    generation_no=authoritative.generation_no,
                    published_digest=published_digest,
                )
            except Exception:
                self.repository.fail_generation(
                    ticket,
                    error_code="runtime_generation_build_failed",
                    error_summary="运行时生成代构建失败，继续使用 Last Known Good",
                )
                return RuntimeGenerationPollResult(
                    observed=True,
                    activated=False,
                    retained_lkg=bool(previous.generation_id),
                    generation_id=previous.generation_id,
                    generation_no=previous.generation_no,
                    published_digest=published_digest,
                    error_code="runtime_generation_build_failed",
                )

    def close(self) -> None:
        self.repository.database.close()
