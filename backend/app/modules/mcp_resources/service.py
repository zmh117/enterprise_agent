from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlparse

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound


_CODE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_SECRET_REF = re.compile(r"^secret://platform/[a-z][a-z0-9_-]{1,63}$")
_ROOT_FIELDS = frozenset({"api_version", "kind", "metadata", "spec"})
_METADATA_FIELDS = frozenset({"code", "name"})
_SPEC_FIELDS = {
    "DATABASE": frozenset(
        {
            "provider",
            "host",
            "port",
            "database",
            "schema",
            "username",
            "password_ref",
            "allowed_tables",
            "max_rows",
            "timeout_seconds",
            "tls",
        }
    ),
    "REDIS": frozenset(
        {
            "host",
            "port",
            "database",
            "username",
            "password_ref",
            "key_prefixes",
            "scan_limit",
            "timeout_seconds",
            "tls",
        }
    ),
    "LOKI": frozenset(
        {
            "base_url",
            "tenant_id",
            "auth_ref",
            "label_scope",
            "max_minutes",
            "max_lines",
            "timeout_seconds",
        }
    ),
}


Verifier = Callable[[dict[str, Any]], dict[str, Any]]


class McpResourceService:
    """Small declarative Resource control plane; no provider commands are model-visible."""

    def __init__(
        self,
        database: Database,
        *,
        audit_service: AuditService | None = None,
        verifier: Verifier | None = None,
    ) -> None:
        self.database = database
        self.audit_service = audit_service
        self.verifier = verifier or self._configuration_verifier

    def plan(self, manifest: dict[str, Any]) -> dict[str, Any]:
        canonical, content_hash, refs = validate_manifest(manifest)
        code = canonical["metadata"]["code"]
        resource = self.database.execute_one("select * from mcp_resource where code = ?", (code,))
        current = self.database.execute_one(
            """
            select rr.* from mcp_resource_revision rr
              join mcp_resource r on r.id = rr.resource_id
             where r.code = ? order by rr.revision desc limit 1
            """,
            (code,),
        )
        current_manifest = _object((current or {}).get("manifest_json"))
        return {
            "code": code,
            "kind": canonical["kind"],
            "action": "CREATE"
            if resource is None
            else ("NOOP" if current and current["content_hash"] == content_hash else "UPDATE"),
            "expected_revision": int((resource or {}).get("revision") or 0),
            "content_hash": content_hash,
            "changed_paths": _changed_paths(current_manifest, canonical),
            "secret_refs": ["secret://platform/<redacted>" for _ in refs],
        }

    def apply(
        self,
        manifest: dict[str, Any],
        *,
        actor_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        canonical, content_hash, _ = validate_manifest(manifest)
        request_hash = _hash({"manifest": canonical, "expected_revision": expected_revision})
        replay = self._idempotent(idempotency_key, "resource.apply", actor_id, request_hash)
        if replay is not None:
            return replay
        code = canonical["metadata"]["code"]
        timestamp = now_iso()
        with self.database.unit_of_work():
            resource = self.database.execute_one(
                "select * from mcp_resource where code = ?", (code,)
            )
            if resource is None:
                if expected_revision not in {0, 1}:
                    raise self._conflict()
                resource_id = new_id("mcp_resource")
                resource_revision = 1
                self.database.execute(
                    """
                    insert into mcp_resource
                      (id, code, kind, name, lifecycle_status, revision,
                       created_by, created_at, updated_at)
                    values (?, ?, ?, ?, 'ENABLED', 1, ?, ?, ?)
                    """,
                    (
                        resource_id,
                        code,
                        canonical["kind"],
                        canonical["metadata"]["name"],
                        actor_id,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                if int(resource["revision"]) != expected_revision:
                    raise self._conflict()
                if str(resource["kind"]) != canonical["kind"]:
                    raise NonRetryableExecutionError(
                        "Resource kind is immutable",
                        safe_message="资源类型不可变更",
                        error_code="mcp_resource_kind_immutable",
                    )
                resource_id = str(resource["id"])
                resource_revision = expected_revision + 1
                rows = self.database.execute(
                    """
                    update mcp_resource
                       set name = ?, revision = revision + 1, updated_at = ?
                     where id = ? and revision = ?
                    returning id
                    """,
                    (
                        canonical["metadata"]["name"],
                        timestamp,
                        resource_id,
                        expected_revision,
                    ),
                )
                if not rows:
                    raise self._conflict()
            self.database.execute(
                """
                update mcp_resource_draft set status = 'DISCARDED', updated_at = ?
                 where resource_id = ? and status in ('DRAFT', 'VERIFIED')
                """,
                (timestamp, resource_id),
            )
            draft_no = self.database.execute_one(
                "select coalesce(max(draft_revision), 0) + 1 as value from mcp_resource_draft where resource_id = ?",
                (resource_id,),
            )
            assert draft_no is not None
            draft_id = new_id("mcp_resource_draft")
            self.database.execute(
                """
                insert into mcp_resource_draft
                  (id, resource_id, draft_revision, manifest_json, content_hash,
                   status, expected_resource_revision, created_by, created_at, updated_at)
                values (?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    resource_id,
                    int(draft_no["value"]),
                    _canonical_json(canonical),
                    content_hash,
                    resource_revision,
                    actor_id,
                    timestamp,
                    timestamp,
                ),
            )
            response = {
                "resource_id": resource_id,
                "code": code,
                "draft_id": draft_id,
                "status": "DRAFT",
                "revision": resource_revision,
                "content_hash": content_hash,
            }
            self._remember(idempotency_key, "resource.apply", actor_id, request_hash, response)
        self._audit("mcp.resource.applied", actor_id, response)
        return response

    def verify(self, code: str, *, actor_id: str, expected_revision: int) -> dict[str, Any]:
        resource, draft = self._open_draft(code)
        if int(resource["revision"]) != expected_revision:
            raise self._conflict()
        manifest = _object(draft["manifest_json"])
        refs = validate_manifest(manifest)[2]
        secret_versions = self._active_secret_versions(refs)
        safe_summary = self.verifier(manifest)
        if any(_looks_sensitive(key) for key in _walk_keys(safe_summary)):
            raise NonRetryableExecutionError(
                "Verifier returned a sensitive summary",
                safe_message="资源验证摘要不安全",
                error_code="mcp_resource_verification_summary_unsafe",
            )
        timestamp = now_iso()
        verification_id = new_id("mcp_resource_verification")
        with self.database.unit_of_work():
            self.database.execute(
                """
                insert into mcp_resource_verification
                  (id, draft_id, content_hash, status, safe_summary_json,
                   verified_by, verified_at)
                values (?, ?, ?, 'PASSED', ?, ?, ?)
                """,
                (
                    verification_id,
                    draft["id"],
                    draft["content_hash"],
                    _canonical_json(safe_summary),
                    actor_id,
                    timestamp,
                ),
            )
            self.database.execute(
                "update mcp_resource_draft set status = 'VERIFIED', updated_at = ? where id = ? and status = 'DRAFT'",
                (timestamp, draft["id"]),
            )
        response = {
            "code": code,
            "draft_id": draft["id"],
            "verification_id": verification_id,
            "status": "PASSED",
            "content_hash": draft["content_hash"],
            "secret_version_count": len(secret_versions),
            "safe_summary": safe_summary,
        }
        self._audit("mcp.resource.verified", actor_id, response)
        return response

    def publish(
        self,
        code: str,
        *,
        actor_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        resource, draft = self._open_draft(code, required_status="VERIFIED")
        if int(resource["revision"]) != expected_revision:
            raise self._conflict()
        request_hash = _hash(
            {"code": code, "draft": draft["id"], "expected_revision": expected_revision}
        )
        replay = self._idempotent(idempotency_key, "resource.publish", actor_id, request_hash)
        if replay is not None:
            return replay
        verification = self.database.execute_one(
            "select * from mcp_resource_verification where draft_id = ? and content_hash = ? and status = 'PASSED'",
            (draft["id"], draft["content_hash"]),
        )
        if verification is None:
            raise NonRetryableExecutionError(
                "Resource verification is missing or stale",
                safe_message="资源验证缺失或已失效",
                error_code="mcp_resource_verification_stale",
            )
        manifest = _object(draft["manifest_json"])
        secret_versions = self._active_secret_versions(validate_manifest(manifest)[2])
        timestamp = now_iso()
        with self.database.unit_of_work():
            revision_no_row = self.database.execute_one(
                "select coalesce(max(revision), 0) + 1 as value from mcp_resource_revision where resource_id = ?",
                (resource["id"],),
            )
            assert revision_no_row is not None
            revision_id = new_id("mcp_resource_revision")
            self.database.execute(
                """
                insert into mcp_resource_revision
                  (id, resource_id, revision, kind, manifest_json, content_hash,
                   verification_id, revision_status, published_by, published_at)
                values (?, ?, ?, ?, ?, ?, ?, 'PUBLISHED', ?, ?)
                """,
                (
                    revision_id,
                    resource["id"],
                    int(revision_no_row["value"]),
                    resource["kind"],
                    draft["manifest_json"],
                    draft["content_hash"],
                    verification["id"],
                    actor_id,
                    timestamp,
                ),
            )
            deployment = self.database.execute_one(
                "select * from mcp_resource_deployment where resource_id = ? and server_code = 'data-mcp' order by revision desc limit 1",
                (resource["id"],),
            )
            if deployment is None:
                deployment_id = new_id("mcp_resource_deployment")
                deployment_revision = 1
                self.database.execute(
                    """
                    insert into mcp_resource_deployment
                      (id, resource_id, server_code, resource_revision_id, status,
                       revision, current_generation_id, last_known_good_generation_id,
                       updated_by, created_at, updated_at)
                    values (?, ?, 'data-mcp', ?, 'ACTIVE', 1, '', '', ?, ?, ?)
                    """,
                    (deployment_id, resource["id"], revision_id, actor_id, timestamp, timestamp),
                )
            else:
                deployment_id = str(deployment["id"])
                deployment_revision = int(deployment["revision"]) + 1
                self.database.execute(
                    """
                    update mcp_resource_deployment
                       set resource_revision_id = ?, status = 'ACTIVE',
                           revision = revision + 1, current_generation_id = '',
                           last_known_good_generation_id = '', updated_by = ?, updated_at = ?
                     where id = ?
                    """,
                    (revision_id, actor_id, timestamp, deployment_id),
                )
            self.database.execute(
                """
                update mcp_resource_generation
                   set status = 'FAILED', safe_error_code = 'superseded_before_activation'
                 where deployment_id = ? and status in ('BUILDING', 'VERIFYING')
                """,
                (deployment_id,),
            )
            generation_id = self._insert_generation(
                deployment_id=deployment_id,
                resource_revision_id=revision_id,
                secret_versions=secret_versions,
                timestamp=timestamp,
            )
            rows = self.database.execute(
                "update mcp_resource set revision = revision + 1, updated_at = ? where id = ? and revision = ? returning id",
                (timestamp, resource["id"], expected_revision),
            )
            if not rows:
                raise self._conflict()
            response = {
                "code": code,
                "resource_revision_id": revision_id,
                "resource_revision": int(revision_no_row["value"]),
                "deployment_id": deployment_id,
                "deployment_revision": deployment_revision,
                "generation_id": generation_id,
                "generation_status": "BUILDING",
                "revision": expected_revision + 1,
            }
            self._remember(idempotency_key, "resource.publish", actor_id, request_hash, response)
        self._audit("mcp.resource.published", actor_id, response)
        return response

    def unpublish(self, code: str, *, actor_id: str, expected_revision: int) -> dict[str, Any]:
        resource = self._resource(code)
        if int(resource["revision"]) != expected_revision:
            raise self._conflict()
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                "update mcp_resource set revision = revision + 1, updated_at = ? where id = ? and revision = ? returning id",
                (timestamp, resource["id"], expected_revision),
            )
            if not rows:
                raise self._conflict()
            self.database.execute(
                """
                update mcp_resource_deployment
                   set status = 'DISABLED', revision = revision + 1,
                       current_generation_id = '', updated_by = ?, updated_at = ?
                 where resource_id = ? and status = 'ACTIVE'
                """,
                (actor_id, timestamp, resource["id"]),
            )
        response = {"code": code, "status": "DISABLED", "revision": expected_revision + 1}
        self._audit("mcp.resource.unpublished", actor_id, response)
        return response

    def activate_generation(
        self,
        generation_id: str,
        *,
        success: bool,
        safe_error_code: str = "",
    ) -> dict[str, Any]:
        generation = self.database.execute_one(
            "select * from mcp_resource_generation where id = ?", (generation_id,)
        )
        if generation is None or str(generation["status"]) not in {
            "BUILDING",
            "VERIFYING",
        }:
            raise NotFound("MCP Resource generation is not buildable")
        timestamp = now_iso()
        with self.database.unit_of_work():
            deployment = self.database.execute_one(
                "select * from mcp_resource_deployment where id = ?",
                (generation["deployment_id"],),
            )
            if deployment is None or str(deployment["status"]) != "ACTIVE":
                success = False
                safe_error_code = "deployment_inactive"
            elif success and str(deployment["resource_revision_id"]) == str(
                generation["resource_revision_id"]
            ):
                self.database.execute(
                    """
                    update mcp_resource_generation set status = 'SUPERSEDED'
                     where deployment_id = ? and status = 'ACTIVE' and id != ?
                    """,
                    (generation["deployment_id"], generation_id),
                )
                self.database.execute(
                    "update mcp_resource_generation set status = 'ACTIVE', activated_at = ?, safe_error_code = '' where id = ?",
                    (timestamp, generation_id),
                )
                self.database.execute(
                    """
                    update mcp_resource_deployment
                       set current_generation_id = ?, last_known_good_generation_id = ?, updated_at = ?
                     where id = ? and status = 'ACTIVE' and resource_revision_id = ?
                    """,
                    (
                        generation_id,
                        generation_id,
                        timestamp,
                        generation["deployment_id"],
                        generation["resource_revision_id"],
                    ),
                )
                status = "ACTIVE"
            else:
                self.database.execute(
                    "update mcp_resource_generation set status = 'FAILED', safe_error_code = ? where id = ?",
                    ((safe_error_code or "generation_build_failed")[:128], generation_id),
                )
                status = "FAILED"
        return {"generation_id": generation_id, "status": status}

    def status(self, code: str) -> dict[str, Any]:
        resource = self._resource(code)
        draft = self.database.execute_one(
            """
            select id, draft_revision, status, content_hash, updated_at
              from mcp_resource_draft
             where resource_id = ? and status in ('DRAFT', 'VERIFIED')
             order by draft_revision desc limit 1
            """,
            (resource["id"],),
        )
        verification = (
            self.database.execute_one(
                """
                select status, verified_at
                  from mcp_resource_verification
                 where draft_id = ?
                 order by verified_at desc limit 1
                """,
                (draft["id"],),
            )
            if draft is not None
            else None
        )
        deployment = self.database.execute_one(
            """
            select d.*,
                   current.status as current_generation_status,
                   current.resource_revision_id as current_generation_revision_id,
                   current.safe_error_code as current_safe_error_code,
                   latest.status as latest_generation_status,
                   latest.safe_error_code as latest_safe_error_code
              from mcp_resource_deployment d
              left join mcp_resource_generation current
                on current.id = d.current_generation_id
              left join mcp_resource_generation latest
                on latest.id = (
                  select candidate.id
                    from mcp_resource_generation candidate
                   where candidate.deployment_id = d.id
                     and candidate.resource_revision_id = d.resource_revision_id
                   order by candidate.generation desc
                   limit 1
                )
             where d.resource_id = ? order by d.revision desc limit 1
            """,
            (resource["id"],),
        )
        generation_status = "UNAVAILABLE"
        safe_error_code = ""
        if deployment and str(deployment["status"]) == "ACTIVE":
            latest_status = str(deployment.get("latest_generation_status") or "")
            current_status = str(deployment.get("current_generation_status") or "")
            current_is_exact_lkg = current_status == "ACTIVE" and str(
                deployment.get("current_generation_revision_id") or ""
            ) == str(deployment["resource_revision_id"])
            if latest_status == "FAILED" and current_is_exact_lkg:
                generation_status = "DEGRADED"
                safe_error_code = str(deployment.get("latest_safe_error_code") or "")
            elif latest_status in {"BUILDING", "VERIFYING", "FAILED"}:
                generation_status = latest_status
                safe_error_code = str(deployment.get("latest_safe_error_code") or "")
            elif current_is_exact_lkg:
                generation_status = "ACTIVE"
                safe_error_code = str(deployment.get("current_safe_error_code") or "")
        return {
            "code": code,
            "kind": resource["kind"],
            "lifecycle_status": resource["lifecycle_status"],
            "revision": resource["revision"],
            "resource": {
                "id": resource["id"],
                "code": code,
                "name": resource["name"],
                "kind": resource["kind"],
                "lifecycle_status": resource["lifecycle_status"],
                "revision": resource["revision"],
            },
            "draft": (
                {
                    "id": draft["id"],
                    "revision": draft["draft_revision"],
                    "status": draft["status"],
                    "content_hash": draft["content_hash"],
                    "updated_at": draft["updated_at"],
                }
                if draft
                else None
            ),
            "verification": (
                {
                    "status": verification["status"],
                    "verified_at": verification["verified_at"],
                }
                if verification
                else None
            ),
            "deployment": (
                {
                    "id": deployment["id"],
                    "status": deployment["status"],
                    "revision": deployment["revision"],
                    "resource_revision_id": deployment["resource_revision_id"],
                    "generation_status": generation_status,
                    "safe_error_code": safe_error_code,
                }
                if deployment
                else None
            ),
        }

    def list_status(self) -> list[dict[str, Any]]:
        rows = self.database.execute("select code from mcp_resource order by code")
        return [self.status(str(row["code"])) for row in rows]

    def draft_from_revision(
        self,
        code: str,
        resource_revision_id: str,
        *,
        actor_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        revision = self.database.execute_one(
            """
            select rr.manifest_json
              from mcp_resource_revision rr
              join mcp_resource r on r.id = rr.resource_id
             where r.code = ? and rr.id = ?
            """,
            (code, resource_revision_id),
        )
        if revision is None:
            raise NotFound(
                "MCP Resource Revision not found",
                safe_message="资源版本不存在",
            )
        return self.apply(
            _object(revision["manifest_json"]),
            actor_id=actor_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )

    def _insert_generation(
        self,
        *,
        deployment_id: str,
        resource_revision_id: str,
        secret_versions: list[dict[str, Any]],
        timestamp: str,
    ) -> str:
        generation_no = self.database.execute_one(
            "select coalesce(max(generation), 0) + 1 as value from mcp_resource_generation where deployment_id = ?",
            (deployment_id,),
        )
        assert generation_no is not None
        generation_id = new_id("mcp_resource_generation")
        digest = _hash({str(item["id"]): int(item["active_version"]) for item in secret_versions})
        self.database.execute(
            """
            insert into mcp_resource_generation
              (id, deployment_id, resource_revision_id, generation,
               secret_versions_hash, status, safe_error_code, created_at)
            values (?, ?, ?, ?, ?, 'BUILDING', '', ?)
            """,
            (
                generation_id,
                deployment_id,
                resource_revision_id,
                int(generation_no["value"]),
                digest,
                timestamp,
            ),
        )
        for secret in secret_versions:
            self.database.execute(
                """
                insert into mcp_resource_generation_secret_version
                  (generation_id, secret_id, secret_version)
                values (?, ?, ?)
                """,
                (generation_id, secret["id"], int(secret["active_version"])),
            )
        return generation_id

    def _active_secret_versions(self, refs: tuple[str, ...]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for ref in refs:
            row = self.database.execute_one(
                """
                select s.id, s.active_version, s.status, v.status as version_status
                  from platform_secret s
                  join platform_secret_version v
                    on v.secret_id = s.id and v.version = s.active_version
                 where s.ref = ?
                """,
                (ref,),
            )
            if (
                row is None
                or str(row["status"]) != "enabled"
                or str(row["version_status"]) != "active"
            ):
                raise NonRetryableExecutionError(
                    "Resource secret is unavailable",
                    safe_message="资源引用的凭据缺失或已停用",
                    error_code="mcp_resource_secret_unavailable",
                )
            rows.append(row)
        return rows

    def _resource(self, code: str) -> dict[str, Any]:
        row = self.database.execute_one("select * from mcp_resource where code = ?", (code,))
        if row is None:
            raise NotFound("MCP Resource not found", safe_message="资源不存在")
        return row

    def _open_draft(
        self, code: str, *, required_status: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        resource = self._resource(code)
        statuses = (required_status,) if required_status else ("DRAFT", "VERIFIED")
        placeholders = ",".join("?" for _ in statuses)
        draft = self.database.execute_one(
            f"select * from mcp_resource_draft where resource_id = ? and status in ({placeholders}) order by draft_revision desc limit 1",
            (resource["id"], *statuses),
        )
        if draft is None:
            raise NotFound("Open MCP Resource draft not found", safe_message="资源草稿不存在")
        return resource, draft

    def _idempotent(
        self, key: str, operation: str, actor_id: str, request_hash: str
    ) -> dict[str, Any] | None:
        if not key or len(key) > 128:
            raise ValueError("Idempotency key is required and must be bounded")
        row = self.database.execute_one(
            "select * from mcp_operation_idempotency where idempotency_key = ?", (key,)
        )
        if row is None:
            return None
        if any(
            (
                str(row["operation"]) != operation,
                str(row["actor_id"]) != actor_id,
                str(row["request_hash"]) != request_hash,
            )
        ):
            raise NonRetryableExecutionError(
                "MCP idempotency key conflicts with another request",
                safe_message="重复请求与原请求不一致",
                error_code="mcp_idempotency_conflict",
            )
        return _object(row["response_json"])

    def _remember(
        self,
        key: str,
        operation: str,
        actor_id: str,
        request_hash: str,
        response: dict[str, Any],
    ) -> None:
        self.database.execute(
            """
            insert into mcp_operation_idempotency
              (idempotency_key, operation, actor_id, request_hash, response_json, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (key, operation, actor_id, request_hash, _canonical_json(response), now_iso()),
        )

    def _audit(self, event: str, actor_id: str, payload: dict[str, Any]) -> None:
        if self.audit_service is not None:
            self.audit_service.record(
                event,
                status="SUCCEEDED",
                summary=event.replace(".", " "),
                actor_id=actor_id,
                payload=payload,
            )

    @staticmethod
    def _configuration_verifier(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": manifest["kind"],
            "configuration": "valid",
            "provider_query_executed": False,
        }

    @staticmethod
    def _conflict() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "MCP Resource revision conflict",
            safe_message="资源已被其他操作更新，请刷新后重试",
            error_code="revision_conflict",
        )


def validate_manifest(
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], str, tuple[str, ...]]:
    if not isinstance(manifest, dict) or set(manifest) - _ROOT_FIELDS:
        raise ValueError("Manifest root contains unknown fields")
    if set(manifest) != _ROOT_FIELDS:
        raise ValueError("Manifest root fields are incomplete")
    if manifest.get("api_version") != "enterprise-agent/v1":
        raise ValueError("Unsupported Resource manifest api_version")
    kind = str(manifest.get("kind") or "").upper()
    if kind not in _SPEC_FIELDS:
        raise ValueError("Unsupported Resource kind")
    metadata = manifest.get("metadata")
    spec = manifest.get("spec")
    if not isinstance(metadata, dict) or set(metadata) != _METADATA_FIELDS:
        raise ValueError("Resource metadata is invalid")
    if not isinstance(spec, dict) or set(spec) - _SPEC_FIELDS[kind]:
        raise ValueError("Resource spec contains unknown fields")
    code = str(metadata.get("code") or "")
    name = str(metadata.get("name") or "").strip()
    if not _CODE.fullmatch(code) or not 1 <= len(name) <= 128:
        raise ValueError("Resource metadata is invalid")
    normalized = {
        "api_version": "enterprise-agent/v1",
        "kind": kind,
        "metadata": {"code": code, "name": name},
        "spec": dict(spec),
    }
    refs: list[str] = []
    if kind == "DATABASE":
        _require_fields(
            spec,
            {
                "provider",
                "host",
                "port",
                "database",
                "username",
                "password_ref",
                "allowed_tables",
                "max_rows",
                "timeout_seconds",
            },
        )
        if str(spec["provider"]) not in {"mysql", "postgresql", "sqlserver", "oracle"}:
            raise ValueError("Database provider is invalid")
        _host_port(spec)
        if not isinstance(spec["allowed_tables"], list) or not spec["allowed_tables"]:
            raise ValueError("Database allowed_tables is required")
        if not 1 <= int(spec["max_rows"]) <= 1000 or not 1 <= int(spec["timeout_seconds"]) <= 30:
            raise ValueError("Database limits are invalid")
        refs.append(_validate_secret_ref(spec["password_ref"]))
    elif kind == "REDIS":
        _require_fields(
            spec, {"host", "port", "database", "key_prefixes", "scan_limit", "timeout_seconds"}
        )
        _host_port(spec)
        if not 0 <= int(spec["database"]) <= 15:
            raise ValueError("Redis database is invalid")
        if not isinstance(spec["key_prefixes"], list) or not spec["key_prefixes"]:
            raise ValueError("Redis key_prefixes is required")
        if not 1 <= int(spec["scan_limit"]) <= 500 or not 1 <= int(spec["timeout_seconds"]) <= 30:
            raise ValueError("Redis limits are invalid")
        if spec.get("password_ref"):
            refs.append(_validate_secret_ref(spec["password_ref"]))
    else:
        _require_fields(
            spec, {"base_url", "label_scope", "max_minutes", "max_lines", "timeout_seconds"}
        )
        parsed = urlparse(str(spec["base_url"]))
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Loki base_url is invalid")
        if not isinstance(spec["label_scope"], dict) or not spec["label_scope"]:
            raise ValueError("Loki label_scope is required")
        if not 1 <= int(spec["max_minutes"]) <= 1440 or not 1 <= int(spec["max_lines"]) <= 5000:
            raise ValueError("Loki limits are invalid")
        if spec.get("auth_ref"):
            refs.append(_validate_secret_ref(spec["auth_ref"]))
    for key in _walk_keys(spec):
        if _looks_sensitive(key) and not key.endswith("_ref"):
            raise ValueError("Plaintext sensitive manifest field is forbidden")
    for value in _walk_values(spec):
        if isinstance(value, str) and value.startswith(("env:", "vault:", "kms:")):
            raise ValueError("Unsupported secret provider")
    canonical = json.loads(_canonical_json(normalized))
    return (
        canonical,
        hashlib.sha256(_canonical_json(canonical).encode()).hexdigest(),
        tuple(sorted(set(refs))),
    )


def _validate_secret_ref(value: Any) -> str:
    ref = str(value or "")
    if not _SECRET_REF.fullmatch(ref):
        raise ValueError("Only secret://platform references are allowed")
    return ref


def _require_fields(value: dict[str, Any], fields: set[str]) -> None:
    if not fields <= set(value):
        raise ValueError("Resource spec fields are incomplete")


def _host_port(value: dict[str, Any]) -> None:
    if not str(value.get("host") or "").strip() or not 1 <= int(value.get("port") or 0) <= 65535:
        raise ValueError("Resource host or port is invalid")


def _walk_keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _walk_values(value: Any) -> Iterator[Any]:
    if isinstance(value, dict):
        for child in value.values():
            yield child
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield child
            yield from _walk_values(child)


def _looks_sensitive(key: str) -> bool:
    return any(
        part in key.lower()
        for part in ("password", "token", "secret", "credential", "authorization")
    )


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _changed_paths(before: dict[str, Any], after: dict[str, Any], prefix: str = "") -> list[str]:
    paths: list[str] = []
    for key in sorted(set(before) | set(after)):
        path = f"{prefix}.{key}" if prefix else key
        left, right = before.get(key), after.get(key)
        if isinstance(left, dict) and isinstance(right, dict):
            paths.extend(_changed_paths(left, right, path))
        elif left != right:
            paths.append(path)
    return paths
