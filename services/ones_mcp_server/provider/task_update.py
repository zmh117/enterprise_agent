from __future__ import annotations

import re
from typing import Any

from app.modules.mcp_audit import McpAuditCoordinator
from services.ones_mcp_server.contracts import PROVIDER_HEADERS
from services.ones_mcp_server.errors import OnesMcpError, invalid_provider_response
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient
from services.ones_mcp_server.provider.rest import PROJECT_SPRINTS_OPERATION, TEAM_USERS_OPERATION
from services.ones_mcp_server.task_update import OnesTaskSnapshot
from services.ones_mcp_server.task_update_catalog import TaskUpdateField, TaskUpdateFieldCatalog


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

TASK_UPDATE_DETAIL_DOCUMENT = """query GovernedTaskUpdateDetail($key: Key) {
  task(key: $key) {
    uuid number name serverUpdateStamp descriptionText
    project { uuid }
    issueType { uuid name }
    canEdit(attachPermission: {permissions: [\"update_tasks\"]})
    hasEditPermission(attachPermission: {permissions: [\"update_tasks\"]})
    canUpdateWatchers(attachPermission: {permissions: [\"update_task_watchers\"]})
    hasUpdateWatchersPermission(attachPermission: {permissions: [\"update_task_watchers\"]})
    assign { uuid name }
    watchers { uuid name }
    solver { uuid name }
    _VRS2LsBn { uuid name }
    _5BiPnrfy _F9eyqM3a _DmGDdhkv _LMb5XC7P _41TN9bsG
    defectType { uuid value }
    _FnkEKd4Y { uuid value }
    severityLevel { uuid value }
    _4v1yHkX9 { uuid value }
    _679m6U93 { uuid value }
    sprint { uuid name }
    products { uuid name }
    allProducts(stubTaskProducts: {}) { uuid name }
    productModules { uuid name }
    allProductModules(stubTaskProductModules: {}) { uuid name }
    _79WCF8hL { uuid value }
    isOnlineDefect { uuid value }
    _6FimuZwX { uuid value }
    _4ipdiS95 { uuid value }
    _MysgAE3y { uuid value }
    _LfbLTzsp { uuid value }
    _PxHXwe6T { uuid value }
    solution { uuid value }
    _2adoeHHw { uuid value }
    priority { uuid value }
  }
}"""


def _identifier(value: str, *, field: str) -> str:
    if _IDENTIFIER.fullmatch(value) is None:
        raise OnesMcpError(
            f"Invalid ONES {field}",
            safe_message="ONES 缺陷标识无效",
            error_code="ones_task_update_target_invalid",
        )
    return value


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise invalid_provider_response("ones_task_update_detail_invalid")
    return {str(key): item for key, item in value.items()}


def _value_and_display(field: TaskUpdateField, raw: object) -> tuple[Any, Any]:
    if raw is None:
        return ([] if field.value_kind in {"users", "entities", "options"} else "", "（空）")
    if field.value_kind in {"users", "entities", "options"}:
        if not isinstance(raw, list):
            raise invalid_provider_response("ones_task_update_detail_invalid")
        pairs = []
        for item in raw:
            value = _object(item)
            uuid = str(value.get("uuid") or "")
            name = str(value.get("name") or value.get("value") or "")
            if not uuid or not name:
                raise invalid_provider_response("ones_task_update_detail_invalid")
            pairs.append((uuid, name))
        pairs.sort()
        return ([uuid for uuid, _ in pairs], [name for _, name in pairs])
    if field.value_kind in {"user", "sprint", "option"}:
        value = _object(raw)
        uuid = str(value.get("uuid") or "")
        name = str(value.get("name") or value.get("value") or "")
        if not uuid:
            raise invalid_provider_response("ones_task_update_detail_invalid")
        return uuid, name or uuid
    if field.value_kind == "number":
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise invalid_provider_response("ones_task_update_detail_invalid")
        return raw, str(raw)
    if not isinstance(raw, str):
        raise invalid_provider_response("ones_task_update_detail_invalid")
    return raw, raw or "（空）"


