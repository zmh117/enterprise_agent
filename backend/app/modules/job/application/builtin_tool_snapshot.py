from __future__ import annotations

import json
from typing import Any

from app.modules.business_application.application.builtin_tool_composition import (
    ApplicationBuiltinToolCompositionService,
)
from app.modules.business_application.domain.policies import (
    snapshot_hash,
    verify_snapshot,
)
from app.modules.internal_tools.domain import (
    HandlerRegistry,
    HandlerRegistryError,
    build_builtin_handler_registry,
)
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError


class JobBuiltinToolSnapshotService:
    def __init__(
        self,
        database: Database,
        *,
        composition: ApplicationBuiltinToolCompositionService | None = None,
        registry: HandlerRegistry | None = None,
    ) -> None:
        self.database = database
        self.composition = composition or ApplicationBuiltinToolCompositionService(database)
        self.registry = registry or build_builtin_handler_registry()

    def freeze(
        self,
        *,
        job_id: str,
        requester_id: str,
        application_id: str,
        application_publication_id: str,
        application_config_hash: str,
        agent_publication_id: str,
        routing_context: dict[str, Any],
        business_authorization: dict[str, Any],
        runtime_authorization: dict[str, Any],
    ) -> dict[str, Any]:
        publication = self._publication(
            application_id=application_id,
            publication_id=application_publication_id,
            config_hash=application_config_hash,
        )
        publication_snapshot = publication["snapshot"]
        facts = self.composition.publication_facts(application_publication_id)
        tools = facts["tools"]
        if not tools:
            return {}
        expected_facts = {
            "builtin_tools": tools,
            "target_paths": facts["targets"],
            "builtin_tool_resolution_set": facts["resolution_set"],
        }
        for field, value in expected_facts.items():
            snapshot_value = publication_snapshot.get(field)
            if field == "target_paths" and snapshot_value is None:
                snapshot_value = []
            if snapshot_value != value:
                raise self._invalid(
                    "Business Application built-in Tool facts differ from its publication",
                    "业务应用内置工具发布事实完整性校验失败",
                    code="job_builtin_tool_publication_hash_mismatch",
                )
        application_agent = publication_snapshot.get("agent")
        expected_agent_publication_id = (
            str(application_agent.get("id") or "") if isinstance(application_agent, dict) else ""
        )
        if (
            not expected_agent_publication_id
            or expected_agent_publication_id != agent_publication_id
        ):
            raise self._invalid(
                "Job Agent publication differs from its Application publication",
                "Job 的 Agent 发布版本与业务应用不一致",
            )
        target = self._resolve_target(
            targets=facts["targets"],
            routing_context=routing_context,
        )
        resolution_set = facts["resolution_set"]
        if not isinstance(resolution_set, dict):
            raise self._invalid(
                "Application built-in Tool resolution set is missing",
                "业务应用缺少内置工具资源解析表",
            )
        resolutions = [
            dict(item)
            for item in resolution_set.get("resolutions") or []
            if str(item.get("target_key") or "") == target["target_key"]
        ]
        bindings = self._prepare_bindings(
            tools=tools,
            target=target,
            resolutions=resolutions,
        )
        runtime_authorization_hash = snapshot_hash(runtime_authorization)
        business_authorization_hash = snapshot_hash(business_authorization)
        authorization_facts = {
            "requester_id": requester_id,
            "application_id": application_id,
            "application_publication_id": application_publication_id,
            "target_hash": target["target_hash"],
            "business_authorization_hash": business_authorization_hash,
            "runtime_authorization_hash": runtime_authorization_hash,
            "runtime_authorization_schema_version": int(
                runtime_authorization.get("schema_version") or 0
            ),
        }
        authorization_hash = snapshot_hash(authorization_facts)
        snapshot = {
            "schema_version": 3,
            "job_id": job_id,
            "application_publication": {
                "id": application_publication_id,
                "config_hash": application_config_hash,
                "resolution_set_hash": str(resolution_set["resolution_set_hash"]),
            },
            "agent_publication_id": agent_publication_id,
            "target": target,
            "authorization": authorization_facts,
            "bindings": bindings,
        }
        content_hash = snapshot_hash(snapshot)
        timestamp = now_iso()
        self.database.execute(
            """
            insert into agent_job_builtin_tool_snapshot
              (id, job_id, application_publication_id, agent_publication_id,
               schema_version, snapshot_json, snapshot_hash,
               authorization_hash, created_at)
            values (?, ?, ?, ?, 3, ?, ?, ?, ?)
            on conflict(job_id) do nothing
            """,
            (
                new_id("job_builtin_tool_snapshot"),
                job_id,
                application_publication_id,
                agent_publication_id,
                self._json(snapshot),
                content_hash,
                authorization_hash,
                timestamp,
            ),
        )
        row = self.database.execute_one(
            "select * from agent_job_builtin_tool_snapshot where job_id = ?",
            (job_id,),
        )
        if row is None:
            raise self._invalid(
                "Job built-in Tool Snapshot was not persisted",
                "Job 内置工具执行快照保存失败",
            )
        if (
            str(row["snapshot_hash"]) != content_hash
            or str(row["authorization_hash"]) != authorization_hash
        ):
            raise self._invalid(
                "Existing Job built-in Tool Snapshot differs",
                "Job 内置工具执行快照冲突",
                code="job_builtin_tool_snapshot_immutable",
            )
        snapshot_id = str(row["id"])
        for binding in bindings:
            self._persist_binding(
                snapshot_id=snapshot_id,
                binding=binding,
                timestamp=timestamp,
            )
        return self.verify(job_id)

    def freeze_agent_only(
        self,
        *,
        job_id: str,
        requester_id: str,
        agent_publication_id: str,
        routing_context: dict[str, Any],
        business_authorization: dict[str, Any],
        runtime_authorization: dict[str, Any],
    ) -> dict[str, Any]:
        """Freeze the resource-free subset of an exact Agent envelope.

        Resource-backed tools require an Application target matrix and are
        intentionally omitted from direct Agent Jobs.
        """

        publication = self.database.execute_one(
            "select id from agent_publication where id = ?",
            (agent_publication_id,),
        )
        if publication is None:
            raise self._invalid(
                "Direct Job Agent publication is unavailable",
                "Job 的 Agent 发布版本不可用",
            )
        rows = self.database.execute(
            """
            select envelope.agent_publication_id,
                   envelope.tool_identifier, envelope.tool_release_id,
                   envelope.handler_version,
                   envelope.implementation_digest,
                   envelope.public_schema_hash
              from agent_publication_builtin_tool envelope
              join builtin_tool_release release
                on release.id = envelope.tool_release_id
               and release.tool_identifier = envelope.tool_identifier
               and release.handler_version = envelope.handler_version
               and release.implementation_digest =
                   envelope.implementation_digest
              join builtin_tool_installation installation
                on installation.tool_identifier = envelope.tool_identifier
               and installation.handler_version = envelope.handler_version
               and installation.implementation_digest =
                   envelope.implementation_digest
             where envelope.agent_publication_id = ?
               and release.status in ('ACTIVE', 'DEPRECATED')
               and installation.installation_status = 'INSTALLED'
             order by envelope.tool_identifier
            """,
            (agent_publication_id,),
        )
        target = self._direct_target(routing_context)
        tools: list[dict[str, Any]] = []
        for row in rows:
            definition = self.registry.require(
                str(row["tool_identifier"]),
                str(row["handler_version"]),
            )
            if any(slot.required for slot in definition.resource_slots):
                continue
            tool = dict(row)
            self._assert_tool_callable(tool)
            tools.append(tool)
        bindings = [self._binding(tool, target, "", []) for tool in tools]
        runtime_authorization_hash = snapshot_hash(runtime_authorization)
        business_authorization_hash = snapshot_hash(business_authorization)
        authorization_facts = {
            "requester_id": requester_id,
            "application_id": "",
            "application_publication_id": "",
            "target_hash": target["target_hash"],
            "business_authorization_hash": business_authorization_hash,
            "runtime_authorization_hash": runtime_authorization_hash,
            "runtime_authorization_schema_version": int(
                runtime_authorization.get("schema_version") or 0
            ),
        }
        authorization_hash = snapshot_hash(authorization_facts)
        snapshot = {
            "schema_version": 3,
            "job_id": job_id,
            "application_publication": {
                "id": "",
                "config_hash": "",
                "resolution_set_hash": snapshot_hash(
                    {
                        "mode": "direct_agent_resource_free",
                        "agent_publication_id": agent_publication_id,
                    }
                ),
            },
            "agent_publication_id": agent_publication_id,
            "target": target,
            "authorization": authorization_facts,
            "bindings": bindings,
        }
        content_hash = snapshot_hash(snapshot)
        timestamp = now_iso()
        self.database.execute(
            """
            insert into agent_job_builtin_tool_snapshot
              (id, job_id, application_publication_id, agent_publication_id,
               schema_version, snapshot_json, snapshot_hash,
               authorization_hash, created_at)
            values (?, ?, null, ?, 3, ?, ?, ?, ?)
            on conflict(job_id) do nothing
            """,
            (
                new_id("job_builtin_tool_snapshot"),
                job_id,
                agent_publication_id,
                self._json(snapshot),
                content_hash,
                authorization_hash,
                timestamp,
            ),
        )
        persisted = self.database.execute_one(
            "select * from agent_job_builtin_tool_snapshot where job_id = ?",
            (job_id,),
        )
        if (
            persisted is None
            or str(persisted["snapshot_hash"]) != content_hash
            or str(persisted["authorization_hash"]) != authorization_hash
        ):
            raise self._invalid(
                "Existing direct Job snapshot differs",
                "Job 内置工具执行快照冲突",
                code="job_builtin_tool_snapshot_immutable",
            )
        for binding in bindings:
            self._persist_binding(
                snapshot_id=str(persisted["id"]),
                binding=binding,
                timestamp=timestamp,
            )
        return self.verify(job_id)

    @staticmethod
    def _direct_target(routing_context: dict[str, Any]) -> dict[str, Any]:
        environment_id = str(routing_context.get("environment_id") or "")
        base_id = str(routing_context.get("base_id") or "")
        workshop_id = str(routing_context.get("workshop_id") or "")
        environment_code = str(routing_context.get("environment") or "")
        base_code = str(routing_context.get("base") or "")
        workshop_code = str(routing_context.get("workshop") or "")
        target = {
            "target_scope_type": (
                "workshop"
                if workshop_code or workshop_id
                else "base"
                if base_code or base_id
                else "environment"
                if environment_code or environment_id
                else "unscoped"
            ),
            "target_key": "/".join(
                value
                for value in (
                    environment_code or environment_id,
                    base_code or base_id,
                    workshop_code or workshop_id,
                )
                if value
            )
            or "unscoped",
            "environment_id": environment_id,
            "environment_code": environment_code,
            "base_id": base_id,
            "base_code": base_code,
            "workshop_id": workshop_id,
            "workshop_code": workshop_code,
        }
        return {**target, "target_hash": snapshot_hash(target)}

    def freeze_legacy_migration(
        self,
        *,
        job_id: str,
        tool_release_ids: list[str],
        migration_version: str,
    ) -> dict[str, Any]:
        """Materialize a resource-free legacy Job from its original frozen facts."""

        row = self.database.execute_one(
            """
            select job.*,
                   scope.id as legacy_scope_id,
                   scope.application_publication_id as scope_application_publication_id,
                   scope.agent_publication_id as scope_agent_publication_id,
                   scope.environment_id as scope_environment_id,
                   scope.base_id as scope_base_id,
                   scope.workshop_id as scope_workshop_id,
                   scope.scope_hash as legacy_scope_hash,
                   scope.schema_version as legacy_scope_schema_version,
                   scope.snapshot_json as legacy_scope_snapshot_json
              from agent_job job
              join agent_job_execution_scope scope on scope.job_id = job.id
             where job.id = ?
            """,
            (job_id,),
        )
        if row is None:
            raise self._invalid(
                "Legacy Job execution scope is missing",
                "旧 Job 缺少不可变执行范围",
                code="builtin_tool_legacy_job_execution_scope_missing",
            )
        application_publication_id = str(row.get("business_application_publication_id") or "")
        agent_publication_id = str(row.get("agent_publication_id") or "")
        if (
            int(row.get("legacy_scope_schema_version") or 0) != 2
            or str(row.get("scope_application_publication_id") or "") != application_publication_id
            or str(row.get("scope_agent_publication_id") or "") != agent_publication_id
        ):
            raise self._invalid(
                "Legacy Job execution scope differs from Job publication facts",
                "旧 Job 执行范围与发布事实不一致",
                code="builtin_tool_legacy_job_execution_scope_mismatch",
            )
        route_decision = self._object_json(
            row.get("business_application_route_decision_json"),
            code="builtin_tool_legacy_job_authorization_missing",
        )
        business_authorization = route_decision.get("authorization_snapshot")
        runtime_authorization = route_decision.get("runtime_authorization")
        if not isinstance(business_authorization, dict) or not isinstance(
            runtime_authorization, dict
        ):
            raise self._invalid(
                "Legacy Job authorization evidence is missing",
                "旧 Job 授权快照缺失",
                code="builtin_tool_legacy_job_authorization_missing",
            )
        scope_snapshot = self._object_json(
            row.get("legacy_scope_snapshot_json"),
            code="builtin_tool_legacy_job_execution_scope_mismatch",
        )
        expected_scope_snapshot = {"job_id": job_id, **runtime_authorization}
        if (
            scope_snapshot != expected_scope_snapshot
            or snapshot_hash(scope_snapshot) != str(row.get("legacy_scope_hash") or "")
            or int(runtime_authorization.get("schema_version") or 0) != 2
        ):
            raise self._invalid(
                "Legacy Job execution scope integrity check failed",
                "旧 Job 执行范围完整性校验失败",
                code="builtin_tool_legacy_job_execution_scope_mismatch",
            )
        publication = self._publication(
            application_id=str(row.get("business_application_id") or ""),
            publication_id=application_publication_id,
            config_hash=str(row.get("business_application_config_hash") or ""),
        )
        target = self._legacy_target(
            runtime_authorization=runtime_authorization,
            row=row,
        )
        tools = self._legacy_tools(
            agent_publication_id=agent_publication_id,
            tool_release_ids=tool_release_ids,
        )
        bindings = [self._binding(tool, target, "", []) for tool in tools]
        bindings.sort(key=lambda item: str(item["tool_identifier"]))
        runtime_authorization_hash = snapshot_hash(runtime_authorization)
        business_authorization_hash = snapshot_hash(business_authorization)
        requester_id = str(row.get("internal_user_id") or row.get("user_id") or "")
        if not requester_id:
            raise self._invalid(
                "Legacy Job requester is missing",
                "旧 Job 请求主体缺失",
                code="builtin_tool_legacy_job_authorization_missing",
            )
        authorization_facts = {
            "requester_id": requester_id,
            "application_id": str(row.get("business_application_id") or ""),
            "application_publication_id": application_publication_id,
            "target_hash": target["target_hash"],
            "business_authorization_hash": business_authorization_hash,
            "runtime_authorization_hash": runtime_authorization_hash,
            "runtime_authorization_schema_version": 2,
        }
        authorization_hash = snapshot_hash(authorization_facts)
        migration_resolution_hash = snapshot_hash(
            {
                "migration_version": migration_version,
                "application_publication_id": application_publication_id,
                "agent_publication_id": agent_publication_id,
                "execution_scope_hash": str(row["legacy_scope_hash"]),
                "tool_release_ids": sorted(tool_release_ids),
            }
        )
        snapshot = {
            "schema_version": 3,
            "job_id": job_id,
            "application_publication": {
                "id": application_publication_id,
                "config_hash": str(publication["config_hash"]),
                "resolution_set_hash": migration_resolution_hash,
            },
            "agent_publication_id": agent_publication_id,
            "target": target,
            "authorization": authorization_facts,
            "bindings": bindings,
        }
        content_hash = snapshot_hash(snapshot)
        timestamp = now_iso()
        self.database.execute(
            """
            insert into agent_job_builtin_tool_snapshot
              (id, job_id, application_publication_id, agent_publication_id,
               schema_version, snapshot_json, snapshot_hash,
               authorization_hash, created_at)
            values (?, ?, ?, ?, 3, ?, ?, ?, ?)
            on conflict(job_id) do nothing
            """,
            (
                new_id("job_builtin_tool_snapshot"),
                job_id,
                application_publication_id,
                agent_publication_id,
                self._json(snapshot),
                content_hash,
                authorization_hash,
                timestamp,
            ),
        )
        persisted = self.database.execute_one(
            "select * from agent_job_builtin_tool_snapshot where job_id = ?",
            (job_id,),
        )
        if (
            persisted is None
            or str(persisted["snapshot_hash"]) != content_hash
            or str(persisted["authorization_hash"]) != authorization_hash
        ):
            raise self._invalid(
                "Existing legacy Job snapshot differs from migration result",
                "旧 Job 精确快照与迁移结果冲突",
                code="job_builtin_tool_snapshot_immutable",
            )
        for binding in bindings:
            self._persist_binding(
                snapshot_id=str(persisted["id"]),
                binding=binding,
                timestamp=timestamp,
            )
        return self.verify(job_id)

    def verify(self, job_id: str) -> dict[str, Any]:
        existing_snapshot = self.database.execute_one(
            "select id from agent_job_builtin_tool_snapshot where job_id = ?",
            (job_id,),
        )
        required = self.database.execute_one(
            """
            select count(*) as count
              from agent_job job
              join business_application_publication_builtin_tool tool
                on tool.application_publication_id =
                   job.business_application_publication_id
             where job.id = ?
            """,
            (job_id,),
        )
        if existing_snapshot is None and (required is None or int(required["count"]) == 0):
            return {}
        row = self.database.execute_one(
            """
            select snapshot.*, job.agent_publication_id as job_agent_publication_id,
                   job.business_application_publication_id as job_application_publication_id,
                   job.business_application_id as job_application_id,
                   job.business_application_config_hash as job_application_config_hash,
                   job.user_id as job_user_id,
                   job.internal_user_id as job_internal_user_id,
                   job.business_application_route_decision_json as job_route_decision_json
              from agent_job_builtin_tool_snapshot snapshot
              join agent_job job on job.id = snapshot.job_id
             where snapshot.job_id = ?
            """,
            (job_id,),
        )
        if row is None:
            raise self._invalid(
                "Job built-in Tool Snapshot is missing",
                "Job 内置工具执行快照缺失",
            )
        try:
            snapshot = json.loads(str(row["snapshot_json"]))
        except json.JSONDecodeError as exc:
            raise self._invalid(
                "Job built-in Tool Snapshot JSON is invalid",
                "Job 内置工具执行快照无效",
            ) from exc
        if (
            not isinstance(snapshot, dict)
            or int(snapshot.get("schema_version") or 0) != 3
            or snapshot_hash(snapshot) != str(row["snapshot_hash"])
            or snapshot_hash(snapshot.get("authorization") or {}) != str(row["authorization_hash"])
            or str(row["agent_publication_id"]) != str(row["job_agent_publication_id"] or "")
            or str(row.get("application_publication_id") or "")
            != str(row["job_application_publication_id"] or "")
        ):
            raise self._invalid(
                "Job built-in Tool Snapshot integrity check failed",
                "Job 内置工具执行快照完整性校验失败",
                code="job_builtin_tool_snapshot_hash_mismatch",
            )
        self._assert_job_authorization_facts(row=row, snapshot=snapshot)
        bindings = snapshot.get("bindings")
        if not isinstance(bindings, list):
            raise self._invalid(
                "Job built-in Tool bindings are invalid",
                "Job 内置工具执行绑定无效",
            )
        persisted = self._binding_facts(str(row["id"]))
        if persisted != bindings:
            raise self._invalid(
                "Job built-in Tool binding facts differ from Snapshot",
                "Job 内置工具执行绑定完整性校验失败",
                code="job_builtin_tool_snapshot_hash_mismatch",
            )
        for binding in bindings:
            self._assert_tool_callable(binding)
            self._assert_resource_facts(binding)
        return {
            "id": str(row["id"]),
            "job_id": job_id,
            "snapshot_hash": str(row["snapshot_hash"]),
            "authorization_hash": str(row["authorization_hash"]),
            "snapshot": snapshot,
        }

    def _assert_job_authorization_facts(
        self,
        *,
        row: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> None:
        authorization = snapshot.get("authorization")
        target = snapshot.get("target")
        publication = snapshot.get("application_publication")
        if (
            not isinstance(authorization, dict)
            or not isinstance(target, dict)
            or not isinstance(publication, dict)
        ):
            raise self._invalid(
                "Job built-in Tool authorization facts are invalid",
                "Job 内置工具授权事实无效",
                code="job_builtin_tool_snapshot_hash_mismatch",
            )
        try:
            route_decision = json.loads(str(row.get("job_route_decision_json") or "{}"))
        except json.JSONDecodeError as exc:
            raise self._invalid(
                "Job route decision JSON is invalid",
                "Job 路由授权事实无效",
                code="job_builtin_tool_authorization_mismatch",
            ) from exc
        if not isinstance(route_decision, dict):
            raise self._invalid(
                "Job route decision is invalid",
                "Job 路由授权事实无效",
                code="job_builtin_tool_authorization_mismatch",
            )
        business_authorization = route_decision.get("authorization_snapshot")
        runtime_authorization = route_decision.get("runtime_authorization")
        if not isinstance(business_authorization, dict) or not isinstance(
            runtime_authorization,
            dict,
        ):
            raise self._invalid(
                "Job authorization snapshots are missing",
                "Job 授权快照缺失",
                code="job_builtin_tool_authorization_mismatch",
            )
        authoritative_user_id = str(row.get("job_internal_user_id") or row.get("job_user_id") or "")
        expected = {
            "requester_id": authoritative_user_id,
            "application_id": str(row.get("job_application_id") or ""),
            "application_publication_id": str(row.get("job_application_publication_id") or ""),
            "target_hash": str(target.get("target_hash") or ""),
            "business_authorization_hash": snapshot_hash(business_authorization),
            "runtime_authorization_hash": snapshot_hash(runtime_authorization),
            "runtime_authorization_schema_version": int(
                runtime_authorization.get("schema_version") or 0
            ),
        }
        if (
            authorization != expected
            or str(publication.get("config_hash") or "")
            != str(row.get("job_application_config_hash") or "")
            or not authoritative_user_id
        ):
            raise self._invalid(
                "Job authorization facts differ from the built-in Tool Snapshot",
                "Job 授权事实与内置工具快照不一致",
                code="job_builtin_tool_authorization_mismatch",
            )

    def tool_binding(
        self,
        *,
        job_id: str,
        tool_identifier: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        frozen = self.verify(job_id)
        if not frozen:
            return None
        snapshot = frozen["snapshot"]
        bindings = [
            dict(binding)
            for binding in snapshot["bindings"]
            if str(binding["tool_identifier"]) == tool_identifier
        ]
        if not bindings:
            return snapshot["target"], []
        return dict(snapshot["target"]), bindings

    def _publication(
        self,
        *,
        application_id: str,
        publication_id: str,
        config_hash: str,
    ) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from business_application_publication where id = ?",
            (publication_id,),
        )
        if (
            row is None
            or str(row["application_id"]) != application_id
            or str(row["config_hash"]) != config_hash
            or int(row["schema_version"]) != 1
        ):
            raise self._invalid(
                "Business Application publication cannot be pinned",
                "业务应用发布版本不可用于 Job 快照",
            )
        try:
            snapshot = json.loads(str(row["snapshot_json"]))
        except json.JSONDecodeError as exc:
            raise self._invalid(
                "Business Application publication JSON is invalid",
                "业务应用发布版本无效",
            ) from exc
        if not isinstance(snapshot, dict) or not verify_snapshot(
            snapshot,
            config_hash,
        ):
            raise self._invalid(
                "Business Application publication hash mismatch",
                "业务应用发布版本完整性校验失败",
                code="job_builtin_tool_publication_hash_mismatch",
            )
        return {**row, "snapshot": snapshot}

    def _resolve_target(
        self,
        *,
        targets: list[dict[str, Any]],
        routing_context: dict[str, Any],
    ) -> dict[str, Any]:
        fields = (
            ("environment_id", "environment_code", "environment"),
            ("base_id", "base_code", "base"),
            ("workshop_id", "workshop_code", "workshop"),
        )
        matches: list[dict[str, Any]] = []
        for target in targets:
            matched = True
            for id_field, code_field, request_code_field in fields:
                requested_id = str(routing_context.get(id_field) or "")
                requested_code = str(routing_context.get(request_code_field) or "")
                if requested_id and requested_id != str(target.get(id_field) or ""):
                    matched = False
                    break
                if requested_code and requested_code != str(target.get(code_field) or ""):
                    matched = False
                    break
            if matched:
                matches.append(dict(target))
        if len(matches) != 1:
            raise self._invalid(
                "Job target does not resolve to exactly one published target",
                "Job 业务目标无法唯一解析到应用发布范围",
                code="job_builtin_tool_target_resolution_invalid",
            )
        return matches[0]

    def _legacy_target(
        self,
        *,
        runtime_authorization: dict[str, Any],
        row: dict[str, Any],
    ) -> dict[str, Any]:
        requested = runtime_authorization.get("requested_scope")
        if not isinstance(requested, dict):
            raise self._invalid(
                "Legacy Job requested scope is missing",
                "旧 Job 目标范围缺失",
                code="builtin_tool_legacy_job_execution_scope_mismatch",
            )
        environment_id = str(requested.get("environment_id") or "")
        base_id = str(requested.get("base_id") or "")
        workshop_id = str(requested.get("workshop_id") or "")
        if (
            environment_id != str(row.get("scope_environment_id") or "")
            or base_id != str(row.get("scope_base_id") or "")
            or workshop_id != str(row.get("scope_workshop_id") or "")
        ):
            raise self._invalid(
                "Legacy Job requested scope differs from persisted nodes",
                "旧 Job 目标范围与持久化节点不一致",
                code="builtin_tool_legacy_job_execution_scope_mismatch",
            )
        scope_type = "workshop" if workshop_id else "base" if base_id else "environment"
        prepared = self.composition.prepare_targets(
            [
                {
                    "target_scope_type": scope_type,
                    "environment_code": str(requested.get("environment_code") or ""),
                    "base_code": str(requested.get("base_code") or ""),
                    "workshop_code": str(requested.get("workshop_code") or ""),
                }
            ]
        )
        if len(prepared) != 1:
            raise self._invalid(
                "Legacy Job target cannot be resolved uniquely",
                "旧 Job 目标无法唯一解析",
                code="builtin_tool_legacy_job_target_invalid",
            )
        target = prepared[0]
        if (
            str(target["environment_id"]) != environment_id
            or str(target.get("base_id") or "") != base_id
            or str(target.get("workshop_id") or "") != workshop_id
        ):
            raise self._invalid(
                "Legacy Job target differs from current topology identity",
                "旧 Job 目标与拓扑身份不一致",
                code="builtin_tool_legacy_job_target_invalid",
            )
        return target

    def _legacy_tools(
        self,
        *,
        agent_publication_id: str,
        tool_release_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not tool_release_ids or len(tool_release_ids) != len(set(tool_release_ids)):
            raise self._invalid(
                "Legacy Job Tool Release candidates are invalid",
                "旧 Job 精确工具候选无效",
                code="builtin_tool_legacy_resolution_missing",
            )
        placeholders = ",".join("?" for _ in tool_release_ids)
        rows = self.database.execute(
            f"""
            select release.id as tool_release_id,
                   release.tool_identifier, release.handler_version,
                   release.implementation_digest, release.public_schema_hash
              from builtin_tool_release release
             where release.id in ({placeholders})
             order by release.tool_identifier
            """,
            tuple(tool_release_ids),
        )
        if len(rows) != len(tool_release_ids):
            raise self._invalid(
                "Legacy Job Tool Release candidate is missing",
                "旧 Job 精确工具候选缺失",
                code="builtin_tool_legacy_resolution_missing",
            )
        legacy_names = {
            str(item["tool_name"])
            for item in self.database.execute(
                """
                select tool_name from agent_tool_binding
                 where publication_id = ?
                """,
                (agent_publication_id,),
            )
        }
        tools: list[dict[str, Any]] = []
        for row in rows:
            if str(row["tool_identifier"]) not in legacy_names:
                raise self._invalid(
                    "Legacy Job Tool candidate was not present in its Agent publication",
                    "旧 Job 工具候选与原 Agent 发布版本不一致",
                    code="builtin_tool_legacy_resolution_mismatch",
                )
            definition = self.registry.require(
                str(row["tool_identifier"]),
                str(row["handler_version"]),
            )
            if any(slot.required for slot in definition.resource_slots):
                raise self._invalid(
                    "Legacy Job resource facts cannot be reconstructed safely",
                    "旧 Job 缺少精确资源或策略事实，不能自动物化",
                    code="builtin_tool_legacy_job_resource_snapshot_missing",
                )
            tool = {
                "agent_publication_id": agent_publication_id,
                "tool_identifier": str(row["tool_identifier"]),
                "tool_release_id": str(row["tool_release_id"]),
                "handler_version": str(row["handler_version"]),
                "implementation_digest": str(row["implementation_digest"]),
                "public_schema_hash": str(row["public_schema_hash"]),
            }
            self._assert_tool_callable(tool)
            tools.append(tool)
        return tools

    def _object_json(self, raw: object, *, code: str) -> dict[str, Any]:
        try:
            value = json.loads(str(raw or "{}"))
        except json.JSONDecodeError as exc:
            raise self._invalid(
                "Legacy Job JSON evidence is invalid",
                "旧 Job 证据格式无效",
                code=code,
            ) from exc
        if not isinstance(value, dict):
            raise self._invalid(
                "Legacy Job JSON evidence is not an object",
                "旧 Job 证据格式无效",
                code=code,
            )
        return value

    def _prepare_bindings(
        self,
        *,
        tools: list[dict[str, Any]],
        target: dict[str, Any],
        resolutions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for tool in tools:
            self._assert_tool_callable(tool)
            tool_resolutions = [
                item
                for item in resolutions
                if str(item["tool_identifier"]) == str(tool["tool_identifier"])
                and str(item["tool_release_id"]) == str(tool["tool_release_id"])
                and str(item["handler_version"]) == str(tool["handler_version"])
                and str(item["implementation_digest"]) == str(tool["implementation_digest"])
            ]
            by_slot: dict[str, list[dict[str, Any]]] = {}
            for item in tool_resolutions:
                by_slot.setdefault(str(item["resource_slot"]), []).append(item)
            if not by_slot:
                prepared.append(self._binding(tool, target, "", []))
                continue
            for slot in sorted(by_slot):
                candidates = sorted(
                    by_slot[slot],
                    key=lambda item: str(item.get("placement") or ""),
                )
                placement_keys = [str(item.get("placement") or "") for item in candidates]
                if len(placement_keys) != len(set(placement_keys)):
                    raise self._invalid(
                        "Job Resource Mapping placement is ambiguous",
                        "Job 工具资源 placement 无法唯一解析",
                    )
                if "" in placement_keys and len(placement_keys) > 1:
                    raise self._invalid(
                        "Job Resource Mapping mixes placed and no-placement candidates",
                        "Job 工具资源不能混用 placement 与无 placement",
                    )
                prepared.append(self._binding(tool, target, slot, candidates))
        prepared.sort(
            key=lambda item: (
                str(item["tool_identifier"]),
                str(item["resource_slot"]),
            )
        )
        return prepared

    def _binding(
        self,
        tool: dict[str, Any],
        target: dict[str, Any],
        slot: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        available_placements = sorted(
            str(item["placement"]) for item in candidates if item.get("placement")
        )
        candidate_facts = [
            {
                "placement": item.get("placement"),
                "resource_revision_id": item["resource_revision_id"],
                "resource_content_hash": item["resource_content_hash"],
                "resource_kind": item["resource_kind"],
                "resource_scope_type": item["resource_scope_type"],
                "workshop_partition_policy_revision_id": item[
                    "workshop_partition_policy_revision_id"
                ],
                "workshop_partition_policy_hash": item["workshop_partition_policy_hash"],
                "loki_scope_policy_revision_id": item["loki_scope_policy_revision_id"],
                "loki_scope_policy_hash": item["loki_scope_policy_hash"],
                "mapping_hash": item["mapping_hash"],
                "resolution_hash": item["resolution_hash"],
            }
            for item in candidates
        ]
        binding = {
            "tool_identifier": tool["tool_identifier"],
            "tool_release_id": tool["tool_release_id"],
            "handler_version": tool["handler_version"],
            "implementation_digest": tool["implementation_digest"],
            "public_schema_hash": tool["public_schema_hash"],
            "resource_slot": slot,
            "target_key": target["target_key"],
            "available_placements": available_placements,
            "candidates": candidate_facts,
        }
        binding["binding_hash"] = snapshot_hash(binding)
        return binding

    def _persist_binding(
        self,
        *,
        snapshot_id: str,
        binding: dict[str, Any],
        timestamp: str,
    ) -> None:
        candidates = list(binding["candidates"])
        resource_revision_id = (
            str(candidates[0]["resource_revision_id"]) if len(candidates) == 1 else None
        )
        workshop_policy_ids = {
            str(item.get("workshop_partition_policy_revision_id") or "") for item in candidates
        } - {""}
        workshop_policy_hashes = {
            str(item.get("workshop_partition_policy_hash") or "") for item in candidates
        } - {""}
        loki_policy_ids = {
            str(item.get("loki_scope_policy_revision_id") or "") for item in candidates
        } - {""}
        loki_policy_hashes = {
            str(item.get("loki_scope_policy_hash") or "") for item in candidates
        } - {""}
        if any(
            len(values) > 1
            for values in (
                workshop_policy_ids,
                workshop_policy_hashes,
                loki_policy_ids,
                loki_policy_hashes,
            )
        ):
            raise self._invalid(
                "Job Resource Mapping policies are inconsistent across placements",
                "Job 工具资源在不同 placement 使用了不一致的策略",
            )
        self.database.execute(
            """
            insert into agent_job_builtin_tool_binding
              (id, snapshot_id, tool_identifier, tool_release_id,
               handler_version, implementation_digest, public_schema_hash,
               resource_slot, target_key, available_placements_json,
               resource_revision_id,
               workshop_partition_policy_revision_id,
               workshop_partition_policy_hash,
               loki_scope_policy_revision_id, loki_scope_policy_hash,
               binding_hash, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(snapshot_id, tool_identifier, resource_slot, target_key)
            do nothing
            """,
            (
                new_id("job_builtin_tool_binding"),
                snapshot_id,
                binding["tool_identifier"],
                binding["tool_release_id"],
                binding["handler_version"],
                binding["implementation_digest"],
                binding["public_schema_hash"],
                binding["resource_slot"],
                binding["target_key"],
                self._json(binding["available_placements"]),
                resource_revision_id,
                next(iter(workshop_policy_ids), None),
                next(iter(workshop_policy_hashes), None),
                next(iter(loki_policy_ids), None),
                next(iter(loki_policy_hashes), None),
                binding["binding_hash"],
                timestamp,
            ),
        )

    def _binding_facts(self, snapshot_id: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select * from agent_job_builtin_tool_binding
             where snapshot_id = ?
             order by tool_identifier, resource_slot
            """,
            (snapshot_id,),
        )
        result: list[dict[str, Any]] = []
        snapshot = self.database.execute_one(
            "select snapshot_json from agent_job_builtin_tool_snapshot where id = ?",
            (snapshot_id,),
        )
        assert snapshot is not None
        content = json.loads(str(snapshot["snapshot_json"]))
        by_key = {
            (str(item["tool_identifier"]), str(item["resource_slot"])): item
            for item in content.get("bindings") or []
        }
        if len(rows) != len(by_key):
            return []
        for row in rows:
            key = (str(row["tool_identifier"]), str(row["resource_slot"]))
            expected = by_key.get(key)
            if expected is None:
                return []
            try:
                placements = json.loads(str(row["available_placements_json"]))
            except json.JSONDecodeError:
                placements = None
            candidates = list(expected["candidates"])
            expected_resource_revision_id = (
                str(candidates[0]["resource_revision_id"]) if len(candidates) == 1 else ""
            )
            expected_workshop_policy_ids = {
                str(item.get("workshop_partition_policy_revision_id") or "") for item in candidates
            } - {""}
            expected_workshop_policy_hashes = {
                str(item.get("workshop_partition_policy_hash") or "") for item in candidates
            } - {""}
            expected_loki_policy_ids = {
                str(item.get("loki_scope_policy_revision_id") or "") for item in candidates
            } - {""}
            expected_loki_policy_hashes = {
                str(item.get("loki_scope_policy_hash") or "") for item in candidates
            } - {""}
            canonical_binding = dict(expected)
            persisted_binding_hash = str(canonical_binding.pop("binding_hash", ""))
            if (
                placements != expected["available_placements"]
                or persisted_binding_hash != snapshot_hash(canonical_binding)
                or str(row["binding_hash"]) != persisted_binding_hash
                or str(row["tool_release_id"]) != str(expected["tool_release_id"])
                or str(row["handler_version"]) != str(expected["handler_version"])
                or str(row["implementation_digest"]) != str(expected["implementation_digest"])
                or str(row["public_schema_hash"]) != str(expected["public_schema_hash"])
                or str(row["target_key"]) != str(expected["target_key"])
                or str(row.get("resource_revision_id") or "") != expected_resource_revision_id
                or str(row.get("workshop_partition_policy_revision_id") or "")
                != next(iter(expected_workshop_policy_ids), "")
                or str(row.get("workshop_partition_policy_hash") or "")
                != next(iter(expected_workshop_policy_hashes), "")
                or str(row.get("loki_scope_policy_revision_id") or "")
                != next(iter(expected_loki_policy_ids), "")
                or str(row.get("loki_scope_policy_hash") or "")
                != next(iter(expected_loki_policy_hashes), "")
            ):
                return []
            result.append(expected)
        return result

    def _assert_tool_callable(self, binding: dict[str, Any]) -> None:
        identifier = str(binding["tool_identifier"])
        handler_version = str(binding["handler_version"])
        implementation_digest = str(binding["implementation_digest"])
        try:
            definition = self.registry.require(identifier, handler_version)
        except HandlerRegistryError as exc:
            raise self._invalid(
                "Frozen built-in Tool implementation is missing",
                "Job 冻结的内置工具精确实现缺失",
                code="job_builtin_tool_implementation_missing",
            ) from exc
        release = self.database.execute_one(
            """
            select release.status, installation.installation_status,
                   installation.implementation_digest as installed_digest,
                   release.public_schema_hash
              from builtin_tool_release release
              left join builtin_tool_installation installation
                on installation.tool_identifier = release.tool_identifier
               and installation.handler_version = release.handler_version
             where release.id = ? and release.tool_identifier = ?
               and release.handler_version = ?
               and release.implementation_digest = ?
            """,
            (
                binding["tool_release_id"],
                identifier,
                handler_version,
                implementation_digest,
            ),
        )
        if release is None or str(release["status"]) not in {
            "ACTIVE",
            "DEPRECATED",
        }:
            raise self._invalid(
                "Frozen built-in Tool Release is not callable",
                "Job 冻结的内置工具 Release 已不可调用",
                code="job_builtin_tool_release_not_callable",
            )
        if (
            str(release.get("installation_status") or "") != "INSTALLED"
            or str(release.get("installed_digest") or "") != implementation_digest
            or definition.implementation_digest != implementation_digest
            or definition.public_schema_hash != str(binding["public_schema_hash"])
            or str(release["public_schema_hash"]) != str(binding["public_schema_hash"])
        ):
            raise self._invalid(
                "Frozen built-in Tool implementation is missing or drifted",
                "Job 冻结的内置工具精确实现缺失或漂移",
                code="job_builtin_tool_implementation_drifted",
            )

    def _assert_resource_facts(self, binding: dict[str, Any]) -> None:
        slot = str(binding.get("resource_slot") or "")
        candidates = binding.get("candidates")
        if not isinstance(candidates, list) or (slot and not candidates):
            raise self._invalid(
                "Frozen built-in Tool Resource Mapping is missing",
                "Job 冻结的内置工具资源映射缺失",
                code="job_builtin_tool_resource_missing",
            )
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise self._invalid(
                    "Frozen built-in Tool Resource Mapping is invalid",
                    "Job 冻结的内置工具资源映射无效",
                )
            resource = self.database.execute_one(
                """
                select revision.content_hash, revision.status,
                       resource.resource_kind
                  from platform_resource_revision revision
                  join platform_resource resource
                    on resource.id = revision.resource_id
                 where revision.id = ?
                """,
                (candidate.get("resource_revision_id"),),
            )
            if (
                resource is None
                or str(resource["status"]) != "PUBLISHED"
                or str(resource["content_hash"])
                != str(candidate.get("resource_content_hash") or "")
                or str(resource["resource_kind"]) != str(candidate.get("resource_kind") or "")
            ):
                raise self._invalid(
                    "Frozen built-in Tool Resource Revision is unavailable",
                    "Job 冻结的工具资源版本不可用",
                    code="job_builtin_tool_resource_unavailable",
                )
            self._assert_policy_fact(
                table="workshop_partition_policy_revision",
                revision_id=str(candidate.get("workshop_partition_policy_revision_id") or ""),
                expected_hash=str(candidate.get("workshop_partition_policy_hash") or ""),
            )
            self._assert_policy_fact(
                table="loki_scope_policy_revision",
                revision_id=str(candidate.get("loki_scope_policy_revision_id") or ""),
                expected_hash=str(candidate.get("loki_scope_policy_hash") or ""),
            )

    def _assert_policy_fact(
        self,
        *,
        table: str,
        revision_id: str,
        expected_hash: str,
    ) -> None:
        if not revision_id and not expected_hash:
            return
        if not revision_id or not expected_hash:
            raise self._invalid(
                "Frozen built-in Tool Policy fact is incomplete",
                "Job 冻结的工具隔离策略事实不完整",
                code="job_builtin_tool_policy_unavailable",
            )
        if table not in {
            "workshop_partition_policy_revision",
            "loki_scope_policy_revision",
        }:
            raise AssertionError("Unsupported built-in Tool policy table")
        row = self.database.execute_one(
            f"select content_hash, status from {table} where id = ?",
            (revision_id,),
        )
        if (
            row is None
            or str(row["status"]) != "PUBLISHED"
            or str(row["content_hash"]) != expected_hash
        ):
            raise self._invalid(
                "Frozen built-in Tool Policy Revision is unavailable",
                "Job 冻结的工具隔离策略版本不可用",
                code="job_builtin_tool_policy_unavailable",
            )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _invalid(
        message: str,
        safe_message: str,
        *,
        code: str = "job_builtin_tool_snapshot_invalid",
    ) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            message,
            safe_message=safe_message,
            error_code=code,
        )
