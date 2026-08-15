from __future__ import annotations

import json
import re
from typing import Any, Never

from app.modules.admin.application import AdminCapabilityService
from app.modules.admin.domain import ADMIN_CAPABILITIES, ADMIN_CAPABILITY_BY_CODE
from app.modules.audit.application.audit_service import AuditService
from app.modules.business_application.domain.policies import verify_publication_snapshot
from app.modules.authorization_center.infrastructure.repository import (
    AuthorizationCenterRepository,
)
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.identity.infrastructure import IdentityRepository
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied


_ROLE_CODE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_FORBIDDEN_BUSINESS_CAPABILITY = re.compile(
    r"(^|[._-])(write|insert|update|delete|drop|shell|exec|file-write|redis-set)([._-]|$)",
    re.IGNORECASE,
)
_ROLE_AUDIT_LABELS = {
    "authorization.role.created": "创建角色",
    "authorization.role.metadata.updated": "更新基本信息",
    "authorization.role.admin.updated": "更新管理后台能力",
    "authorization.role.business.updated": "更新业务应用与数据范围",
    "authorization.role.members.updated": "更新角色成员",
}


class AuthorizationCenterService:
    def __init__(
        self,
        repository: AuthorizationCenterRepository,
        identity_repository: IdentityRepository,
        authorization: AuthorizationEvaluator,
        audit_service: AuditService,
    ) -> None:
        self.repository = repository
        self.identity_repository = identity_repository
        self.authorization = authorization
        self.audit_service = audit_service

    def capability_catalog(self) -> dict[str, Any]:
        modules: dict[str, list[dict[str, object]]] = {}
        for item in ADMIN_CAPABILITIES:
            modules.setdefault(item.module, []).append(item.to_dict())
        return {
            "items": [item.to_dict() for item in ADMIN_CAPABILITIES],
            "modules": [{"code": code, "items": items} for code, items in sorted(modules.items())],
        }

    def list_roles(
        self,
        *,
        actor_id: str,
        search: str,
        status: str,
        origin: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        self._require_catalog(actor_id, "authorization.read")
        items, total = self.repository.list_roles(
            search=search,
            status=status,
            origin=origin,
            limit=min(max(limit, 1), 100),
            offset=max(offset, 0),
        )
        return {"items": items, "page": {"limit": limit, "offset": offset, "total": total}}

    def role_detail(self, *, actor_id: str, role_id: str) -> dict[str, Any]:
        self._require_catalog(actor_id, "authorization.read")
        role = self.repository.get_role(role_id)
        return {
            "role": role,
            "admin": {
                "revision": role["admin_revision"],
                "bindings": self.repository.list_admin_bindings(role_id),
                "implicit_all": bool(role["protected"] and role["code"] == "platform-admin"),
            },
            "business": {
                "revision": role["business_revision"],
                "applications": self.repository.list_business_access(role_id),
            },
            "membership": {
                "revision": role["membership_revision"],
                "members": self.identity_repository.list_role_members(role_id),
            },
        }

    def role_audit(self, *, actor_id: str, role_id: str, limit: int = 100) -> dict[str, Any]:
        self._require_catalog(actor_id, "authorization.read")
        self.repository.get_role(role_id)
        rows = self.repository.database.execute(
            """
            select id, event_type, actor_id, status, created_at
              from audit_event
             where event_type like ?
               and cast(payload_summary as text) like ?
             order by created_at desc, id desc
             limit ?
            """,
            (
                "authorization.role.%",
                f"%{role_id}%",
                min(max(limit, 1), 100),
            ),
        )
        return {
            "items": [
                {
                    **row,
                    "action_zh": _ROLE_AUDIT_LABELS.get(str(row["event_type"]), "角色授权操作"),
                }
                for row in rows
            ],
            "notice": "仅显示安全操作摘要，不包含凭据、消息正文或策略条件。",
        }

    def create_role(
        self,
        *,
        actor_id: str,
        code: str,
        name: str,
        description: str,
        purpose_tags: list[str],
        copy_from_role_id: str = "",
    ) -> dict[str, Any]:
        self._require_catalog(actor_id, "authorization.manage")
        normalized_code = code.strip().lower()
        if not _ROLE_CODE.fullmatch(normalized_code):
            raise NonRetryableExecutionError(
                "Invalid role code",
                safe_message="角色编码需以小写字母开头，仅包含小写字母、数字和连字符",
                error_code="role_code_invalid",
                field_errors=[{"field": "code", "message": "角色编码格式无效"}],
            )
        if not name.strip():
            raise NonRetryableExecutionError(
                "Role name is required",
                safe_message="请输入角色名称",
                error_code="role_name_required",
                field_errors=[{"field": "name", "message": "请输入角色名称"}],
            )
        with self.repository.database.unit_of_work():
            role = self.repository.create_role(
                code=normalized_code,
                name=name.strip(),
                description=description.strip(),
                purpose_tags=self._purpose_tags(purpose_tags),
            )
            if copy_from_role_id:
                source = self.repository.get_role(copy_from_role_id)
                bindings = self.repository.list_admin_bindings(copy_from_role_id)
                applications = self.repository.list_business_access(copy_from_role_id)
                self._validate_admin_bindings(actor_id, bindings, confirmed=True, reason="复制角色")
                normalized_apps = self._normalize_business_applications(
                    actor_id=actor_id,
                    applications=[
                        {
                            "application_id": item["application_id"],
                            "tool_identifiers": item["tool_identifiers"],
                            "scopes": item["scopes"],
                        }
                        for item in applications
                    ],
                    confirmed=True,
                    reason="复制角色",
                )
                if bindings:
                    self.repository.replace_admin_bindings(
                        str(role["id"]), expected_revision=1, bindings=bindings
                    )
                if normalized_apps:
                    self.repository.replace_business_access(
                        str(role["id"]),
                        expected_revision=1,
                        applications=normalized_apps,
                    )
                copy_summary = {"source_role_id": source["id"], "members_copied": False}
            else:
                copy_summary = {}
            self.audit_service.record(
                "authorization.role.created",
                status="SUCCEEDED",
                summary="Role created",
                actor_id=actor_id,
                payload={"role_id": role["id"], "role_code": role["code"], **copy_summary},
            )
        return self.role_detail(actor_id=actor_id, role_id=str(role["id"]))

    def update_metadata(
        self,
        *,
        actor_id: str,
        role_id: str,
        expected_revision: int,
        name: str,
        description: str,
        purpose_tags: list[str],
        status: str,
        confirmed: bool,
        reason: str,
    ) -> dict[str, Any]:
        self._require_catalog(actor_id, "authorization.manage", resource_code=role_id)
        if status not in {"enabled", "disabled"}:
            self._field_error("status", "角色状态无效")
        before = self.repository.get_role(role_id)
        if status == "disabled" and before["status"] == "enabled" and not confirmed:
            self._confirmation_required("停用角色前需要确认受影响成员")
        with self.repository.database.unit_of_work():
            role = self.repository.update_metadata(
                role_id,
                expected_revision=expected_revision,
                name=name.strip(),
                description=description.strip(),
                purpose_tags=self._purpose_tags(purpose_tags),
                status=status,
            )
            self.audit_service.record(
                "authorization.role.metadata.updated",
                status="SUCCEEDED",
                summary="Role metadata updated",
                actor_id=actor_id,
                payload={
                    "role_id": role_id,
                    "before": self._safe_role_summary(before),
                    "after": self._safe_role_summary(role),
                    "reason": reason.strip() if confirmed else "",
                },
            )
        return role

    def replace_admin_capabilities(
        self,
        *,
        actor_id: str,
        role_id: str,
        expected_revision: int,
        bindings: list[dict[str, str]],
        confirmed: bool,
        reason: str,
    ) -> dict[str, Any]:
        self._require_catalog(actor_id, "authorization.manage", resource_code=role_id)
        normalized = self._validate_admin_bindings(
            actor_id, bindings, confirmed=confirmed, reason=reason
        )
        with self.repository.database.unit_of_work():
            before = self.repository.list_admin_bindings(role_id)
            result = self.repository.replace_admin_bindings(
                role_id,
                expected_revision=expected_revision,
                bindings=normalized,
            )
            self.audit_service.record(
                "authorization.role.admin.updated",
                status="SUCCEEDED",
                summary="Role admin capabilities updated",
                actor_id=actor_id,
                payload={
                    "role_id": role_id,
                    "before_codes": [item["capability_code"] for item in before],
                    "after_codes": [item["capability_code"] for item in normalized],
                    "reason": reason.strip(),
                },
            )
        return result

    def replace_business_access(
        self,
        *,
        actor_id: str,
        role_id: str,
        expected_revision: int,
        applications: list[dict[str, Any]],
        confirmed: bool,
        reason: str,
    ) -> dict[str, Any]:
        self._require_catalog(actor_id, "authorization.manage", resource_code=role_id)
        normalized = self._normalize_business_applications(
            actor_id=actor_id,
            applications=applications,
            confirmed=confirmed,
            reason=reason,
        )
        with self.repository.database.unit_of_work():
            before = self.repository.list_business_access(role_id)
            result = self.repository.replace_business_access(
                role_id,
                expected_revision=expected_revision,
                applications=normalized,
            )
            self.audit_service.record(
                "authorization.role.business.updated",
                status="SUCCEEDED",
                summary="Role business access updated",
                actor_id=actor_id,
                payload={
                    "role_id": role_id,
                    "before_application_ids": [item["application_id"] for item in before],
                    "after_application_ids": [item["application_id"] for item in normalized],
                    "reason": reason.strip(),
                },
            )
        return result

    def update_members(
        self,
        *,
        actor_id: str,
        role_id: str,
        expected_revision: int,
        changes: list[dict[str, Any]],
        confirmed: bool,
    ) -> dict[str, Any]:
        self._require_role_assignment(actor_id, role_id)
        role = self.repository.get_role(role_id)
        if role["protected"] and not confirmed:
            self._confirmation_required("修改平台管理员成员前需要二次确认")
        self_removal = any(
            str(change.get("user_id") or "") == actor_id and not bool(change.get("enabled"))
            for change in changes
        )
        if self_removal and not confirmed:
            self._confirmation_required("撤销自己的角色前需要二次确认")
        try:
            with self.repository.database.unit_of_work():
                verified_admins_before: int | None = None
                if role["code"] == "platform-admin":
                    self.identity_repository.lock_platform_admin_invariant()
                    self.repository.lock_platform_admin_memberships()
                    verified_admins_before = (
                        self.identity_repository.verified_human_platform_admin_count()
                    )
                self.repository.bump_membership_revision(role_id, expected_revision)
                for change in changes:
                    user_id = str(change.get("user_id") or "")
                    enabled = bool(change.get("enabled"))
                    user = self.identity_repository.get_user(user_id)
                    if (
                        enabled
                        and str(user["account_type"]) == "service"
                        and self._role_has_admin_capabilities(role)
                    ):
                        self._field_error(
                            "changes",
                            "服务账号不能加入包含管理后台能力的角色",
                        )
                    membership = self.repository.database.execute_one(
                        "select * from rbac_user_role where user_id = ? and role_id = ?",
                        (user_id, role_id),
                    )
                    if enabled:
                        self.identity_repository.assign_role(
                            user_id=user_id,
                            role_id=role_id,
                            expected_revision=(int(membership["revision"]) if membership else 0),
                            expires_at=change.get("expires_at") or None,
                            assigned_by=actor_id,
                            assignment_source=str(change.get("source") or "manual"),
                        )
                    else:
                        if membership is None:
                            continue
                        self.identity_repository.remove_role(
                            user_id=user_id,
                            role_id=role_id,
                            expected_revision=int(membership["revision"]),
                        )
                if verified_admins_before is not None:
                    verified_admins_after = (
                        self.identity_repository.verified_human_platform_admin_count()
                    )
                    if verified_admins_after < verified_admins_before:
                        self.identity_repository.require_verified_human_platform_admins()
                self.audit_service.record(
                    "authorization.role.members.updated",
                    status="SUCCEEDED",
                    summary="Role memberships updated",
                    actor_id=actor_id,
                    payload={
                        "role_id": role_id,
                        "changes": [
                            {
                                "user_id": str(item.get("user_id") or ""),
                                "enabled": bool(item.get("enabled")),
                                "expires_at": item.get("expires_at"),
                            }
                            for item in changes
                        ],
                    },
                )
        except NonRetryableExecutionError as exc:
            if exc.error_code == "platform_admin_invariant":
                self.audit_service.record(
                    "platform_admin_invariant_denied",
                    status="DENIED",
                    summary="Platform administrator invariant denied mutation",
                    actor_id=actor_id,
                    payload={
                        "operation": "platform_admin_membership.batch",
                        "target_id": role_id,
                    },
                )
            raise
        if self_removal:
            self.identity_repository.revoke_user_sessions(actor_id)
        return {
            "revision": self.repository.get_role(role_id)["membership_revision"],
            "members": self.identity_repository.list_role_members(role_id),
        }

    def update_user_roles(
        self,
        *,
        actor_id: str,
        user_id: str,
        changes: list[dict[str, Any]],
        confirmed: bool,
    ) -> dict[str, Any]:
        self.identity_repository.get_user(user_id)
        with self.repository.database.unit_of_work():
            for change in changes:
                self.update_members(
                    actor_id=actor_id,
                    role_id=str(change.get("role_id") or ""),
                    expected_revision=int(change.get("expected_role_revision") or 0),
                    changes=[
                        {
                            "user_id": user_id,
                            "enabled": bool(change.get("enabled")),
                            "expires_at": change.get("expires_at"),
                            "source": "manual",
                        }
                    ],
                    confirmed=confirmed,
                )
        return self.effective_summary(user_id)

    def effective_summary(self, user_id: str) -> dict[str, Any]:
        role_rows = self.repository.active_role_rows_for_user(user_id)
        business: dict[str, dict[str, Any]] = {}
        for role in role_rows:
            for access in self.repository.list_business_access(str(role["id"])):
                if access["status"] != "enabled":
                    continue
                item = business.setdefault(
                    str(access["application_id"]),
                    {
                        "id": access["application_id"],
                        "code": access["application_code"],
                        "name": access["application_name"],
                        "source_role_codes": [],
                        "tool_identifiers": [],
                        "scopes": [],
                    },
                )
                item["source_role_codes"].append(str(role["code"]))
                item["tool_identifiers"].extend(access["tool_identifiers"])
                item["scopes"].extend(access["scopes"])
        management = AdminCapabilityService(self.identity_repository, self.authorization).summary(
            user_id
        )
        return {
            "roles": self.identity_repository.list_user_roles(user_id),
            "management_capabilities": management["capabilities"],
            "business_applications": [
                {
                    **item,
                    "source_role_codes": sorted(set(item["source_role_codes"])),
                    "tool_identifiers": sorted(set(item["tool_identifiers"])),
                    "scopes": list(
                        {str(scope["scope_key"]): scope for scope in item["scopes"]}.values()
                    ),
                }
                for item in business.values()
            ],
            "access_status": ("已获得角色授权" if business else "未获得应用权限"),
        }

    def assignable_catalog(self, *, actor_id: str) -> dict[str, Any]:
        self._require_catalog(actor_id, "authorization.read")
        platform_admin = "platform-admin" in self.identity_repository.role_codes_for_user(actor_id)
        applications = self.repository.application_catalog()
        topology = self.repository.topology_catalog()
        if not platform_admin:
            actor_access: dict[str, list[dict[str, Any]]] = {}
            for application in applications:
                access = self.repository.business_access_for_user(
                    user_id=actor_id,
                    application_id=str(application["id"]),
                )
                if access:
                    actor_access[str(application["id"])] = access
            applications = [
                {
                    **application,
                    "mcp_tools": [
                        tool
                        for tool in application["mcp_tools"]
                        if str(tool["tool_identifier"])
                        in {
                            identifier
                            for access in actor_access[str(application["id"])]
                            for identifier in access["tool_identifiers"]
                        }
                    ],
                }
                for application in applications
                if str(application["id"]) in actor_access
            ]
            grantable_scope_keys = {
                str(scope["scope_key"])
                for accesses in actor_access.values()
                for access in accesses
                for scope in access["scopes"]
            }
            topology = self._filter_topology(topology, grantable_scope_keys)
        return {
            "applications": applications,
            "topology": topology,
            "scope_mode": "explicit_current_set",
            "scope_notice": "“当前全部”会保存当前已有范围的明确集合，未来新增范围不会自动获得。",
        }

    def _validate_admin_bindings(
        self,
        actor_id: str,
        bindings: list[dict[str, Any]],
        *,
        confirmed: bool,
        reason: str,
    ) -> list[dict[str, str]]:
        actor_is_platform_admin = "platform-admin" in self.identity_repository.role_codes_for_user(
            actor_id
        )
        actor_bindings: dict[str, set[str]] = {}
        for item in self.repository.admin_bindings_for_user(actor_id):
            actor_bindings.setdefault(str(item["capability_code"]), set()).add(
                str(item["resource_code"])
            )
        requested: dict[tuple[str, str, str, str], dict[str, str]] = {}
        requested_codes = {str(item.get("capability_code") or "") for item in bindings}
        closure = set(requested_codes)
        queue = list(requested_codes)
        while queue:
            code = queue.pop()
            definition = ADMIN_CAPABILITY_BY_CODE.get(code)
            if definition is None or not definition.assignable:
                self._field_error("bindings", f"管理能力不存在或不可分配：{code}")
            for dependency in definition.dependencies:
                if dependency not in closure:
                    closure.add(dependency)
                    queue.append(dependency)
        for code in sorted(closure):
            definition = ADMIN_CAPABILITY_BY_CODE[code]
            source = next(
                (item for item in bindings if str(item.get("capability_code") or "") == code),
                {},
            )
            resource_code = str(source.get("resource_code") or definition.resource_code)
            if not actor_is_platform_admin and not (
                code in actor_bindings
                and ("*" in actor_bindings[code] or resource_code in actor_bindings[code])
            ):
                self._field_error(
                    "bindings",
                    f"你无权授予管理能力：{definition.display_name_zh}",
                )
            key = (code, definition.resource_type, resource_code, definition.action)
            requested[key] = {
                "capability_code": code,
                "resource_type": definition.resource_type,
                "resource_code": resource_code,
            }
        high_risk = [
            ADMIN_CAPABILITY_BY_CODE[code].display_name_zh
            for code in closure
            if ADMIN_CAPABILITY_BY_CODE[code].risk_level == "high"
        ]
        if high_risk and (not confirmed or not reason.strip()):
            self._confirmation_required("高风险管理能力需要二次确认并填写变更原因")
        return list(requested.values())

    def _normalize_business_applications(
        self,
        *,
        actor_id: str,
        applications: list[dict[str, Any]],
        confirmed: bool,
        reason: str,
    ) -> list[dict[str, Any]]:
        actor_is_platform_admin = "platform-admin" in self.identity_repository.role_codes_for_user(
            actor_id
        )
        catalog = {str(item["id"]): item for item in self.repository.application_catalog()}
        result: list[dict[str, Any]] = []
        seen_apps: set[str] = set()
        for index, item in enumerate(applications):
            application_id = str(item.get("application_id") or "")
            if application_id in seen_apps:
                self._field_error(f"applications.{index}", "业务应用重复")
            application = catalog.get(application_id)
            if application is None or application["status"] != "enabled":
                self._field_error(f"applications.{index}.application_id", "业务应用不可授权")
            if not actor_is_platform_admin:
                actor_access = self.repository.business_access_for_user(
                    user_id=actor_id, application_id=application_id
                )
                if not actor_access:
                    self._field_error(
                        f"applications.{index}.application_id",
                        "你无权授予该业务应用",
                    )
            available_codes = {str(value["tool_identifier"]) for value in application["mcp_tools"]}
            tool_identifiers = sorted(
                {
                    str(value).strip()
                    for value in item.get("tool_identifiers") or []
                    if str(value).strip()
                }
            )
            for identifier in tool_identifiers:
                if identifier not in available_codes:
                    self._field_error(
                        f"applications.{index}.tool_identifiers",
                        f"MCP Tool 未在业务应用中装配：{identifier}",
                    )
                if _FORBIDDEN_BUSINESS_CAPABILITY.search(identifier):
                    self._field_error(
                        f"applications.{index}.tool_identifiers",
                        "角色只允许授予已注册的只读 MCP Tool",
                    )
            scopes: list[dict[str, Any]] = []
            seen_scopes: set[str] = set()
            raw_scopes = list(item.get("scopes") or [])
            for current_all in item.get("current_all") or []:
                raw_scopes.extend(
                    self.repository.expand_current_scopes(
                        level=str(current_all.get("level") or ""),
                        environment_id=str(current_all.get("environment_id") or ""),
                        base_id=str(current_all.get("base_id") or ""),
                    )
                )
            for scope_index, raw_scope in enumerate(raw_scopes):
                scope = self.repository.scope_node(
                    environment_id=str(raw_scope.get("environment_id") or ""),
                    base_id=str(raw_scope.get("base_id") or "") or None,
                    workshop_id=str(raw_scope.get("workshop_id") or "") or None,
                )
                if scope["scope_key"] in seen_scopes:
                    self._field_error(
                        f"applications.{index}.scopes.{scope_index}",
                        "数据范围重复",
                    )
                seen_scopes.add(scope["scope_key"])
                scopes.append(scope)
            if not actor_is_platform_admin:
                actor_access = self.repository.business_access_for_user(
                    user_id=actor_id, application_id=application_id
                )
                grantable_tools = {
                    identifier
                    for access in actor_access
                    for identifier in access["tool_identifiers"]
                }
                grantable_scopes = {
                    str(scope["scope_key"]) for access in actor_access for scope in access["scopes"]
                }
                if not set(tool_identifiers) <= grantable_tools:
                    self._field_error(
                        f"applications.{index}.tool_identifiers",
                        "不能授予超出你可授权范围的 MCP Tool",
                    )
                if not seen_scopes <= grantable_scopes:
                    self._field_error(
                        f"applications.{index}.scopes",
                        "不能授予超出你可授权范围的数据范围",
                    )
            seen_apps.add(application_id)
            result.append(
                {
                    "application_id": application_id,
                    "tool_identifiers": tool_identifiers,
                    "scopes": scopes,
                }
            )
        if applications and (not confirmed or not reason.strip()):
            self._confirmation_required("业务应用或数据范围授权需要二次确认并填写变更原因")
        return result

    def _require_catalog(
        self, actor_id: str, capability_code: str, *, resource_code: str = "*"
    ) -> None:
        definition = ADMIN_CAPABILITY_BY_CODE[capability_code]
        self.authorization.require(
            user_id=actor_id,
            resource_type=definition.resource_type,
            resource_code=resource_code,
            action=definition.action,
        )

    def _require_role_assignment(self, actor_id: str, role_id: str) -> None:
        if "platform-admin" in self.identity_repository.role_codes_for_user(actor_id):
            return
        self.authorization.require(
            user_id=actor_id,
            resource_type="role",
            resource_code=role_id,
            action="assign",
        )

    def _role_has_admin_capabilities(self, role: dict[str, Any]) -> bool:
        return bool(
            role["code"] == "platform-admin" or self.repository.list_admin_bindings(str(role["id"]))
        )

    @staticmethod
    def _filter_topology(
        topology: list[dict[str, Any]], grantable_scope_keys: set[str]
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for environment in topology:
            environment_code = str(environment["code"])
            environment_allowed = environment_code in grantable_scope_keys
            bases: list[dict[str, Any]] = []
            for base in environment["bases"]:
                base_key = f"{environment_code}/{base['code']}"
                base_allowed = base_key in grantable_scope_keys
                workshops = [
                    workshop
                    for workshop in base["workshops"]
                    if f"{base_key}/{workshop['code']}" in grantable_scope_keys
                ]
                if base_allowed or workshops:
                    bases.append({**base, "workshops": workshops})
            if environment_allowed or bases:
                result.append({**environment, "bases": bases})
        return result

    @staticmethod
    def _purpose_tags(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))[:10]

    @staticmethod
    def _safe_role_summary(role: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": role["id"],
            "code": role["code"],
            "name": role["name"],
            "status": role["status"],
            "purpose_tags": role.get("purpose_tags") or [],
        }

    @staticmethod
    def _field_error(field: str, message: str) -> Never:
        raise NonRetryableExecutionError(
            message,
            safe_message=message,
            error_code="validation_failed",
            field_errors=[{"field": field, "message": message}],
        )

    @staticmethod
    def _confirmation_required(message: str) -> None:
        raise NonRetryableExecutionError(
            message,
            safe_message=message,
            error_code="confirmation_required",
        )


class BusinessAuthorizationService:
    def __init__(
        self,
        repository: AuthorizationCenterRepository,
        identity_repository: IdentityRepository,
        *,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.identity_repository = identity_repository
        self.audit_service = audit_service

    def decide(
        self,
        *,
        user_id: str,
        application_id: str = "",
        application_code: str = "",
        tool_identifier: str = "",
        environment: str = "",
        base: str = "",
        workshop: str = "",
        stage: str = "invoke",
    ) -> dict[str, Any]:
        user = self.identity_repository.get_user(user_id)
        application = (
            self.repository.database.execute_one(
                "select * from business_application where id = ?", (application_id,)
            )
            if application_id
            else self.repository.database.execute_one(
                "select * from business_application where code = ?", (application_code,)
            )
        )
        if application is None:
            return self._decision(False, stage, "application_not_found", [], {})
        if str(user["status"]) != "enabled":
            return self._decision(False, stage, "user_disabled", [], application)
        if str(application["status"]) != "enabled":
            return self._decision(False, stage, "application_disabled", [], application)
        role_codes = self.identity_repository.role_codes_for_user(user_id)
        if tool_identifier:
            if not self.repository.application_tool_is_effective(
                str(application["id"]), tool_identifier
            ):
                return self._decision(
                    False,
                    stage,
                    "application_tool_safety_ceiling",
                    list(role_codes),
                    application,
                    tool_identifier=tool_identifier,
                    scope=self._scope_summary(environment, base, workshop),
                )
        accesses = self.repository.business_access_for_user(
            user_id=user_id, application_id=str(application["id"])
        )
        matching_roles: list[str] = []
        tool_allowed = not tool_identifier
        scope_allowed = not (environment or base or workshop)
        for access in accesses:
            if tool_identifier and tool_identifier not in access["tool_identifiers"]:
                continue
            tool_allowed = True
            if environment or base or workshop:
                if not any(
                    self._scope_matches(
                        scope,
                        environment=environment,
                        base=base,
                        workshop=workshop,
                    )
                    for scope in access["scopes"]
                ):
                    continue
                scope_allowed = True
            matching_roles.append(str(access["role_code"]))
        if accesses and matching_roles and tool_allowed and scope_allowed:
            return self._decision(
                True,
                stage,
                "application_role_allow",
                matching_roles,
                application,
                tool_identifier=tool_identifier,
                scope=self._scope_summary(environment, base, workshop),
            )
        if accesses:
            reason = "application_tool_denied" if not tool_allowed else "application_scope_denied"
            return self._decision(
                False,
                stage,
                reason,
                [str(item["role_code"]) for item in accesses],
                application,
                tool_identifier=tool_identifier,
                scope=self._scope_summary(environment, base, workshop),
            )
        return self._decision(
            False,
            stage,
            "no_application_role",
            list(role_codes),
            application,
            tool_identifier=tool_identifier,
            scope=self._scope_summary(environment, base, workshop),
        )

    def capture_runtime_facts(
        self,
        *,
        user_id: str,
        application_id: str,
        publication_id: str,
        publication_config_hash: str,
        environment: str = "",
        base: str = "",
        workshop: str = "",
    ) -> dict[str, Any]:
        """Capture the strict, immutable authorization boundary for one Job."""

        publication = self.repository.database.execute_one(
            """
            select id, application_id, revision, schema_version, snapshot_json,
                   config_hash
              from business_application_publication
             where id = ?
            """,
            (publication_id,),
        )
        if (
            publication is None
            or str(publication.get("application_id") or "") != application_id
            or str(publication.get("config_hash") or "") != publication_config_hash
        ):
            raise PermissionDenied(
                "Business Application publication cannot be pinned for this Job",
                safe_message="业务应用发布版本不可用",
                error_code="job_runtime_facts_invalid",
            )
        try:
            snapshot = json.loads(str(publication.get("snapshot_json") or "{}"))
        except json.JSONDecodeError as exc:
            raise PermissionDenied(
                "Business Application publication snapshot is invalid",
                safe_message="业务应用发布版本不可用",
                error_code="job_runtime_facts_invalid",
            ) from exc
        if (
            not isinstance(snapshot, dict)
            or not verify_publication_snapshot(
                snapshot,
                schema_version=int(publication.get("schema_version") or 0),
                expected_hash=publication_config_hash,
            )
        ):
            raise PermissionDenied(
                "Business Application publication integrity check failed",
                safe_message="业务应用发布版本完整性校验失败",
                error_code="job_runtime_facts_invalid",
            )

        accesses = self.repository.business_access_for_user(
            user_id=user_id,
            application_id=application_id,
        )
        return self._capture_exact_builtin_runtime_facts(
            application_id=application_id,
            publication=publication,
            snapshot=snapshot,
            accesses=accesses,
            environment=environment,
            base=base,
            workshop=workshop,
        )

    def _capture_exact_builtin_runtime_facts(
        self,
        *,
        application_id: str,
        publication: dict[str, Any],
        snapshot: dict[str, Any],
        accesses: list[dict[str, Any]],
        environment: str,
        base: str,
        workshop: str,
    ) -> dict[str, Any]:
        """Capture audit facts without interpreting legacy name bindings."""

        publication_id = str(publication["id"])
        agent = snapshot.get("agent")
        agent_publication_id = str(agent.get("id") or "") if isinstance(agent, dict) else ""
        if not agent_publication_id:
            raise self._runtime_facts_invalid(
                "Application publication does not pin an Agent publication"
            )
        tools = self.repository.database.execute(
            """
            select allowlist.server_code, allowlist.tool_identifier, allowlist.schema_hash
              from business_application_publication_mcp_tool allowlist
             where allowlist.application_publication_id = ?
               and allowlist.agent_publication_id = ?
             order by allowlist.selection_order
            """,
            (publication_id, agent_publication_id),
        )
        requested_scope = {
            "environment_code": environment,
            "base_code": base,
            "workshop_code": workshop,
        }
        roles_by_tool: dict[str, set[str]] = {str(tool["tool_identifier"]): set() for tool in tools}
        for access in accesses:
            if not any(
                self._scope_matches(
                    scope,
                    environment=environment,
                    base=base,
                    workshop=workshop,
                )
                for scope in access["scopes"]
            ):
                continue
            for tool_identifier in (
                set(str(value) for value in access["tool_identifiers"]) & roles_by_tool.keys()
            ):
                roles_by_tool[tool_identifier].add(str(access["role_code"]))
        return {
            "schema_version": 3,
            "application_publication": {
                "id": publication_id,
                "application_id": application_id,
                "revision": int(publication.get("revision") or 0),
                "config_hash": str(publication["config_hash"]),
            },
            "agent_publication_id": agent_publication_id,
            "requested_scope": requested_scope,
            "tool_grants": [
                {
                    "tool_identifier": str(tool["tool_identifier"]),
                    "server_code": str(tool["server_code"]),
                    "schema_hash": str(tool["schema_hash"]),
                    "source_role_codes": sorted(roles_by_tool[str(tool["tool_identifier"])]),
                }
                for tool in tools
            ],
            "bindings": [],
        }

    def _resolve_execution_scope_nodes(
        self,
        *,
        environment: str,
        base: str,
        workshop: str,
    ) -> dict[str, str]:
        environment_row = self.repository.database.execute_one(
            """
            select id, code from platform_environment
             where code = ? and status = 'enabled'
            """,
            (environment,),
        )
        if environment_row is None:
            raise self._runtime_facts_invalid("Execution Scope environment is unavailable")
        base_row: dict[str, Any] | None = None
        if base:
            base_row = self.repository.database.execute_one(
                """
                select id, code from platform_base
                 where environment_id = ? and code = ?
                   and status = 'enabled'
                """,
                (environment_row["id"], base),
            )
            if base_row is None:
                raise self._runtime_facts_invalid("Execution Scope base is unavailable")
        workshop_row: dict[str, Any] | None = None
        if workshop:
            if base_row is None:
                raise self._runtime_facts_invalid("Execution Scope workshop has no base")
            workshop_row = self.repository.database.execute_one(
                """
                select id, code from platform_workshop
                 where base_id = ? and code = ? and status = 'enabled'
                """,
                (base_row["id"], workshop),
            )
            if workshop_row is None:
                raise self._runtime_facts_invalid("Execution Scope workshop is unavailable")
        scope_key = "|".join(
            (
                str(environment_row["id"]),
                str((base_row or {}).get("id") or ""),
                str((workshop_row or {}).get("id") or ""),
            )
        )
        return {
            "scope_key": scope_key,
            "environment_id": str(environment_row["id"]),
            "environment_code": str(environment_row["code"]),
            "base_id": str((base_row or {}).get("id") or ""),
            "base_code": str((base_row or {}).get("code") or ""),
            "workshop_id": str((workshop_row or {}).get("id") or ""),
            "workshop_code": str((workshop_row or {}).get("code") or ""),
        }

    @staticmethod
    def _runtime_facts_invalid(message: str) -> PermissionDenied:
        return PermissionDenied(
            message,
            safe_message="Job 执行范围无法固化",
            error_code="job_runtime_facts_invalid",
        )

    @staticmethod
    def _runtime_resource_fact(resource: dict[str, Any]) -> dict[str, Any]:
        return {
            "resource_revision_id": str(resource.get("id") or ""),
            "resource_code": str(resource.get("code") or ""),
            "revision": int(resource.get("revision") or 0),
            "resource_kind": str(resource.get("resource_kind") or ""),
            "scope_type": str(resource.get("scope_type") or ""),
            "environment_id": str(resource.get("environment_id") or ""),
            "environment_code": str(resource.get("environment_code") or ""),
            "base_id": str(resource.get("base_id") or ""),
            "base_code": str(resource.get("base_code") or ""),
            "workshop_id": str(resource.get("workshop_id") or ""),
            "workshop_code": str(resource.get("workshop_code") or ""),
        }

    @staticmethod
    def _resource_within_scope(
        resource: dict[str, Any],
        scope: dict[str, str],
        requested_scope: dict[str, str],
    ) -> bool:
        resource_environment = str(resource.get("environment_code") or "")
        resource_base = str(resource.get("base_code") or "")
        resource_workshop = str(resource.get("workshop_code") or "")
        if resource_environment != scope["environment_code"]:
            return False
        if scope["base_code"] and resource_base != scope["base_code"]:
            return False
        if scope["workshop_code"] and (
            resource_base != scope["base_code"]
            or (resource_workshop and resource_workshop != scope["workshop_code"])
        ):
            return False
        if (
            requested_scope["environment_code"]
            and resource_environment != requested_scope["environment_code"]
        ):
            return False
        if requested_scope["base_code"] and resource_base != requested_scope["base_code"]:
            return False
        if requested_scope["workshop_code"] and (
            resource_workshop and resource_workshop != requested_scope["workshop_code"]
        ):
            return False
        return True

    def require(self, **kwargs: Any) -> dict[str, Any]:
        decision = self.decide(**kwargs)
        if not decision["allowed"]:
            if self.audit_service:
                self.audit_service.record(
                    "authorization.business.denied",
                    status="DENIED",
                    summary="Business authorization denied",
                    actor_id=str(kwargs.get("user_id") or ""),
                    payload=decision,
                )
            message = (
                "当前用户未获得该业务应用权限"
                if decision["reason"] == "no_application_role"
                else "当前用户无权使用该应用 MCP Tool 或数据范围"
            )
            raise PermissionDenied(
                f"Business authorization denied: {decision['reason']}",
                safe_message=message,
                error_code="business_application_denied",
                diagnostics={"decision": decision},
            )
        return decision

    @staticmethod
    def _scope_matches(
        scope: dict[str, Any], *, environment: str, base: str, workshop: str
    ) -> bool:
        if environment and str(scope.get("environment_code") or "") != environment:
            return False
        scope_base = str(scope.get("base_code") or "")
        scope_workshop = str(scope.get("workshop_code") or "")
        if base and scope_base and scope_base != base:
            return False
        if workshop and scope_workshop and scope_workshop != workshop:
            return False
        return True

    @staticmethod
    def _scope_summary(environment: str, base: str, workshop: str) -> dict[str, str]:
        return {"environment": environment, "base": base, "workshop": workshop}

    @staticmethod
    def _decision(
        allowed: bool,
        stage: str,
        reason: str,
        role_codes: list[str],
        application: dict[str, Any],
        *,
        tool_identifier: str = "",
        scope: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "allowed": allowed,
            "stage": stage,
            "reason": reason,
            "source_role_codes": sorted(set(role_codes)),
            "application": {
                "id": str(application.get("id") or ""),
                "code": str(application.get("code") or ""),
            },
            "tool_identifier": tool_identifier,
            "scope": scope or {},
        }


class AuthorizationExplanationService:
    def __init__(self, business_authorization: BusinessAuthorizationService) -> None:
        self.business_authorization = business_authorization

    def explain(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "decision": self.business_authorization.decide(**kwargs),
            "notice": "解释仅显示安全的授权来源摘要，不包含策略条件、消息正文或凭据。",
        }