class OnesTaskUpdateProvider:
    def __init__(
        self,
        http: OnesProviderHttpClient,
        *,
        catalog: TaskUpdateFieldCatalog,
    ) -> None:
        self.http = http
        self.catalog = catalog

    def read_task(
        self,
        *,
        team_uuid: str,
        task_uuid: str,
        provider_user_id: str,
        token: str,
    ) -> OnesTaskSnapshot:
        team_uuid = _identifier(team_uuid, field="Team")
        task_uuid = _identifier(task_uuid, field="Task")
        provider_user_id = _identifier(provider_user_id, field="user")
        self.catalog.require_team(team_uuid)
        response = self.http.post_json(
            f"/project/api/project/team/{team_uuid}/items/graphql",
            {
                "query": TASK_UPDATE_DETAIL_DOCUMENT,
                "variables": {"key": f"task-{task_uuid}"},
            },
            headers={
                PROVIDER_HEADERS["token"]: token,
                PROVIDER_HEADERS["user"]: provider_user_id,
            },
            query={"t": "Task"},
        )
        data = _object(response.get("data"))
        task = _object(data.get("task"))
        if str(task.get("uuid") or "") != task_uuid:
            raise OnesMcpError(
                "ONES task was not found",
                safe_message="未找到可更新的 ONES 缺陷",
                error_code="ones_task_update_not_found",
            )
        project = _object(task.get("project"))
        issue_type = _object(task.get("issueType"))
        title = str(task.get("name") or "")
        stamp = str(task.get("serverUpdateStamp") or "")
        number = task.get("number")
        if not title or not stamp or type(number) is not int:
            raise invalid_provider_response("ones_task_update_detail_invalid")

        values: dict[str, Any] = {"title": title}
        displays: dict[str, Any] = {"title": title}
        available = {"title"}
        builtins = {
            "description": task.get("descriptionText"),
            "assignee_uuid": task.get("assign"),
            "watcher_uuids": task.get("watchers"),
        }
        for semantic_name, raw in builtins.items():
            if semantic_name == "description" and "descriptionText" not in task:
                continue
            if semantic_name == "assignee_uuid" and "assign" not in task:
                continue
            if semantic_name == "watcher_uuids" and "watchers" not in task:
                continue
            field = self.catalog.require_field(semantic_name)
            values[semantic_name], displays[semantic_name] = _value_and_display(field, raw)
            available.add(semantic_name)
        for field in self.catalog.fields:
            if field.semantic_name in values or field.semantic_name in {
                "title",
                "description",
                "assignee_uuid",
                "watcher_uuids",
            }:
                continue
            if field.source_key not in task:
                continue
            values[field.semantic_name], displays[field.semantic_name] = _value_and_display(
                field, task.get(field.source_key)
            )
            available.add(field.semantic_name)
        McpAuditCoordinator.reject_auth_material(task)
        allowed_entities = {
            "product_uuids": self._named_entities(task.get("allProducts")),
            "product_module_uuids": self._named_entities(task.get("allProductModules")),
        }
        return OnesTaskSnapshot(
            uuid=task_uuid,
            number=number,
            title=title,
            issue_type_name=str(issue_type.get("name") or ""),
            project_uuid=str(project.get("uuid") or ""),
            team_uuid=team_uuid,
            server_update_stamp=stamp,
            can_edit=bool(task.get("canEdit")) and bool(task.get("hasEditPermission")),
            can_update_watchers=bool(task.get("canUpdateWatchers"))
            and bool(task.get("hasUpdateWatchersPermission")),
            available_fields=frozenset(available),
            values=values,
            display_values=displays,
            allowed_entities=allowed_entities,
        )

    @staticmethod
    def _named_entities(raw: object) -> dict[str, str]:
        if raw is None:
            return {}
        if not isinstance(raw, list) or len(raw) > 2000:
            raise invalid_provider_response("ones_task_update_detail_invalid")
        result: dict[str, str] = {}
        for item in raw:
            value = _object(item)
            uuid = str(value.get("uuid") or "")
            name = str(value.get("name") or "")
            if not uuid or not name or uuid in result:
                raise invalid_provider_response("ones_task_update_detail_invalid")
            result[uuid] = name
        return result

    def resolve_entities(
        self,
        *,
        snapshot: OnesTaskSnapshot,
        arguments: dict[str, Any],
        provider_user_id: str,
        token: str,
    ) -> dict[str, dict[str, str]]:
        resolved: dict[str, dict[str, str]] = {}
        user_fields = (
            "assignee_uuid",
            "resolver_uuid",
            "owner_uuids",
            "watcher_uuids",
        )
        user_uuids: set[str] = set()
        for semantic_name in user_fields:
            value = arguments.get(semantic_name)
            if isinstance(value, str) and value:
                user_uuids.add(value)
            elif isinstance(value, list):
                user_uuids.update(str(item) for item in value)
        user_names: dict[str, str] = {}
        if user_uuids:
            execution = TEAM_USERS_OPERATION.execute(
                self.http,
                team_uuid=snapshot.team_uuid,
                member_uuids=sorted(user_uuids),
                token=token,
                user_id=provider_user_id,
            )
            user_names = execution.output
            if set(user_names) != user_uuids:
                raise OnesMcpError(
                    "ONES task-update user target is not unique in the current Team",
                    safe_message="缺陷更新中的人员不存在、已失效或无法唯一解析",
                    error_code="ones_task_update_entity_invalid",
                )
        for semantic_name in user_fields:
            if semantic_name in arguments:
                resolved[semantic_name] = user_names

        sprint_uuid = arguments.get("sprint_uuid")
        if isinstance(sprint_uuid, str) and sprint_uuid:
            execution = PROJECT_SPRINTS_OPERATION.execute(
                self.http,
                team_uuid=snapshot.team_uuid,
                project_uuid=snapshot.project_uuid,
                limit=100,
                token=token,
                user_id=provider_user_id,
            )
            matches = {
                str(item["uuid"]): str(item["name"])
                for item in execution.output["sprints"]
                if str(item["uuid"]) == sprint_uuid
            }
            if len(matches) != 1:
                raise OnesMcpError(
                    "ONES task-update sprint is unavailable for the current project",
                    safe_message="所属迭代不属于当前缺陷项目或已失效",
                    error_code="ones_task_update_entity_invalid",
                )
            resolved["sprint_uuid"] = matches

        for semantic_name in ("product_uuids", "product_module_uuids"):
            if semantic_name not in arguments:
                continue
            values = arguments[semantic_name]
            allowed = snapshot.allowed_entities.get(semantic_name, {})
            if not isinstance(values, list) or any(str(value) not in allowed for value in values):
                raise OnesMcpError(
                    "ONES task-update entity is unavailable for the current defect",
                    safe_message="所属产品或功能模块不适用于当前缺陷",
                    error_code="ones_task_update_entity_invalid",
                )
            resolved[semantic_name] = allowed
        return resolved

    def update_task(
        self,
        *,
        team_uuid: str,
        provider_user_id: str,
        token: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        team_uuid = _identifier(team_uuid, field="Team")
        provider_user_id = _identifier(provider_user_id, field="user")
        self.catalog.require_team(team_uuid)
        tasks = payload.get("tasks")
        if set(payload) != {"tasks"} or not isinstance(tasks, list) or len(tasks) != 1:
            raise OnesMcpError(
                "ONES task-update payload is invalid",
                safe_message="ONES 缺陷更新请求无效",
                error_code="ones_task_update_payload_invalid",
            )
        response = self.http.post_json(
            f"/project/api/project/team/{team_uuid}/tasks/update3",
            payload,
            headers={
                PROVIDER_HEADERS["token"]: token,
                PROVIDER_HEADERS["user"]: provider_user_id,
            },
        )
        bad_tasks = response.get("bad_tasks")
        if not isinstance(bad_tasks, list):
            raise invalid_provider_response("ones_task_update_response_invalid")
        if bad_tasks:
            raise OnesMcpError(
                "ONES Provider rejected one or more task updates",
                safe_message="ONES 未接受本次缺陷更新",
                error_code="ones_task_update_rejected",
            )
        return {"updated": True, "bad_tasks": []}
