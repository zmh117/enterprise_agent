from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.agent.domain.runtime import McpRuntimeBinding, McpUnavailableNotice
from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError
from services.mcp_common import get_catalog_entry


_ONES_REVERIFY_MESSAGE = "ONES 查询暂不可用，请在本人身份页面重新验证 ONES 并确认默认 Team。"
_DATA_UNAVAILABLE_MESSAGE = "数据诊断工具暂不可用，请联系管理员检查资源发布状态。"


class McpJobBindingService:
    """Freezes and revalidates exact per-Job MCP publication facts."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def freeze(self, job: AgentJob) -> tuple[McpRuntimeBinding, ...]:
        existing = self.database.execute_one(
            "select id from mcp_job_subject_snapshot where job_id = ?",
            (job.id,),
        )
        if existing is not None:
            return self.eligible_bindings(job.id, require_running=False)[0]
        app_user_id = job.internal_user_id or job.user_id
        publications = self.database.execute(
            """
            select p.* from mcp_tool_publication p
              join agent_publication_mcp_tool a
                on a.tool_publication_id = p.id
              join business_application_publication_mcp_tool b
                on b.tool_publication_id = p.id
             where a.agent_publication_id = ?
               and b.application_publication_id = ?
               and p.status = 'PUBLISHED'
             order by p.server_code, p.tool_name, p.resource_code
            """,
            (job.agent_publication_id, job.business_application_publication_id or ""),
        )
        subject = self._subject(app_user_id)
        subject_payload = {
            "job_id": job.id,
            "app_user_id": app_user_id,
            "external_identity_id": str((subject or {}).get("id") or ""),
            "external_subject": str((subject or {}).get("external_subject_id") or ""),
            "provider_instance_id": str((subject or {}).get("provider_instance_id") or ""),
            "default_team_id": str(
                _json_object((subject or {}).get("metadata_json")).get("default_team_id") or ""
            ),
            "binding_revision": int((subject or {}).get("binding_revision") or 0),
        }
        timestamp = now_iso()
        subject_id = new_id("mcp_subject_snapshot")
        with self.database.unit_of_work():
            self.database.execute(
                """
                insert into mcp_job_subject_snapshot
                  (id, job_id, app_user_id, external_identity_id,
                   external_subject, provider_instance_id, default_team_id,
                   binding_revision, snapshot_hash, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subject_id,
                    subject_payload["job_id"],
                    subject_payload["app_user_id"],
                    subject_payload["external_identity_id"],
                    subject_payload["external_subject"],
                    subject_payload["provider_instance_id"],
                    subject_payload["default_team_id"],
                    subject_payload["binding_revision"],
                    _hash(subject_payload),
                    timestamp,
                ),
            )
            for publication in publications:
                status, reason, deployment = self._initial_eligibility(
                    publication=publication,
                    app_user_id=app_user_id,
                    subject=subject,
                )
                payload = {
                    "job_id": job.id,
                    "tool_publication_id": str(publication["id"]),
                    "server_code": str(publication["server_code"]),
                    "tool_name": str(publication["tool_name"]),
                    "required_scope": str(publication["required_scope"]),
                    "tool_schema_hash": str(publication["tool_schema_hash"]),
                    "resource_code": str(publication.get("resource_code") or ""),
                    "resource_deployment_id": str((deployment or {}).get("id") or ""),
                    "resource_revision_id": str(
                        (deployment or {}).get("resource_revision_id") or ""
                    ),
                    "status": status,
                    "reason_code": reason,
                }
                self.database.execute(
                    """
                    insert into mcp_job_tool_binding
                      (id, job_id, tool_publication_id, server_code, tool_name,
                       required_scope, tool_schema_hash, resource_code,
                       resource_deployment_id, resource_revision_id, status,
                       reason_code, snapshot_hash, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("mcp_job_tool_binding"),
                        payload["job_id"],
                        payload["tool_publication_id"],
                        payload["server_code"],
                        payload["tool_name"],
                        payload["required_scope"],
                        payload["tool_schema_hash"],
                        payload["resource_code"],
                        payload["resource_deployment_id"],
                        payload["resource_revision_id"],
                        payload["status"],
                        payload["reason_code"],
                        _hash(payload),
                        timestamp,
                    ),
                )
        return self.eligible_bindings(job.id, require_running=False)[0]

    def eligible_bindings(
        self,
        job_id: str,
        *,
        require_running: bool = True,
    ) -> tuple[tuple[McpRuntimeBinding, ...], tuple[McpUnavailableNotice, ...]]:
        job = self.database.execute_one("select * from agent_job where id = ?", (job_id,))
        if job is None:
            raise self._invalid("mcp_job_missing")
        if require_running and str(job["status"]) != "RUNNING":
            raise self._invalid("mcp_job_not_running")
        subject = self.database.execute_one(
            "select * from mcp_job_subject_snapshot where job_id = ?",
            (job_id,),
        )
        if subject is None:
            raise self._invalid("mcp_subject_snapshot_missing")
        self._verify_subject_hash(subject)
        rows = self.database.execute(
            "select * from mcp_job_tool_binding where job_id = ? order by server_code, tool_name, resource_code",
            (job_id,),
        )
        eligible: list[McpRuntimeBinding] = []
        notices: list[McpUnavailableNotice] = []
        for row in rows:
            self._verify_binding_hash(row)
            current_reason = self._current_unavailable_reason(row, subject)
            if str(row["status"]) == "ELIGIBLE" and not current_reason:
                eligible.append(
                    McpRuntimeBinding(
                        server_code=str(row["server_code"]),
                        tool_name=str(row["tool_name"]),
                        required_scope=str(row["required_scope"]),
                        tool_schema_hash=str(row["tool_schema_hash"]),
                        resource_code=str(row["resource_code"]),
                        resource_deployment_id=str(row["resource_deployment_id"]),
                        resource_revision_id=str(row["resource_revision_id"]),
                    )
                )
                continue
            reason = current_reason or str(row["reason_code"] or "mcp_tool_unavailable")
            notices.append(self._notice(str(row["server_code"]), str(row["tool_name"]), reason))
        return tuple(eligible), tuple(notices)

    def _subject(self, app_user_id: str) -> dict[str, Any] | None:
        return self.database.execute_one(
            """
            select i.* from user_external_identity i
              join app_user u on u.id = i.user_id
             where i.user_id = ? and i.provider = 'ones'
               and i.status in ('enabled', 'disabled', 'REVERIFICATION_REQUIRED')
               and u.status = 'enabled'
             order by i.binding_revision desc, i.revision desc limit 1
            """,
            (app_user_id,),
        )

    def _initial_eligibility(
        self,
        *,
        publication: dict[str, Any],
        app_user_id: str,
        subject: dict[str, Any] | None,
    ) -> tuple[str, str, dict[str, Any] | None]:
        if str(publication["server_code"]) == "ones-mcp":
            if subject is None or str(subject["status"]) != "enabled":
                return "UNAVAILABLE", "ones_reverification_required", None
            credential = self.database.execute_one(
                """
                select id from provider_credential
                 where user_id = ? and external_identity_id = ?
                   and provider_instance_id = ? and status = 'ACTIVE'
                 order by revision desc limit 1
                """,
                (
                    app_user_id,
                    subject["id"],
                    subject.get("provider_instance_id") or "",
                ),
            )
            if credential is None:
                return "UNAVAILABLE", "ones_reverification_required", None
            if not str(_json_object(subject["metadata_json"]).get("default_team_id") or ""):
                return "UNAVAILABLE", "ones_default_team_missing", None
            return "ELIGIBLE", "", None
        resource_code = str(publication.get("resource_code") or "")
        if not resource_code:
            return "UNAVAILABLE", "mcp_resource_publication_missing", None
        deployment = self._active_deployment(resource_code)
        if deployment is None:
            return "UNAVAILABLE", "mcp_resource_unavailable", None
        return "ELIGIBLE", "", deployment

    def _current_unavailable_reason(
        self,
        binding: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> str:
        publication = self.database.execute_one(
            "select * from mcp_tool_publication where id = ?",
            (binding["tool_publication_id"],),
        )
        if publication is None or str(publication["status"]) != "PUBLISHED":
            return "mcp_tool_publication_revoked"
        try:
            catalog = get_catalog_entry(str(publication["catalog_key"]))
        except ValueError:
            return "mcp_tool_catalog_mismatch"
        if any(
            (
                catalog.server_code != str(binding["server_code"]),
                catalog.tool_name != str(binding["tool_name"]),
                catalog.required_scope != str(binding["required_scope"]),
                catalog.tool_schema_hash != str(binding["tool_schema_hash"]),
                catalog.server_version != str(publication["server_version"]),
            )
        ):
            return "mcp_tool_catalog_mismatch"
        user = self.database.execute_one(
            "select status from app_user where id = ?",
            (snapshot["app_user_id"],),
        )
        if user is None or str(user["status"]) != "enabled":
            return "mcp_subject_disabled"
        if str(binding["server_code"]) == "ones-mcp":
            identity = self.database.execute_one(
                "select * from user_external_identity where id = ?",
                (snapshot["external_identity_id"],),
            )
            if identity is None or str(identity["status"]) != "enabled":
                return "ones_reverification_required"
            metadata = _json_object(identity["metadata_json"])
            if any(
                (
                    str(identity["user_id"]) != str(snapshot["app_user_id"]),
                    str(identity["external_subject_id"]) != str(snapshot["external_subject"]),
                    str(identity.get("provider_instance_id") or "")
                    != str(snapshot["provider_instance_id"]),
                    str(metadata.get("default_team_id") or "") != str(snapshot["default_team_id"]),
                    int(identity.get("binding_revision") or 0) != int(snapshot["binding_revision"]),
                )
            ):
                return "ones_subject_snapshot_mismatch"
            credential = self.database.execute_one(
                """
                select id from provider_credential
                 where user_id = ? and external_identity_id = ?
                   and provider_instance_id = ? and status = 'ACTIVE'
                 order by revision desc limit 1
                """,
                (
                    snapshot["app_user_id"],
                    snapshot["external_identity_id"],
                    snapshot["provider_instance_id"],
                ),
            )
            return "" if credential else "ones_reverification_required"
        deployment = self.database.execute_one(
            """
            select d.*, r.lifecycle_status, rr.revision_status,
                   g.status as generation_status,
                   g.resource_revision_id as generation_resource_revision_id
              from mcp_resource_deployment d
              join mcp_resource r on r.id = d.resource_id
              join mcp_resource_revision rr on rr.id = d.resource_revision_id
              left join mcp_resource_generation g on g.id = d.current_generation_id
             where d.id = ?
            """,
            (binding["resource_deployment_id"],),
        )
        if deployment is None:
            return "mcp_resource_unavailable"
        if any(
            (
                str(deployment["status"]) != "ACTIVE",
                str(deployment["lifecycle_status"]) != "ENABLED",
                str(deployment["revision_status"]) != "PUBLISHED",
                str(deployment["resource_revision_id"]) != str(binding["resource_revision_id"]),
                str(deployment.get("generation_status") or "") != "ACTIVE",
                str(deployment.get("generation_resource_revision_id") or "")
                != str(binding["resource_revision_id"]),
            )
        ):
            return "mcp_resource_unavailable"
        return ""

    def _active_deployment(self, resource_code: str) -> dict[str, Any] | None:
        return self.database.execute_one(
            """
            select d.* from mcp_resource_deployment d
              join mcp_resource r on r.id = d.resource_id
              join mcp_resource_revision rr on rr.id = d.resource_revision_id
              join mcp_resource_generation g on g.id = d.current_generation_id
             where r.code = ? and r.lifecycle_status = 'ENABLED'
               and d.status = 'ACTIVE' and rr.revision_status = 'PUBLISHED'
               and g.status = 'ACTIVE'
               and g.resource_revision_id = d.resource_revision_id
            """,
            (resource_code,),
        )

    @staticmethod
    def _verify_subject_hash(row: dict[str, Any]) -> None:
        payload = {
            "job_id": row["job_id"],
            "app_user_id": row["app_user_id"],
            "external_identity_id": row["external_identity_id"],
            "external_subject": row["external_subject"],
            "provider_instance_id": row["provider_instance_id"],
            "default_team_id": row["default_team_id"],
            "binding_revision": int(row["binding_revision"]),
        }
        if _hash(payload) != str(row["snapshot_hash"]):
            raise McpJobBindingService._invalid("mcp_subject_snapshot_invalid")

    @staticmethod
    def _verify_binding_hash(row: dict[str, Any]) -> None:
        payload = {
            key: row[key]
            for key in (
                "job_id",
                "tool_publication_id",
                "server_code",
                "tool_name",
                "required_scope",
                "tool_schema_hash",
                "resource_code",
                "resource_deployment_id",
                "resource_revision_id",
                "status",
                "reason_code",
            )
        }
        if _hash(payload) != str(row["snapshot_hash"]):
            raise McpJobBindingService._invalid("mcp_tool_binding_invalid")

    @staticmethod
    def _notice(server_code: str, tool_name: str, reason: str) -> McpUnavailableNotice:
        return McpUnavailableNotice(
            tool_name=tool_name,
            reason_code=reason,
            message=(
                _ONES_REVERIFY_MESSAGE if server_code == "ones-mcp" else _DATA_UNAVAILABLE_MESSAGE
            ),
        )

    @staticmethod
    def _invalid(code: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "MCP Job binding is invalid",
            safe_message="当前任务的 MCP 运行绑定不可用",
            error_code=code,
        )


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
