from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.modules.external_action.domain import json_hash
from app.modules.mcp_audit import McpAuditCoordinator
from app.shared.ones_tool_contracts import ONES_CREATE_BUG_TOOL_IDENTIFIER, require_ones_tool_contract
from services.ones_mcp_server.bug_create import validate_bug_create_arguments
from services.ones_mcp_server.bug_create_catalog import BugCreateFieldCatalog
from services.ones_mcp_server.contracts import PROVIDER_HEADERS
from services.ones_mcp_server.errors import OnesMcpError, invalid_provider_response
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _identifier(value: object, code: str = "ones_bug_create_target_invalid") -> str:
    text = str(value or "")
    if _IDENTIFIER.fullmatch(text) is None:
        raise OnesMcpError(
            "Invalid ONES bug-create identifier",
            safe_message="ONES 缺陷创建目标标识无效",
            error_code=code,
        )
    return text


def _object(value: object, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise invalid_provider_response(code)
    return {str(key): item for key, item in value.items()}


def _named(value: object, code: str) -> tuple[str, str]:
    item = _object(value, code)
    uuid = _identifier(item.get("uuid"))
    name = str(item.get("name") or "").strip()
    if not name or len(name) > 300:
        raise invalid_provider_response(code)
    return uuid, name


def _named_list(value: object, code: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 2000:
        raise invalid_provider_response(code)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        item = _object(raw, code)
        uuid, name = _named(item, code)
        if uuid in seen:
            raise invalid_provider_response(code)
        seen.add(uuid)
        result.append({**item, "uuid": uuid, "name": name})
    return result


@dataclass(frozen=True, slots=True)
class BugCreatePreflight:
    layout_version: str
    validation_hash: str
    display_values: dict[str, dict[str, str]]


class OnesBugCreateProvider:
    def __init__(self, http: OnesProviderHttpClient, *, catalog: BugCreateFieldCatalog) -> None:
        self.http = http
        self.catalog = catalog

    def preflight_create(
        self,
        *,
        team_uuid: str,
        provider_user_id: str,
        token: str,
        arguments: dict[str, Any],
    ) -> BugCreatePreflight:
        team_uuid = _identifier(team_uuid)
        provider_user_id = _identifier(provider_user_id)
        self.catalog.require_team(team_uuid)
        request = validate_bug_create_arguments(arguments)
        for semantic_name in (
            "defect_type_uuid",
            "urgency_uuid",
            "severity_uuid",
            "discovery_difficulty_uuid",
            "reproduction_probability_uuid",
            "discovery_stage_uuid",
            "online_defect_uuid",
            "historical_defect_uuid",
        ):
            self.catalog.option_name(semantic_name, str(request[semantic_name]))
        user_uuids = list(
            dict.fromkeys(
                [provider_user_id, str(request["assignee_uuid"]), *request["watcher_uuids"]]
            )
        )
        payload = {
            "project_uuid": request["project_uuid"],
            "issue_type_uuid": self.catalog.fixed_issue_type_uuid,
            "user_uuids": user_uuids,
            "product_uuids": request["product_uuids"],
            "product_module_uuids": request["product_module_uuids"],
            "affected_version_uuids": request["affected_version_uuids"],
        }
        try:
            response = self.http.post_json(
                f"/project/api/project/team/{team_uuid}/tasks/create_preflight",
                payload,
                headers={
                    PROVIDER_HEADERS["token"]: token,
                    PROVIDER_HEADERS["user"]: provider_user_id,
                },
            )
        except OnesMcpError as exc:
            if exc.error_code != "ones_provider_operation_unavailable":
                raise
            raise OnesMcpError(
                "ONES create capability contract is unavailable",
                safe_message="当前 ONES 环境未提供可靠的缺陷创建权限、布局和回查合同",
                error_code="ones_bug_create_capability_not_ready",
            ) from None
        McpAuditCoordinator.reject_auth_material(response)
        if response.get("ready") is not True or response.get("can_create") is not True:
            raise OnesMcpError(
                "ONES create capability or permission is not ready",
                safe_message="当前 ONES 环境未提供可靠的缺陷创建权限与布局校验",
                error_code="ones_bug_create_capability_not_ready",
            )
        layout_version = str(response.get("layout_version") or "")
        required_fields = response.get("required_field_uuids")
        expected_fields = {field.provider_field_uuid for field in self.catalog.fields}
        if (
            not layout_version
            or len(layout_version) > 128
            or not isinstance(required_fields, list)
            or set(str(value) for value in required_fields) != expected_fields
        ):
            raise OnesMcpError(
                "ONES defect-create layout is incompatible",
                safe_message="当前项目的 ONES 缺陷创建布局与受管字段目录不一致",
                error_code="ones_bug_create_layout_mismatch",
            )
        project_uuid, project_name = _named(
            response.get("project"), "ones_bug_create_preflight_invalid"
        )
        issue_uuid, issue_name = _named(
            response.get("issue_type"), "ones_bug_create_preflight_invalid"
        )
        if project_uuid != request["project_uuid"] or (
            issue_uuid != self.catalog.fixed_issue_type_uuid or issue_name != "缺陷"
        ):
            raise OnesMcpError(
                "ONES project or fixed issue type validation failed",
                safe_message="所属项目或固定缺陷工作项类型不可用",
                error_code="ones_bug_create_project_or_type_invalid",
            )

        users = _named_list(response.get("users"), "ones_bug_create_preflight_invalid")
        products = _named_list(response.get("products"), "ones_bug_create_preflight_invalid")
        modules = _named_list(
            response.get("product_modules"), "ones_bug_create_preflight_invalid"
        )
        versions = _named_list(
            response.get("affected_versions"), "ones_bug_create_preflight_invalid"
        )
        users_by_id = {item["uuid"]: item["name"] for item in users}
        products_by_id = {item["uuid"]: item["name"] for item in products}
        modules_by_id = {item["uuid"]: item["name"] for item in modules}
        versions_by_id = {item["uuid"]: item["name"] for item in versions}
        if set(users_by_id) != set(user_uuids):
            raise self._reference_invalid("人员")
        if set(products_by_id) != set(request["product_uuids"]):
            raise self._reference_invalid("所属产品")
        if set(modules_by_id) != set(request["product_module_uuids"]):
            raise self._reference_invalid("所属功能模块")
        if set(versions_by_id) != set(request["affected_version_uuids"]):
            raise self._reference_invalid("影响版本")
        selected_products = set(request["product_uuids"])
        for module in modules:
            parents = module.get("product_uuids")
            if (
                not isinstance(parents, list)
                or not set(str(value) for value in parents).intersection(selected_products)
            ):
                raise OnesMcpError(
                    "ONES product module relation is invalid",
                    safe_message="所属功能模块不属于已选产品",
                    error_code="ones_bug_create_product_module_mismatch",
                )
        if any(str(item.get("kind") or "") != "affected" for item in versions):
            raise OnesMcpError(
                "ONES version kind is not affected",
                safe_message="影响版本不能混用修复版本或验证版本",
                error_code="ones_bug_create_version_kind_mismatch",
            )
        validation = {
            "layout_version": layout_version,
            "project_uuid": project_uuid,
            "issue_type_uuid": issue_uuid,
            "user_uuids": sorted(users_by_id),
            "product_uuids": sorted(products_by_id),
            "product_module_uuids": sorted(modules_by_id),
            "affected_version_uuids": sorted(versions_by_id),
        }
        return BugCreatePreflight(
            layout_version=layout_version,
            validation_hash=json_hash(validation),
            display_values={
                "project_uuid": {project_uuid: project_name},
                "user_uuids": users_by_id,
                "product_uuids": products_by_id,
                "product_module_uuids": modules_by_id,
                "affected_version_uuids": versions_by_id,
            },
        )

    @staticmethod
    def _reference_invalid(label: str) -> OnesMcpError:
        return OnesMcpError(
            "ONES bug-create dynamic reference is invalid",
            safe_message=f"{label}不存在、已失效或无法唯一验证",
            error_code="ones_bug_create_reference_invalid",
        )

    def create_bug(
        self,
        *,
        team_uuid: str,
        provider_user_id: str,
        token: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        team_uuid = _identifier(team_uuid)
        provider_user_id = _identifier(provider_user_id)
        self.catalog.require_team(team_uuid)
        tasks = payload.get("tasks")
        if set(payload) != {"tasks"} or not isinstance(tasks, list) or len(tasks) != 1:
            raise OnesMcpError(
                "ONES bug-create payload is invalid",
                safe_message="ONES 缺陷创建请求无效",
                error_code="ones_bug_create_payload_invalid",
            )
        response = self.http.post_json(
            f"/project/api/project/team/{team_uuid}/tasks/add3",
            payload,
            headers={
                PROVIDER_HEADERS["token"]: token,
                PROVIDER_HEADERS["user"]: provider_user_id,
            },
        )
        tasks_response = response.get("tasks")
        bad_tasks = response.get("bad_tasks")
        if (
            not isinstance(tasks_response, list)
            or len(tasks_response) != 1
            or bad_tasks != []
        ):
            raise invalid_provider_response("ones_bug_create_response_invalid")
        task = _object(tasks_response[0], "ones_bug_create_response_invalid")
        requested = _object(tasks[0], "ones_bug_create_payload_invalid")
        number = task.get("number")
        if (
            str(task.get("uuid") or "") != str(requested.get("uuid") or "")
            or str(task.get("project_uuid") or "") != str(requested.get("project_uuid") or "")
            or str(task.get("issue_type_uuid") or "")
            != self.catalog.fixed_issue_type_uuid
            or str(task.get("summary") or "") != str(requested.get("summary") or "")
            or type(number) is not int
        ):
            raise invalid_provider_response("ones_bug_create_response_invalid")
        return {"uuid": str(task["uuid"]), "number": number, "status": "created"}

    def read_created_bug(
        self,
        *,
        team_uuid: str,
        task_uuid: str,
        provider_user_id: str,
        token: str,
    ) -> dict[str, Any] | None:
        team_uuid = _identifier(team_uuid)
        task_uuid = _identifier(task_uuid)
        provider_user_id = _identifier(provider_user_id)
        self.catalog.require_team(team_uuid)
        response = self.http.get_json(
            f"/project/api/project/team/{team_uuid}/tasks/{task_uuid}/create_readback",
            None,
            headers={
                PROVIDER_HEADERS["token"]: token,
                PROVIDER_HEADERS["user"]: provider_user_id,
            },
        )
        if response.get("found") is False:
            return None
        task = _object(response.get("task"), "ones_bug_create_readback_invalid")
        if str(task.get("uuid") or "") != task_uuid or type(task.get("number")) is not int:
            raise invalid_provider_response("ones_bug_create_readback_invalid")
        allowed = {
            "uuid",
            "number",
            "summary",
            "assign",
            "parent_uuid",
            "issue_type_uuid",
            "project_uuid",
            "watchers",
            "field_values",
            "add_manhours",
        }
        if set(task) != allowed:
            raise invalid_provider_response("ones_bug_create_readback_invalid")
        McpAuditCoordinator.reject_auth_material(task)
        return task

    @staticmethod
    def request_hash(payload: dict[str, Any]) -> str:
        return json_hash(payload)


def validate_create_contract() -> None:
    contract = require_ones_tool_contract(ONES_CREATE_BUG_TOOL_IDENTIFIER)
    if contract.operation_code != "ones.task.create" or contract.effect != "mutation":
        raise ValueError("ONES bug-create Tool contract is inconsistent")


validate_create_contract()
