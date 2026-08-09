from __future__ import annotations

import json
from typing import Any

from ..infrastructure.repository import PlatformConfigRepository


class PlatformSecretUsageService:
    """Read dependency metadata without returning configuration or key material."""

    def __init__(self, repository: PlatformConfigRepository) -> None:
        self.repository = repository

    def dependencies(
        self,
        *,
        secret_id: str,
        secret_ref: str,
    ) -> list[dict[str, Any]]:
        dependencies: list[dict[str, Any]] = []
        dependencies.extend(self._mcp_resource_dependencies(secret_id))
        dependencies.extend(self._connector_dependencies(secret_ref))
        dependencies.extend(self._webhook_dependencies(secret_ref))
        dependencies.extend(self._model_connection_dependencies(secret_id))
        return sorted(
            dependencies,
            key=lambda item: (
                str(item["dependency_type"]),
                str(item["code"]),
                str(item["id"]),
            ),
        )

    def _mcp_resource_dependencies(self, secret_id: str) -> list[dict[str, Any]]:
        rows = self.repository.database.execute(
            """
            select distinct
                   d.id,
                   r.code,
                   r.kind,
                   d.status,
                   rr.revision as resource_revision,
                   g.generation,
                   g.status as generation_status,
                   sv.secret_version
              from mcp_resource_generation_secret_version sv
              join mcp_resource_generation g on g.id = sv.generation_id
              join mcp_resource_deployment d on d.id = g.deployment_id
              join mcp_resource_revision rr on rr.id = g.resource_revision_id
              join mcp_resource r on r.id = d.resource_id
             where sv.secret_id = ?
            """,
            (secret_id,),
        )
        return [
            _dependency(
                dependency_type="mcp_resource_deployment",
                row=row,
                code=str(row["code"]),
                status=str(row["status"]).lower(),
                field_paths=["generation.secret_version"],
                metadata={
                    "resource_kind": str(row["kind"]),
                    "resource_revision": int(row["resource_revision"]),
                    "generation": int(row["generation"]),
                    "generation_status": str(row["generation_status"]),
                    "secret_version": int(row["secret_version"]),
                },
            )
            for row in rows
        ]

    def _connector_dependencies(self, secret_ref: str) -> list[dict[str, Any]]:
        rows = self.repository.database.execute(
            """
            select id, name, connector_type, enabled, secret_ref, endpoint_ref,
                   metadata
            from integration_connector
            """
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            paths: list[str] = []
            for field in ("secret_ref", "endpoint_ref"):
                if row.get(field) == secret_ref:
                    paths.append(field)
            paths.extend(
                f"metadata.{path}"
                for path in _json_reference_paths(
                    row.get("metadata"),
                    secret_ref,
                )
            )
            if paths:
                result.append(
                    _dependency(
                        dependency_type="connector",
                        row=row,
                        code=str(row["name"]),
                        status=("enabled" if bool(int(row.get("enabled") or 0)) else "disabled"),
                        field_paths=paths,
                        metadata={"connector_type": str(row["connector_type"])},
                    )
                )
        return result

    def _webhook_dependencies(self, secret_ref: str) -> list[dict[str, Any]]:
        revisions = self.repository.database.execute(
            """
            select r.id, d.code, r.revision, r.status, r.config_json
            from webhook_trigger_revision r
            join webhook_trigger_definition d on d.id = r.trigger_id
            """
        )
        publications = self.repository.database.execute(
            """
            select p.id, d.code, p.revision, p.status, p.snapshot_json
            from webhook_trigger_publication p
            join webhook_trigger_definition d on d.id = p.trigger_id
            """
        )
        result: list[dict[str, Any]] = []
        for row in revisions:
            paths = _json_reference_paths(row.get("config_json"), secret_ref)
            if paths:
                result.append(
                    _dependency(
                        dependency_type="webhook_revision",
                        row=row,
                        code=str(row["code"]),
                        status=str(row["status"]),
                        field_paths=paths,
                        metadata={"revision": int(row["revision"])},
                    )
                )
        for row in publications:
            paths = _json_reference_paths(
                row.get("snapshot_json"),
                secret_ref,
            )
            if paths:
                result.append(
                    _dependency(
                        dependency_type="webhook_publication",
                        row=row,
                        code=str(row["code"]),
                        status=str(row["status"]),
                        field_paths=paths,
                        metadata={"revision": int(row["revision"])},
                    )
                )
        return result

    def _model_connection_dependencies(
        self,
        secret_id: str,
    ) -> list[dict[str, Any]]:
        rows = self.repository.database.execute(
            """
            select r.id, c.code, r.revision, r.status
            from model_connection_revision r
            join model_connection c on c.id = r.connection_id
            where r.api_key_secret_id = ?
            """,
            (secret_id,),
        )
        return [
            _dependency(
                dependency_type="model_connection_revision",
                row=row,
                code=str(row["code"]),
                status=str(row["status"]),
                field_paths=["api_key_secret_id"],
                metadata={"revision": int(row["revision"])},
            )
            for row in rows
        ]


def _dependency(
    *,
    dependency_type: str,
    row: dict[str, Any],
    code: str,
    status: str,
    field_paths: list[str],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "dependency_type": dependency_type,
        "id": str(row["id"]),
        "code": code,
        "status": status,
        "active": status
        in {
            "active",
            "enabled",
            "ready",
            "published",
            "validated",
            "draft",
        },
        "field_paths": sorted(set(field_paths)),
        "metadata": metadata or {},
    }


def _json_reference_paths(raw: Any, secret_ref: str) -> list[str]:
    if isinstance(raw, str):
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return []
    else:
        value = raw
    return _find_reference_paths(value, secret_ref)


def _find_reference_paths(
    value: Any,
    secret_ref: str,
    *,
    path: str = "",
) -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            paths.extend(
                _find_reference_paths(
                    child,
                    secret_ref,
                    path=child_path,
                )
            )
        return paths
    if isinstance(value, list):
        paths = []
        for index, child in enumerate(value):
            paths.extend(
                _find_reference_paths(
                    child,
                    secret_ref,
                    path=f"{path}[{index}]",
                )
            )
        return paths
    return [path] if value == secret_ref else []
