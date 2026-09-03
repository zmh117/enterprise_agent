from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field


DEFAULT_CONFIG_PATH = Path(__file__).resolve().with_name("mock.yaml")


@dataclass(frozen=True)
class MockOnesUser:
    email: str
    password: str
    uuid: str
    name: str
    token: str


@dataclass(frozen=True)
class MockOnesConfig:
    users: tuple[MockOnesUser, ...]
    team_uuid: str
    team_name: str
    project_uuid: str
    project_name: str
    project_scope_uuid: str
    project_scope_name_pinyin: str
    invalid_response_email: str
    control_passwords: dict[str, str]
    issue_types: dict[str, dict[str, Any]]
    priorities: dict[str, dict[str, Any]]
    statuses: dict[str, dict[str, Any]]
    project_roles: tuple[dict[str, Any], ...]
    tasks: tuple[dict[str, Any], ...]
    additional_teams: tuple[dict[str, str], ...] = ()

    @property
    def primary_user(self) -> MockOnesUser:
        if not self.users:
            raise ValueError("mock.yaml must define at least one user")
        return self.users[0]

    def find_user_by_credentials(self, email: str, password: str) -> MockOnesUser | None:
        for user in self.users:
            if user.email == email and user.password == password:
                return user
        return None

    def find_user_by_auth(self, *, token: str, user_uuid: str) -> MockOnesUser | None:
        for user in self.users:
            if user.token == token and user.uuid == user_uuid:
                return user
        return None

    def user_by_uuid(self, user_uuid: str) -> MockOnesUser | None:
        for user in self.users:
            if user.uuid == user_uuid:
                return user
        return None

    @property
    def teams(self) -> tuple[dict[str, str], ...]:
        return (
            {"uuid": self.team_uuid, "name": self.team_name},
            *self.additional_teams,
        )


@dataclass(frozen=True)
class MockOnesSettings:
    """Compatibility view used by unit tests (primary user + shared team/project)."""

    config: MockOnesConfig = field(default_factory=lambda: load_config())

    @property
    def email(self) -> str:
        return self.config.primary_user.email

    @property
    def password(self) -> str:
        return self.config.primary_user.password

    @property
    def user_uuid(self) -> str:
        return self.config.primary_user.uuid

    @property
    def user_name(self) -> str:
        return self.config.primary_user.name

    @property
    def token(self) -> str:
        return self.config.primary_user.token

    @property
    def team_uuid(self) -> str:
        return self.config.team_uuid

    @property
    def team_name(self) -> str:
        return self.config.team_name

    @property
    def project_scope_uuid(self) -> str:
        return self.config.project_scope_uuid

    @property
    def invalid_response_email(self) -> str:
        return self.config.invalid_response_email

    @classmethod
    def from_environment(cls) -> MockOnesSettings:
        return cls(config=load_config())


