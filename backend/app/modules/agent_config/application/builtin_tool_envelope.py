from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.internal_tools.domain import (
    HandlerRegistry,
    HandlerRegistryError,
    build_builtin_handler_registry,
)
from app.modules.platform_config.infrastructure.handler_governance_repository import (
    HandlerGovernanceRepository,
)
from app.modules.platform_config.infrastructure.repository import new_id, now_iso
from app.shared.exceptions import NonRetryableExecutionError


class AgentBuiltinToolEnvelopeService:
    def __init__(
        self,
        repository: HandlerGovernanceRepository,
        *,
        registry: HandlerRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry or build_builtin_handler_registry()

    def catalog(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for release in self.repository.list_builtin_releases():
            installation = self.repository.find_builtin_installation(
                str(release["tool_identifier"]),
                str(release["handler_version"]),
            )
            installation_status = str(
                (installation or {}).get("installation_status") or "MISSING"
            )
            implementation_exact = bool(
                installation
                and str(installation.get("implementation_digest") or "")
                == str(release["implementation_digest"])
            )
            try:
                definition = self.registry.require(
                    str(release["tool_identifier"]),
                    str(release["handler_version"]),
                )
                code_exact = (
                    definition.implementation_digest
                    == str(release["implementation_digest"])
                    and definition.public_schema_hash
                    == str(release["public_schema_hash"])
                )
                display_name = definition.display_name
                model_description = definition.description
            except HandlerRegistryError:
                code_exact = False
                display_name = str(release["tool_identifier"])
                model_description = ""
            lifecycle = str(release["status"])
            if lifecycle != "ACTIVE":
                health_status = lifecycle
            elif installation_status != "INSTALLED":
                health_status = installation_status
            elif not implementation_exact or not code_exact:
                health_status = "DRIFTED"
            else:
                health_status = "HEALTHY"
            values.append(
                {
                    **self._public_release(release),
                    "display_name": display_name,
                    "model_description": model_description,
                    "installation_status": installation_status,
                    "health_status": health_status,
                    "selectable": health_status == "HEALTHY",
                }
            )
        values.sort(
            key=lambda item: (
                str(item["tool_identifier"]),
                -int(item.get("release_revision") or 0),
            )
        )
        return values

    def prepare(self, release_ids: object) -> list[dict[str, Any]]:
        if not isinstance(release_ids, list) or any(
            not isinstance(value, str) or not value.strip() for value in release_ids
        ):
            raise self._invalid("Built-in Tool Release IDs must be a non-empty string list")
        normalized_ids = [str(value).strip() for value in release_ids]
        if len(normalized_ids) != len(set(normalized_ids)):
            raise self._invalid("Built-in Tool Release IDs must be unique")
        prepared: list[dict[str, Any]] = []
        identifiers: set[str] = set()
        for release_id in normalized_ids:
            row = self.repository.database.execute_one(
                """
                select release.*, installation.installation_status,
                       installation.implementation_digest as installed_digest,
                       manifest.manifest_json
                  from builtin_tool_release release
                  left join builtin_tool_installation installation
                    on installation.tool_identifier = release.tool_identifier
                   and installation.handler_version = release.handler_version
                  left join builtin_tool_manifest_projection manifest
                    on manifest.tool_identifier = release.tool_identifier
                   and manifest.handler_version = release.handler_version
                   and manifest.implementation_digest = release.implementation_digest
                 where release.id = ?
                """,
                (release_id,),
            )
            if (
                row is None
                or str(row["status"]) != "ACTIVE"
                or str(row.get("installation_status") or "") != "INSTALLED"
                or str(row.get("installed_digest") or "") != str(row["implementation_digest"])
                or not row.get("manifest_json")
            ):
                raise self._invalid(
                    "Built-in Tool Release is not ACTIVE with an exact installed implementation"
                )
            identifier = str(row["tool_identifier"])
            try:
                definition = self.registry.require(
                    identifier,
                    str(row["handler_version"]),
                )
            except HandlerRegistryError as exc:
                raise self._invalid(
                    "Built-in Tool Release implementation is missing from code"
                ) from exc
            if definition.implementation_digest != str(
                row["implementation_digest"]
            ) or definition.public_schema_hash != str(row["public_schema_hash"]):
                raise self._invalid("Built-in Tool Release implementation does not match code")
            if identifier in identifiers:
                raise self._invalid("Agent Draft selects multiple Releases for one Tool Identifier")
            identifiers.add(identifier)
            manifest = json.loads(str(row["manifest_json"]))
            envelope = {
                "tool_identifier": identifier,
                "tool_release_id": str(row["id"]),
                "handler_version": str(row["handler_version"]),
                "implementation_digest": str(row["implementation_digest"]),
                "public_schema_hash": str(row["public_schema_hash"]),
                "model_description": str(manifest.get("description") or ""),
            }
            envelope["envelope_hash"] = _hash(envelope)
            prepared.append(envelope)
        prepared.sort(key=lambda item: str(item["tool_identifier"]))
        return prepared

    def freeze(
        self,
        *,
        agent_publication_id: str,
        envelopes: list[dict[str, Any]],
    ) -> None:
        timestamp = now_iso()
        for envelope in envelopes:
            self.repository.database.execute(
                """
                insert into agent_publication_builtin_tool
                  (id, agent_publication_id, tool_identifier, tool_release_id,
                   handler_version, implementation_digest, public_schema_hash,
                   model_description, envelope_hash, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict do nothing
                """,
                (
                    new_id("agent_publication_builtin_tool"),
                    agent_publication_id,
                    envelope["tool_identifier"],
                    envelope["tool_release_id"],
                    envelope["handler_version"],
                    envelope["implementation_digest"],
                    envelope["public_schema_hash"],
                    envelope["model_description"],
                    envelope["envelope_hash"],
                    timestamp,
                ),
            )
        self.verify_frozen(
            agent_publication_id=agent_publication_id,
            envelopes=envelopes,
        )

    def verify_frozen(
        self,
        *,
        agent_publication_id: str,
        envelopes: list[dict[str, Any]],
    ) -> None:
        expected = _canonical_envelopes(envelopes)
        actual = _canonical_envelopes(self.facts(agent_publication_id))
        if actual != expected:
            raise NonRetryableExecutionError(
                "Agent publication Built-in Tool Envelope mismatch",
                safe_message="Agent 内置工具发布事实完整性校验失败",
                error_code="agent_builtin_tool_envelope_hash_mismatch",
            )

    def facts(self, agent_publication_id: str) -> list[dict[str, Any]]:
        facts = [
            {
                "tool_identifier": str(row["tool_identifier"]),
                "tool_release_id": str(row["tool_release_id"]),
                "handler_version": str(row["handler_version"]),
                "implementation_digest": str(row["implementation_digest"]),
                "public_schema_hash": str(row["public_schema_hash"]),
                "model_description": str(row["model_description"]),
                "envelope_hash": str(row["envelope_hash"]),
            }
            for row in self.repository.database.execute(
                """
                select tool_identifier, tool_release_id, handler_version,
                       implementation_digest, public_schema_hash,
                       model_description, envelope_hash
                  from agent_publication_builtin_tool
                 where agent_publication_id = ?
                 order by tool_identifier
                """,
                (agent_publication_id,),
            )
        ]
        return _canonical_envelopes(facts)

    @staticmethod
    def _public_release(release: dict[str, Any]) -> dict[str, Any]:
        return {
            key: release[key]
            for key in (
                "id",
                "tool_identifier",
                "release_revision",
                "tool_semantic_version",
                "handler_version",
                "implementation_digest",
                "public_schema_hash",
                "status",
            )
        }

    @staticmethod
    def _invalid(message: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            message,
            safe_message="Agent 内置工具必须选择唯一且当前可调用的 ACTIVE Release",
            error_code="agent_builtin_tool_envelope_invalid",
        )


def _hash(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_envelopes(
    envelopes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # SQL ORDER BY follows the database collation, which can order underscores
    # differently from Python. Integrity comparison must be dialect-independent.
    return sorted(
        (dict(envelope) for envelope in envelopes),
        key=lambda item: str(item["tool_identifier"]),
    )