def _require_mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a mapping")
    return value


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def load_config(path: str | Path | None = None) -> MockOnesConfig:
    config_path = Path(path or os.getenv("ONES_MOCK_CONFIG") or DEFAULT_CONFIG_PATH)
    if not config_path.is_file():
        raise FileNotFoundError(f"ONES mock config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data = _require_mapping(raw, "mock.yaml")

    team = _require_mapping(data.get("team"), "team")
    project = _require_mapping(data.get("project"), "project")
    users_raw = data.get("users")
    if not isinstance(users_raw, list) or len(users_raw) < 1:
        raise ValueError("users must be a non-empty list")

    users: list[MockOnesUser] = []
    seen_emails: set[str] = set()
    seen_uuids: set[str] = set()
    for index, item in enumerate(users_raw):
        user_data = _require_mapping(item, f"users[{index}]")
        email = _require_str(user_data.get("email"), f"users[{index}].email")
        uuid = _require_str(user_data.get("uuid"), f"users[{index}].uuid")
        if email in seen_emails:
            raise ValueError(f"duplicate user email: {email}")
        if uuid in seen_uuids:
            raise ValueError(f"duplicate user uuid: {uuid}")
        seen_emails.add(email)
        seen_uuids.add(uuid)
        users.append(
            MockOnesUser(
                email=email,
                password=_require_str(user_data.get("password"), f"users[{index}].password"),
                uuid=uuid,
                name=_require_str(user_data.get("name"), f"users[{index}].name"),
                token=_require_str(user_data.get("token"), f"users[{index}].token"),
            )
        )

    issue_types = _require_mapping(data.get("issue_types"), "issue_types")
    priorities = _require_mapping(data.get("priorities"), "priorities")
    statuses = _require_mapping(data.get("statuses"), "statuses")
    project_roles_raw = data.get("project_roles") or []
    if not isinstance(project_roles_raw, list):
        raise ValueError("project_roles must be a list")
    project_roles: list[dict[str, Any]] = []
    for index, item in enumerate(project_roles_raw):
        role = _require_mapping(item, f"project_roles[{index}]")
        member_uuids = role.get("member_uuids") or []
        if not isinstance(member_uuids, list) or any(
            not isinstance(value, str) or not value for value in member_uuids
        ):
            raise ValueError(f"project_roles[{index}].member_uuids must be strings")
        project_roles.append(
            {
                "uuid": _require_str(role.get("uuid"), f"project_roles[{index}].uuid"),
                "name": _require_str(role.get("name"), f"project_roles[{index}].name"),
                "member_uuids": list(member_uuids),
            }
        )
    tasks_raw = data.get("tasks") or []
    if not isinstance(tasks_raw, list):
        raise ValueError("tasks must be a list")

    tasks: list[dict[str, Any]] = []
    for index, item in enumerate(tasks_raw):
        task = _require_mapping(item, f"tasks[{index}]")
        custom_options = _require_mapping(
            task.get("custom_options") or {},
            f"tasks[{index}].custom_options",
        )
        tasks.append(
            {
                "number": _require_int(task.get("number"), f"tasks[{index}].number"),
                "name": _require_str(task.get("name"), f"tasks[{index}].name"),
                "issue_type": _require_str(task.get("issue_type"), f"tasks[{index}].issue_type"),
                "owner_uuid": _require_str(task.get("owner_uuid"), f"tasks[{index}].owner_uuid"),
                "status": _require_str(task.get("status"), f"tasks[{index}].status"),
                "priority": _require_str(task.get("priority"), f"tasks[{index}].priority"),
                "custom_options": {
                    _require_str(key, f"tasks[{index}].custom_options field"): _require_str(
                        value,
                        f"tasks[{index}].custom_options.{key}",
                    )
                    for key, value in custom_options.items()
                },
            }
        )

    additional_teams_raw = data.get("additional_teams") or []
    if not isinstance(additional_teams_raw, list):
        raise ValueError("additional_teams must be a list")
    additional_teams = tuple(
        {
            "uuid": _require_str(
                _require_mapping(
                    value,
                    f"additional_teams[{index}]",
                ).get("uuid"),
                f"additional_teams[{index}].uuid",
            ),
            "name": _require_str(
                _require_mapping(
                    value,
                    f"additional_teams[{index}]",
                ).get("name"),
                f"additional_teams[{index}].name",
            ),
        }
        for index, value in enumerate(additional_teams_raw)
    )

    return MockOnesConfig(
        users=tuple(users),
        team_uuid=_require_str(team.get("uuid"), "team.uuid"),
        team_name=_require_str(team.get("name"), "team.name"),
        project_uuid=_require_str(project.get("uuid"), "project.uuid"),
        project_name=_require_str(project.get("name"), "project.name"),
        project_scope_uuid=_require_str(project.get("scope_uuid"), "project.scope_uuid"),
        project_scope_name_pinyin=_require_str(
            project.get("scope_name_pinyin") or "mock-project",
            "project.scope_name_pinyin",
        ),
        invalid_response_email=_require_str(
            data.get("invalid_response_email"),
            "invalid_response_email",
        ),
        control_passwords={
            str(key): _require_str(value, f"control_passwords.{key}")
            for key, value in _require_mapping(
                data.get("control_passwords"),
                "control_passwords",
            ).items()
        },
        issue_types={
            str(key): _require_mapping(value, f"issue_types.{key}")
            for key, value in issue_types.items()
        },
        priorities={
            str(key): _require_mapping(value, f"priorities.{key}")
            for key, value in priorities.items()
        },
        statuses={
            str(key): _require_mapping(value, f"statuses.{key}") for key, value in statuses.items()
        },
        project_roles=tuple(project_roles),
        tasks=tuple(tasks),
        additional_teams=additional_teams,
    )


@lru_cache(maxsize=1)
def get_default_config() -> MockOnesConfig:
    return load_config()


class LoginRequest(BaseModel):
    email: str
    password: str


class GraphqlRequest(BaseModel):
    query: str = Field(min_length=1)
    variables: dict[str, Any] = Field(default_factory=dict)


class TeamUsersRequest(BaseModel):
    uuids: list[str] = Field(min_length=1, max_length=2000)


_TASK_UPDATE_FIELD_SOURCES = {
    "5BiPnrfy": "_5BiPnrfy",
    "F9eyqM3a": "_F9eyqM3a",
    "field040": "solver",
    "VRS2LsBn": "_VRS2LsBn",
    "field008": "watchers",
    "field041": "defectType",
    "FnkEKd4Y": "_FnkEKd4Y",
    "field038": "severityLevel",
    "4v1yHkX9": "_4v1yHkX9",
    "679m6U93": "_679m6U93",
    "field011": "sprint",
    "field029": "products",
    "field030": "productModules",
    "79WCF8hL": "_79WCF8hL",
    "field031": "isOnlineDefect",
    "6FimuZwX": "_6FimuZwX",
    "4ipdiS95": "_4ipdiS95",
    "MysgAE3y": "_MysgAE3y",
    "LfbLTzsp": "_LfbLTzsp",
    "LMb5XC7P": "_LMb5XC7P",
    "PxHXwe6T": "_PxHXwe6T",
    "DmGDdhkv": "_DmGDdhkv",
    "field039": "solution",
    "41TN9bsG": "_41TN9bsG",
    "2adoeHHw": "_2adoeHHw",
    "field012": "priority",
}

_BUG_CREATE_REQUIRED_FIELD_UUIDS = {
    "field001",
    "field016",
    "5BiPnrfy",
    "field004",
    "field041",
    "FnkEKd4Y",
    "field038",
    "4v1yHkX9",
    "679m6U93",
    "field029",
    "field030",
    "79WCF8hL",
    "field031",
    "6FimuZwX",
    "4ipdiS95",
}
_BUG_ISSUE_TYPE_UUID = "B4TV9bu5"


def _task_fixture(config: MockOnesConfig, task: dict[str, Any]) -> dict[str, Any]:
    issue_type_key = str(task["issue_type"])
    if issue_type_key not in config.issue_types:
        raise ValueError(f"unknown issue_type: {issue_type_key}")
    issue_type = config.issue_types[issue_type_key]
    priority_key = str(task["priority"])
    status_key = str(task["status"])
    if priority_key not in config.priorities:
        raise ValueError(f"unknown priority: {priority_key}")
    if status_key not in config.statuses:
        raise ValueError(f"unknown status: {status_key}")
    priority = config.priorities[priority_key]
    status = config.statuses[status_key]
    owner = config.user_by_uuid(str(task["owner_uuid"]))
    owner_name = owner.name if owner is not None else "Mock Owner"
    owner_uuid = str(task["owner_uuid"])
    number = int(task["number"])
    task_uuid = f"MOCK-ONES-TASK-{number}"
    fixture = {
        "_MOCK_CUSTOM_FIELD": None,
        "createTime": 1784736000000000 + number,
        "deadline": None,
        "estimatedHours": 0,
        "issueType": {
            "manhourStatisticMode": 0,
            "name": issue_type["name"],
            "uuid": issue_type["uuid"],
        },
        "issueTypeScope": {"uuid": issue_type["scope_uuid"]},
        "key": f"task-{task_uuid}",
        "name": task["name"],
        "number": number,
        "owner": {
            "avatar": "",
            "key": f"user-{owner_uuid}",
            "name": owner_name,
            "uuid": owner_uuid,
        },
        "assign": {
            "name": owner_name,
            "uuid": owner_uuid,
        },
        "parent": {"uuid": ""},
        "path": task_uuid,
        "position": 0,
        "priority": {
            "bgColor": priority.get("bg_color") or "#e8f5e9",
            "color": priority.get("color") or "#2e7d32",
            "position": int(priority.get("position") or 0),
            "uuid": priority["uuid"],
            "value": priority["value"],
        },
        "project": {
            "key": f"project-{config.project_uuid}",
            "name": config.project_name,
            "uuid": config.project_uuid,
        },
        "remainingManhour": 0,
        "serverUpdateStamp": 1784736001000000 + number,
        "sprint": {
            "name": "Mock Active Sprint",
            "uuid": "MOCK-ONES-SPRINT-ACTIVE",
        },
        "status": {
            "category": status["category"],
            "name": status["name"],
            "uuid": status["uuid"],
        },
        "subIssueType": None,
        "subTaskCount": 0,
        "subTaskDoneCount": 0,
        "subTasks": [],
        "totalEstimatedHours": 0,
        "totalRemainingHours": 0,
        "uuid": task_uuid,
    }
    for field_uuid, option_uuid in task.get("custom_options", {}).items():
        fixture[f"_{field_uuid}"] = {
            "uuid": option_uuid,
            "value": option_uuid,
        }
    return fixture


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _issue_type_filter(variables: dict[str, Any]) -> set[str]:
    groups = variables.get("filterGroup")
    if not isinstance(groups, list):
        return set()
    values: set[str] = set()
    for group in groups:
        if isinstance(group, dict):
            values.update(_string_list(group.get("issueType_in")))
    return values


def _group_filter_values(variables: dict[str, Any], field: str) -> set[str]:
    groups = variables.get("filterGroup")
    if not isinstance(groups, list):
        return set()
    values: set[str] = set()
    for group in groups:
        if isinstance(group, dict):
            values.update(_string_list(group.get(field)))
    return values


def _created_range(variables: dict[str, Any]) -> dict[str, int]:
    groups = variables.get("filterGroup")
    if not isinstance(groups, list):
        return {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        value = group.get("createTime_range")
        if not isinstance(value, dict):
            continue
        result: dict[str, int] = {}
        for key in ("gte", "lte"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.isdigit():
                result[key] = int(raw)
        return result
    return {}


def _custom_option_filters(variables: dict[str, Any]) -> dict[str, set[str]]:
    groups = variables.get("filterGroup")
    if not isinstance(groups, list):
        return {}
    result: dict[str, set[str]] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        for key, value in group.items():
            if not key.startswith("_") or not key.endswith("_in"):
                continue
            values = set(_string_list(value))
            if values:
                result[key.removesuffix("_in")] = values
    return result


def _matches_custom_options(
    fixture: dict[str, Any],
    custom_filters: dict[str, set[str]],
) -> bool:
    for field_key, allowed in custom_filters.items():
        value = fixture.get(field_key)
        if not isinstance(value, dict) or str(value.get("uuid") or "") not in allowed:
            return False
    return True


def _search_keyword(variables: dict[str, Any]) -> str:
    search = variables.get("search")
    if not isinstance(search, dict):
        return ""
    keyword = search.get("keyword")
    return keyword.strip() if isinstance(keyword, str) else ""


def _page_limit(variables: dict[str, Any]) -> int:
    pagination = variables.get("pagination")
    if not isinstance(pagination, dict):
        return 500
    limit = pagination.get("limit")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return 500
    return min(limit, 1000)


def _matches_keyword(task: dict[str, Any], keyword: str) -> bool:
    normalized = keyword.removeprefix("#").strip().casefold()
    if not normalized:
        return True
    return (
        normalized in str(task["number"]).casefold() or normalized in str(task["name"]).casefold()
    )


def _group_task_data(config: MockOnesConfig, variables: dict[str, Any]) -> dict[str, Any]:
    issue_types = _issue_type_filter(variables)
    projects = _group_filter_values(variables, "project_in")
    sprints = _group_filter_values(variables, "sprint_in")
    statuses = _group_filter_values(variables, "status_in")
    status_categories = _group_filter_values(variables, "statusCategory_in")
    assignees = _group_filter_values(variables, "assign_in")
    custom_filters = _custom_option_filters(variables)
    created = _created_range(variables)
    keyword = _search_keyword(variables)
    tasks = [
        fixture
        for fixture in (_task_fixture(config, task) for task in config.tasks)
        if (not issue_types or str(fixture["issueType"]["uuid"]) in issue_types)
        and (not projects or str(fixture["project"]["uuid"]) in projects)
        and (not sprints or str(fixture["sprint"]["uuid"]) in sprints)
        and (not statuses or str(fixture["status"]["uuid"]) in statuses)
        and (not status_categories or str(fixture["status"]["category"]) in status_categories)
        and (not assignees or str(fixture["assign"]["uuid"]) in assignees)
        and _matches_custom_options(fixture, custom_filters)
        and ("gte" not in created or int(fixture["createTime"]) >= created["gte"])
        and ("lte" not in created or int(fixture["createTime"]) <= created["lte"])
        and _matches_keyword(fixture, keyword)
    ]
    total_count = len(tasks)
    tasks = tasks[: _page_limit(variables)]
    count = len(tasks)
    start_cursor = f"mock-cursor-{tasks[0]['number']}" if tasks else ""
    end_cursor = f"mock-cursor-{tasks[-1]['number']}" if tasks else ""
    return {
        "data": {
            "buckets": [
                {
                    "key": "bucket.0.__all",
                    "pageInfo": {
                        "count": count,
                        "totalCount": total_count,
                        "startPos": 0 if tasks else -1,
                        "startCursor": start_cursor,
                        "endPos": count - 1,
                        "endCursor": end_cursor,
                        "hasNextPage": total_count > count,
                        "preciseCount": total_count,
                    },
                    "tasks": tasks,
                }
            ]
        }
    }


def _issue_type_scopes(config: MockOnesConfig, variables: dict[str, Any]) -> dict[str, Any]:
    requested_scope: str | None = None
    requested_scope_type: int | None = None
    filters = variables.get("filter")
    if isinstance(filters, dict):
        scope = filters.get("scope_equal")
        scope_type = filters.get("scopeType_equal")
        requested_scope = scope if isinstance(scope, str) else None
        requested_scope_type = scope_type if isinstance(scope_type, int) else None

    if requested_scope not in {
        None,
        config.project_uuid,
        config.project_scope_uuid,
    } or requested_scope_type not in {
        None,
        1,
    }:
        return {"data": {"issueTypeScopes": []}}

    scopes = []
    for issue_type in config.issue_types.values():
        scopes.append(
            {
                "issueType": {
                    "builtIn": False,
                    "detailType": issue_type["detail_type"],
                    "icon": issue_type["icon"],
                    "key": f"issue_type-{issue_type['uuid']}",
                    "name": issue_type["name"],
                    "namePinyin": issue_type["name_pinyin"],
                    "subIssueType": False,
                    "uuid": issue_type["uuid"],
                },
                "name": issue_type["name"],
                "namePinyin": issue_type["name_pinyin"],
                "scope": config.project_scope_uuid,
                "scopeName": config.project_name,
                "scopeNamePinyin": config.project_scope_name_pinyin,
                "scopeType": 1,
                "scopeTypeName": "项目",
                "text": f"{issue_type['name']} 项目 {config.project_name}",
                "uuid": issue_type["scope_uuid"],
            }
        )
    return {"data": {"issueTypeScopes": scopes}}


def _project_list(config: MockOnesConfig, variables: dict[str, Any]) -> dict[str, Any]:
    filters = variables.get("projectFilterGroup")
    keyword = ""
    if isinstance(filters, list):
        for value in filters:
            if isinstance(value, dict) and isinstance(value.get("name_match"), str):
                keyword = str(value["name_match"]).strip().casefold()
                break
    projects = [
        {
            "uuid": config.project_uuid,
            "name": config.project_name,
            "status": {
                "uuid": "MOCK-PROJECT-STATUS-ACTIVE",
                "name": "进行中",
                "category": "in_progress",
            },
            "isSample": False,
            "isArchive": False,
            "owner": {
                "uuid": config.primary_user.uuid,
                "name": config.primary_user.name,
            },
        }
    ]
    if keyword:
        projects = [item for item in projects if keyword in str(item["name"]).casefold()]
    return {
        "data": {
            "buckets": [
                {
                    "projects": projects,
                    "pageInfo": {
                        "count": len(projects),
                        "totalCount": len(projects),
                        "endCursor": "mock-project-cursor" if projects else "",
                        "hasNextPage": False,
                    },
                }
            ]
        }
    }


def _work_item_detail(
    config: MockOnesConfig,
    variables: dict[str, Any],
    *,
    task_state: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    key = variables.get("key")
    task_uuid = str(key or "").removeprefix("task-")
    task = task_state.get(task_uuid) if task_state is not None else None
    if task is None and task_state is None:
        task = next(
            (
                _task_fixture(config, value)
                for value in config.tasks
                if key == f"task-MOCK-ONES-TASK-{value['number']}"
            ),
            None,
        )
    if task is None:
        return {"data": {"task": None}}
    return {"data": {"task": deepcopy(task)}}


def _task_update_detail_fixture(
    config: MockOnesConfig,
    task: dict[str, Any],
) -> dict[str, Any]:
    fixture = _task_fixture(config, task)
    fixture.update(
        {
            "descriptionText": "Synthetic work item detail for ONES MCP tests.",
            "relatedTasks": [],
            "canEdit": True,
            "hasEditPermission": True,
            "canUpdateWatchers": True,
            "hasUpdateWatchersPermission": True,
            "watchers": [],
            "solver": fixture["assign"],
            "_VRS2LsBn": [],
            "_5BiPnrfy": "",
            "_F9eyqM3a": "",
            "_LMb5XC7P": "",
            "_DmGDdhkv": 0,
            "_41TN9bsG": "",
            "products": [],
            "allProducts": [{"uuid": "MOCK-PRODUCT-001", "name": "Mock Product"}],
            "productModules": [],
            "allProductModules": [
                {"uuid": "MOCK-PRODUCT-MODULE-001", "name": "Mock Product Module"}
            ],
        }
    )
    for source in _TASK_UPDATE_FIELD_SOURCES.values():
        fixture.setdefault(source, None)
    return fixture


def _named_mock_entity(config: MockOnesConfig, uuid: str) -> dict[str, str]:
    user = config.user_by_uuid(uuid)
    return {"uuid": uuid, "name": user.name if user is not None else uuid}


def _apply_task_field_value(
    config: MockOnesConfig,
    task: dict[str, Any],
    value: dict[str, Any],
) -> bool:
    if set(value) != {"field_uuid", "type", "value"}:
        return False
    field_uuid = str(value.get("field_uuid") or "")
    source = _TASK_UPDATE_FIELD_SOURCES.get(field_uuid)
    field_type = value.get("type")
    raw = value.get("value")
    if source is None or isinstance(field_type, bool) or not isinstance(field_type, int):
        return False
    if field_type in {13, 16, 44, 46}:
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            return False
        task[source] = [_named_mock_entity(config, item) for item in raw]
    elif field_type in {1, 7, 8}:
        if not isinstance(raw, str) or not raw:
            return False
        if source == "priority":
            priority = next(
                (item for item in config.priorities.values() if item["uuid"] == raw),
                None,
            )
            task[source] = (
                {"uuid": raw, "value": str(priority["value"])}
                if priority is not None
                else {"uuid": raw, "value": raw}
            )
        else:
            task[source] = _named_mock_entity(config, raw)
    elif field_type == 4:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return False
        task[source] = raw
    elif field_type in {2, 15}:
        if not isinstance(raw, str):
            return False
        task[source] = raw
    else:
        return False
    return True


def _test_bucket(collection: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "data": {
            "buckets": [
                {
                    collection: items,
                    "pageInfo": {
                        "count": len(items),
                        "totalCount": len(items),
                        "endCursor": f"mock-{collection}-cursor" if items else "",
                        "hasNextPage": False,
                    },
                }
            ]
        }
    }


def _testcase_libraries() -> dict[str, Any]:
    return _test_bucket(
        "testcaseLibraries",
        [
            {
                "uuid": "MOCK-ONES-LIBRARY-001",
                "name": "Mock Regression Library",
                "isSample": False,
                "testcaseCaseCount": 1,
            }
        ],
    )


def _testcase_modules() -> dict[str, Any]:
    return {
        "data": {
            "testcaseModules": [
                {
                    "uuid": "MOCK-ONES-MODULE-001",
                    "name": "Mock Order Module",
                    "path": "MOCK-ONES-MODULE-001",
                    "parent": None,
                    "testcaseCaseCount": 1,
                }
            ]
        }
    }


def _test_plans(config: MockOnesConfig) -> dict[str, Any]:
    return _test_bucket(
        "testcasePlans",
        [
            {
                "uuid": "MOCK-ONES-PLAN-001",
                "name": "Mock Release Verification",
                "owner": {
                    "uuid": config.primary_user.uuid,
                    "name": config.primary_user.name,
                },
                "status": {"name": "进行中", "category": "in_progress"},
                "isSample": False,
            }
        ],
    )


def _test_cases(*, plan: bool) -> dict[str, Any]:
    item: dict[str, Any] = {"uuid": "MOCK-ONES-TESTCASE-001"}
    collection = "testcaseCases"
    if plan:
        collection = "testcasePlanCases"
        item = {"testcaseCase": item}
    return _test_bucket(collection, [item])


def _test_case_detail(config: MockOnesConfig) -> dict[str, Any]:
    return {
        "data": {
            "testcaseCases": [
                {
                    "uuid": "MOCK-ONES-TESTCASE-001",
                    "name": "Mock production order synchronization",
                    "condition": "Synthetic precondition.",
                    "desc": "Synthetic testcase detail.",
                    "assign": {
                        "uuid": config.primary_user.uuid,
                        "name": config.primary_user.name,
                    },
                    "createTime": 1784736000000000,
                    "testcaseLibrary": {"uuid": "MOCK-ONES-LIBRARY-001"},
                    "testcaseModule": {"uuid": "MOCK-ONES-MODULE-001"},
                    "path": "MOCK-ONES-MODULE-001",
                }
            ],
            "testcaseCaseSteps": [
                {
                    "index": 1,
                    "desc": "Run the synthetic action.",
                    "result": "The synthetic result is visible.",
                }
            ],
        }
    }


def create_app(settings: MockOnesConfig | MockOnesSettings | None = None) -> FastAPI:
    if settings is None:
        config = get_default_config()
    elif isinstance(settings, MockOnesSettings):
        config = settings.config
    else:
        config = settings

    app = FastAPI(title="Mock ONES API", version="0.3.0")
    app.state.ones_mock_config = config
    task_state = {
        str(fixture["uuid"]): fixture
        for fixture in (_task_update_detail_fixture(config, task) for task in config.tasks)
    }
    app.state.ones_mock_task_state = task_state
    created_bug_state: dict[str, dict[str, Any]] = {}
    app.state.ones_mock_created_bug_state = created_bug_state
    app.state.ones_mock_bug_create_mode = "success"

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "ones-mock",
            "users": len(config.users),
        }

    @app.post("/project/api/project/auth/login")
    async def login(payload: LoginRequest) -> dict[str, Any]:
        if payload.email == config.invalid_response_email:
            return {
                "user": {"name": "Invalid Mock User"},
                "teams": "invalid",
            }
        control_user = next(
            (user for user in config.users if user.email == payload.email),
            None,
        )
        if control_user is not None and payload.password == config.control_passwords.get(
            "subject_changed"
        ):
            return {
                "user": {
                    "uuid": control_user.uuid + "-CHANGED",
                    "email": control_user.email,
                    "name": control_user.name + " Changed",
                    "token": control_user.token,
                },
                "teams": list(config.teams),
            }
        if control_user is not None and payload.password == config.control_passwords.get(
            "team_missing"
        ):
            return {
                "user": {
                    "uuid": control_user.uuid,
                    "email": control_user.email,
                    "name": control_user.name,
                    "token": control_user.token,
                },
                "teams": [{"uuid": "MOCK-ONES-TEAM-MISSING", "name": "Missing Team"}],
            }
        user = config.find_user_by_credentials(payload.email, payload.password)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_credentials", "message": "invalid email or password"},
            )
        return {
            "user": {
                "uuid": user.uuid,
                "email": user.email,
                "name": user.name,
                "token": user.token,
            },
            "teams": list(config.teams),
        }

    @app.post("/project/api/project/items/graphql")
    async def governed_work_item_search(
        payload: GraphqlRequest,
        ones_auth_token: str | None = Header(
            default=None,
            alias="Ones-Auth-Token",
        ),
    ) -> Any:
        variables = payload.variables
        user_id = str(variables.get("user_id") or "")
        team_id = str(variables.get("team_id") or "")
        keyword = str(variables.get("keyword") or "")
        issue_type = str(variables.get("issue_type") or "")
        limit = variables.get("limit")
        user = config.find_user_by_auth(
            token=str(ones_auth_token or ""),
            user_uuid=user_id,
        )
        if keyword == "__401__" or user is None:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "unauthorized",
                    "message": "invalid ONES credential",
                },
            )
        if keyword in {"__403__", "__team_revoked__"}:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "forbidden",
                    "message": "team access revoked",
                },
            )
        if keyword == "__429__":
            raise HTTPException(
                status_code=429,
                detail={"code": "rate_limited"},
            )
        if keyword == "__500__":
            raise HTTPException(
                status_code=500,
                detail={"code": "server_error"},
            )
        if keyword == "__redirect__":
            return RedirectResponse("/health", status_code=307)
        if keyword == "__bad_json__":
            return Response(
                content="{not-json",
                media_type="application/json",
            )
        if keyword == "__oversize__":
            return Response(
                content='{"padding":"' + ("x" * 2_000_000) + '"}',
                media_type="application/json",
            )
        if team_id not in {str(item["uuid"]) for item in config.teams}:
            raise HTTPException(
                status_code=404,
                detail={"code": "team_not_found"},
            )
        if (
            issue_type not in {"demand", "task", "defect"}
            or not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 50
        ):
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_search_input"},
            )
        matches = [
            task
            for task in config.tasks
            if str(task["issue_type"]) == issue_type and _matches_keyword(task, keyword)
        ]
        items = [
            {
                "number": int(task["number"]),
                "name": str(task["name"]),
                "type": str(task["issue_type"]),
            }
            for task in matches[:limit]
        ]
        if keyword == "__missing_field__":
            items = [
                {
                    "name": "Malformed item",
                    "type": issue_type,
                }
            ]
        return {
            "data": {
                "workItems": {
                    "items": items,
                    "total": len(matches),
                    "truncated": len(matches) > len(items),
                }
            }
        }

    def require_business_user(
        *,
        ones_auth_token: str | None,
        ones_user_id: str | None,
        referer: str | None,
        cache_control: str | None,
    ) -> MockOnesUser:
        user = config.find_user_by_auth(
            token=str(ones_auth_token or ""),
            user_uuid=str(ones_user_id or ""),
        )
        if user is None:
            raise HTTPException(
                status_code=401,
                detail={"code": "unauthorized", "message": "invalid ONES auth headers"},
            )
        if not referer or cache_control != "no-cache":
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_required_headers"},
            )
        return user

    @app.get("/project/api/project/team/{team_uuid}/project/{project_uuid}/role_members")
    async def project_role_members(
        request: Request,
        team_uuid: str,
        project_uuid: str,
        ones_auth_token: str | None = Header(default=None, alias="Ones-Auth-Token"),
        ones_user_id: str | None = Header(default=None, alias="Ones-User-Id"),
        referer: str | None = Header(default=None, alias="Referer"),
        cache_control: str | None = Header(default=None, alias="cache-control"),
    ) -> dict[str, Any]:
        require_business_user(
            ones_auth_token=ones_auth_token,
            ones_user_id=ones_user_id,
            referer=referer,
            cache_control=cache_control,
        )
        try:
            request_body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail={"code": "empty_json_body_required"})
        if request_body != {}:
            raise HTTPException(status_code=400, detail={"code": "empty_json_body_required"})
        if team_uuid != config.team_uuid:
            raise HTTPException(status_code=404, detail={"code": "team_not_found"})
        if project_uuid == "MOCK-ONES-PROJECT-FORBIDDEN":
            raise HTTPException(status_code=403, detail={"code": "forbidden"})
        if project_uuid == "MOCK-ONES-PROJECT-EMPTY":
            return {"role_members": []}
        if project_uuid == "MOCK-ONES-PROJECT-MISSING-USER":
            return {
                "role_members": [
                    {
                        "role": {"uuid": "MOCK-ONES-ROLE-MISSING", "name": "Missing User"},
                        "members": ["MOCK-ONES-USER-MISSING"],
                    }
                ]
            }
        if project_uuid != config.project_uuid:
            raise HTTPException(status_code=404, detail={"code": "project_not_found"})
        return {
            "role_members": [
                {
                    "role": {
                        "uuid": role["uuid"],
                        "name": role["name"],
                        "built_in": role["uuid"] == "MOCK-ONES-ROLE-MEMBERS",
                    },
                    "members": list(role["member_uuids"]),
                }
                for role in config.project_roles
            ]
        }

    @app.post("/project/api/project/team/{team_uuid}/users")
    async def team_users(
        team_uuid: str,
        payload: TeamUsersRequest = Body(),
        ones_auth_token: str | None = Header(default=None, alias="Ones-Auth-Token"),
        ones_user_id: str | None = Header(default=None, alias="Ones-User-Id"),
        referer: str | None = Header(default=None, alias="Referer"),
        cache_control: str | None = Header(default=None, alias="cache-control"),
    ) -> dict[str, Any]:
        require_business_user(
            ones_auth_token=ones_auth_token,
            ones_user_id=ones_user_id,
            referer=referer,
            cache_control=cache_control,
        )
        if team_uuid != config.team_uuid:
            raise HTTPException(status_code=404, detail={"code": "team_not_found"})
        if "__403__" in payload.uuids:
            raise HTTPException(status_code=403, detail={"code": "forbidden"})
        users = []
        for user_uuid in dict.fromkeys(payload.uuids):
            user = config.user_by_uuid(user_uuid)
            if user is None:
                continue
            users.append(
                {
                    "uuid": user.uuid,
                    "name": user.name,
                    "email": user.email,
                    "phone": "",
                    "avatar": "https://mock.invalid/avatar",
                    "department_uuids": ["MOCK-DEPARTMENT"],
                }
            )
        return {"users": users}

    @app.post("/project/api/project/team/{team_uuid}/project/{project_uuid}/stamps/data")
    async def project_sprints(
        team_uuid: str,
        project_uuid: str,
        payload: dict[str, Any] = Body(),
        query_type: str = Query(alias="t"),
        ones_auth_token: str | None = Header(default=None, alias="Ones-Auth-Token"),
        ones_user_id: str | None = Header(default=None, alias="Ones-User-Id"),
        referer: str | None = Header(default=None, alias="Referer"),
        cache_control: str | None = Header(default=None, alias="cache-control"),
    ) -> dict[str, Any]:
        require_business_user(
            ones_auth_token=ones_auth_token,
            ones_user_id=ones_user_id,
            referer=referer,
            cache_control=cache_control,
        )
        if team_uuid != config.team_uuid or project_uuid != config.project_uuid:
            raise HTTPException(status_code=404, detail={"code": "project_not_found"})
        if query_type != "sprint" or payload != {"sprint": 0}:
            raise HTTPException(status_code=400, detail={"code": "invalid_sprint_query"})
        return {
            "sprint": {
                "sprints": [
                    {
                        "uuid": "MOCK-ONES-SPRINT-DONE",
                        "title": "Mock Completed Sprint",
                        "project_uuid": config.project_uuid,
                        "project_name": config.project_name,
                        "start_time": 1782144000000,
                        "end_time": 1782748800000,
                        "progress": 100,
                        "statuses": [{"category": "done", "is_current_status": True}],
                    },
                    {
                        "uuid": "MOCK-ONES-SPRINT-ACTIVE",
                        "title": "Mock Active Sprint",
                        "project_uuid": config.project_uuid,
                        "project_name": config.project_name,
                        "start_time": 1784563200000,
                        "end_time": 1785168000000,
                        "progress": 50,
                        "statuses": [{"category": "in_progress", "is_current_status": True}],
                    },
                ]
            }
        }

    @app.get("/project/api/project/team/{team_uuid}/task/{work_item_uuid}/messages")
    async def work_item_messages(
        team_uuid: str,
        work_item_uuid: str,
        ones_auth_token: str | None = Header(default=None, alias="Ones-Auth-Token"),
        ones_user_id: str | None = Header(default=None, alias="Ones-User-Id"),
        referer: str | None = Header(default=None, alias="Referer"),
        cache_control: str | None = Header(default=None, alias="cache-control"),
    ) -> dict[str, Any]:
        require_business_user(
            ones_auth_token=ones_auth_token,
            ones_user_id=ones_user_id,
            referer=referer,
            cache_control=cache_control,
        )
        if team_uuid != config.team_uuid:
            raise HTTPException(status_code=404, detail={"code": "team_not_found"})
        known = {f"MOCK-ONES-TASK-{task['number']}" for task in config.tasks}
        if work_item_uuid not in known:
            raise HTTPException(status_code=404, detail={"code": "task_not_found"})
        return {
            "messages": [
                {
                    "uuid": "MOCK-ONES-MESSAGE-001",
                    "type": "comment",
                    "send_time": 1784736000000,
                    "text": "Synthetic timeline message.",
                }
            ],
            "count": 1,
            "has_next": False,
        }

    @app.post("/project/api/project/team/{team_uuid}/users/search")
    async def search_team_users(
        team_uuid: str,
        payload: dict[str, Any] = Body(),
        ones_auth_token: str | None = Header(default=None, alias="Ones-Auth-Token"),
        ones_user_id: str | None = Header(default=None, alias="Ones-User-Id"),
        referer: str | None = Header(default=None, alias="Referer"),
        cache_control: str | None = Header(default=None, alias="cache-control"),
    ) -> dict[str, Any]:
        require_business_user(
            ones_auth_token=ones_auth_token,
            ones_user_id=ones_user_id,
            referer=referer,
            cache_control=cache_control,
        )
        if team_uuid != config.team_uuid:
            raise HTTPException(status_code=404, detail={"code": "team_not_found"})
        project_uuid = payload.get("project_uuid")
        if project_uuid not in {None, config.project_uuid}:
            return {"users": []}
        keyword = str(payload.get("keyword") or "").strip().casefold()
        users = [
            {"uuid": user.uuid, "name": user.name}
            for user in config.users
            if not keyword or keyword in user.name.casefold() or keyword in user.email.casefold()
        ]
        return {"users": users}

    @app.post("/project/api/project/team/{team_uuid}/items/graphql")
    async def graphql(
        team_uuid: str,
        payload: GraphqlRequest,
        query_type: str = Query(alias="t"),
        ones_auth_token: str | None = Header(default=None, alias="Ones-Auth-Token"),
        ones_user_id: str | None = Header(default=None, alias="Ones-User-Id"),
    ) -> dict[str, Any]:
        user = config.find_user_by_auth(
            token=str(ones_auth_token or ""),
            user_uuid=str(ones_user_id or ""),
        )
        if user is None:
            raise HTTPException(
                status_code=401,
                detail={"code": "unauthorized", "message": "invalid ONES auth headers"},
            )
        if team_uuid not in {str(item["uuid"]) for item in config.teams}:
            raise HTTPException(
                status_code=404,
                detail={"code": "team_not_found", "message": "mock team does not exist"},
            )
        if query_type == "group-task-data":
            return _group_task_data(config, payload.variables)
        if query_type == "issueTypeScopes":
            return _issue_type_scopes(config, payload.variables)
        if query_type == "projects-group-list-for-project-view":
            return _project_list(config, payload.variables)
        if query_type == "Task":
            return _work_item_detail(config, payload.variables, task_state=task_state)
        if query_type == "QUERY_LIBRARY_LIST":
            return _testcase_libraries()
        if query_type == "library-module-list-tree-NCdREx5Y":
            return _testcase_modules()
        if query_type == "plan-list":
            return _test_plans(config)
        if query_type == "library-testcase-list-uuids":
            return _test_cases(plan=False)
        if query_type == "plan-testcase-list-uuids":
            return _test_cases(plan=True)
        if query_type == "library-testcase-detail":
            return _test_case_detail(config)
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_query_type",
                "message": f"unsupported mock query type: {query_type}",
            },
        )

    def require_create_user(
        team_uuid: str,
        ones_auth_token: str | None,
        ones_user_id: str | None,
    ) -> MockOnesUser:
        user = config.find_user_by_auth(
            token=str(ones_auth_token or ""),
            user_uuid=str(ones_user_id or ""),
        )
        if user is None:
            raise HTTPException(status_code=401, detail={"code": "unauthorized"})
        if team_uuid != config.team_uuid:
            raise HTTPException(status_code=404, detail={"code": "team_not_found"})
        return user

    @app.post("/project/api/project/team/{team_uuid}/tasks/create_preflight")
    async def preflight_bug_create(
        request: Request,
        team_uuid: str,
        payload: dict[str, Any] = Body(),
        ones_auth_token: str | None = Header(default=None, alias="Ones-Auth-Token"),
        ones_user_id: str | None = Header(default=None, alias="Ones-User-Id"),
    ) -> dict[str, Any]:
        current = require_create_user(team_uuid, ones_auth_token, ones_user_id)
        mode = str(request.app.state.ones_mock_bug_create_mode)
        if mode == "not_ready":
            return {"ready": False, "can_create": False}
        project_uuid = str(payload.get("project_uuid") or "")
        if project_uuid != config.project_uuid or payload.get("issue_type_uuid") != _BUG_ISSUE_TYPE_UUID:
            return {"ready": True, "can_create": False}
        user_uuids = payload.get("user_uuids")
        products = payload.get("product_uuids")
        modules = payload.get("product_module_uuids")
        versions = payload.get("affected_version_uuids")
        if not isinstance(user_uuids, list):
            raise HTTPException(status_code=400, detail={"code": "invalid_preflight"})
        if not isinstance(products, list):
            raise HTTPException(status_code=400, detail={"code": "invalid_preflight"})
        if not isinstance(modules, list):
            raise HTTPException(status_code=400, detail={"code": "invalid_preflight"})
        if not isinstance(versions, list):
            raise HTTPException(status_code=400, detail={"code": "invalid_preflight"})
        known_users = {
            user.uuid: user.name for user in config.users if user.uuid in set(user_uuids)
        }
        known_products = {
            "MOCK-PRODUCT-001": "Mock Product",
            "NfvccPP5M3vRzNMY": "MES",
        }
        known_modules = {
            "MOCK-PRODUCT-MODULE-001": ("Mock Product Module", ["MOCK-PRODUCT-001"]),
            "BkcW9Bx4": ("称量", ["NfvccPP5M3vRzNMY"]),
        }
        if current.uuid not in known_users:
            known_users[current.uuid] = current.name
        return {
            "ready": True,
            "can_create": True,
            "layout_version": "mock-defect-create-v1",
            "required_field_uuids": sorted(_BUG_CREATE_REQUIRED_FIELD_UUIDS),
            "project": {"uuid": project_uuid, "name": config.project_name},
            "issue_type": {"uuid": _BUG_ISSUE_TYPE_UUID, "name": "缺陷"},
            "users": [
                {"uuid": uuid, "name": name} for uuid, name in sorted(known_users.items())
            ],
            "products": [
                {"uuid": uuid, "name": known_products.get(uuid, "")}
                for uuid in products
                if uuid in known_products
            ],
            "product_modules": [
                {
                    "uuid": uuid,
                    "name": known_modules[uuid][0],
                    "product_uuids": known_modules[uuid][1],
                }
                for uuid in modules
                if uuid in known_modules
            ],
            "affected_versions": [
                {"uuid": uuid, "name": f"Mock Affected Version {uuid}", "kind": "affected"}
                for uuid in versions
            ],
        }

    @app.post("/project/api/project/team/{team_uuid}/tasks/add3")
    async def create_bug(
        request: Request,
        team_uuid: str,
        payload: dict[str, Any] = Body(),
        ones_auth_token: str | None = Header(default=None, alias="Ones-Auth-Token"),
        ones_user_id: str | None = Header(default=None, alias="Ones-User-Id"),
    ) -> dict[str, Any]:
        require_create_user(team_uuid, ones_auth_token, ones_user_id)
        mode = str(request.app.state.ones_mock_bug_create_mode)
        tasks = payload.get("tasks")
        if set(payload) != {"tasks"} or not isinstance(tasks, list) or len(tasks) != 1:
            raise HTTPException(status_code=400, detail={"code": "invalid_payload"})
        task = tasks[0]
        if not isinstance(task, dict) or set(task) != {
            "uuid",
            "summary",
            "assign",
            "parent_uuid",
            "issue_type_uuid",
            "project_uuid",
            "watchers",
            "field_values",
            "add_manhours",
        }:
            raise HTTPException(status_code=400, detail={"code": "invalid_task"})
        task_uuid = str(task.get("uuid") or "")
        if mode == "conflict" or task_uuid in created_bug_state:
            raise HTTPException(status_code=409, detail={"code": "AlreadyExists.Task"})
        if mode in {"timeout", "disconnect"}:
            raise HTTPException(status_code=503, detail={"code": mode})
        if (
            task.get("parent_uuid") != ""
            or task.get("add_manhours") != []
            or task.get("issue_type_uuid") != _BUG_ISSUE_TYPE_UUID
            or task.get("project_uuid") != config.project_uuid
            or config.user_by_uuid(str(task.get("assign") or "")) is None
            or not isinstance(task.get("watchers"), list)
            or not isinstance(task.get("field_values"), list)
            or {str(value.get("field_uuid") or "") for value in task["field_values"] if isinstance(value, dict)}
            != _BUG_CREATE_REQUIRED_FIELD_UUIDS
        ):
            raise HTTPException(status_code=400, detail={"code": "invalid_task"})
        number = 900000 + len(created_bug_state) + 1
        stored = deepcopy(task)
        stored["number"] = number
        if mode == "mismatch":
            stored["summary"] = "Mock mismatched title"
        created_bug_state[task_uuid] = stored
        return {
            "tasks": [
                {
                    "uuid": task_uuid,
                    "project_uuid": task["project_uuid"],
                    "issue_type_uuid": task["issue_type_uuid"],
                    "summary": task["summary"],
                    "parent_uuid": "",
                    "number": number,
                }
            ],
            "bad_tasks": [],
        }

    @app.get(
        "/project/api/project/team/{team_uuid}/tasks/{task_uuid}/create_readback"
    )
    async def read_created_bug(
        team_uuid: str,
        task_uuid: str,
        ones_auth_token: str | None = Header(default=None, alias="Ones-Auth-Token"),
        ones_user_id: str | None = Header(default=None, alias="Ones-User-Id"),
    ) -> dict[str, Any]:
        require_create_user(team_uuid, ones_auth_token, ones_user_id)
        task = created_bug_state.get(task_uuid)
        if task is None:
            return {"found": False}
        return {"found": True, "task": deepcopy(task)}

    @app.post("/project/api/project/team/{team_uuid}/tasks/update3")
    async def update_tasks(
        team_uuid: str,
        payload: dict[str, Any] = Body(),
        ones_auth_token: str | None = Header(default=None, alias="Ones-Auth-Token"),
        ones_user_id: str | None = Header(default=None, alias="Ones-User-Id"),
    ) -> dict[str, Any]:
        user = config.find_user_by_auth(
            token=str(ones_auth_token or ""),
            user_uuid=str(ones_user_id or ""),
        )
        if user is None:
            raise HTTPException(
                status_code=401,
                detail={"code": "unauthorized", "message": "invalid ONES auth headers"},
            )
        if team_uuid not in {str(item["uuid"]) for item in config.teams}:
            raise HTTPException(
                status_code=404,
                detail={"code": "team_not_found", "message": "mock team does not exist"},
            )
        tasks = payload.get("tasks")
        if set(payload) != {"tasks"} or not isinstance(tasks, list) or len(tasks) != 1:
            return {"bad_tasks": [{"reason": "invalid_payload"}]}
        requested = tasks[0]
        if not isinstance(requested, dict):
            return {"bad_tasks": [{"reason": "invalid_task"}]}
        task_uuid = str(requested.get("uuid") or "")
        task = task_state.get(task_uuid)
        allowed = {
            "uuid",
            "name",
            "summary",
            "desc_rich",
            "descriptionText",
            "assign",
            "field_values",
        }
        if task is None or not set(requested).issubset(allowed):
            return {"bad_tasks": [{"uuid": task_uuid, "reason": "invalid_task"}]}
        candidate = deepcopy(task)
        name = requested.get("name")
        summary = requested.get("summary")
        if (name is None) != (summary is None) or (
            name is not None
            and (
                not isinstance(name, str)
                or not name
                or not isinstance(summary, str)
                or summary != name
            )
        ):
            return {"bad_tasks": [{"uuid": task_uuid, "reason": "invalid_title"}]}
        if isinstance(name, str):
            candidate["name"] = name
        if "descriptionText" in requested:
            description = requested["descriptionText"]
            rich = requested.get("desc_rich")
            if not isinstance(description, str) or not isinstance(rich, str):
                return {"bad_tasks": [{"uuid": task_uuid, "reason": "invalid_description"}]}
            candidate["descriptionText"] = description
        if "assign" in requested:
            assignee = requested["assign"]
            if not isinstance(assignee, str) or config.user_by_uuid(assignee) is None:
                return {"bad_tasks": [{"uuid": task_uuid, "reason": "invalid_assignee"}]}
            candidate["assign"] = _named_mock_entity(config, assignee)
        field_values = requested.get("field_values", [])
        if not isinstance(field_values, list) or any(
            not isinstance(item, dict) or not _apply_task_field_value(config, candidate, item)
            for item in field_values
        ):
            return {"bad_tasks": [{"uuid": task_uuid, "reason": "invalid_field_value"}]}
        candidate["serverUpdateStamp"] = int(candidate["serverUpdateStamp"]) + 1
        task_state[task_uuid] = candidate
        return {"bad_tasks": []}

    return app


try:
    MOCK_ISSUE_TYPES = get_default_config().issue_types
except FileNotFoundError:
    MOCK_ISSUE_TYPES = {}
