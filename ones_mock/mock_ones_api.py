from __future__ import annotations

import os
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
        tasks.append(
            {
                "number": _require_int(task.get("number"), f"tasks[{index}].number"),
                "name": _require_str(task.get("name"), f"tasks[{index}].name"),
                "issue_type": _require_str(task.get("issue_type"), f"tasks[{index}].issue_type"),
                "owner_uuid": _require_str(task.get("owner_uuid"), f"tasks[{index}].owner_uuid"),
                "status": _require_str(task.get("status"), f"tasks[{index}].status"),
                "priority": _require_str(task.get("priority"), f"tasks[{index}].priority"),
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
    return {
        "_MOCK_CUSTOM_FIELD": None,
        "createTime": 1784736000000000 + number,
        "deadline": None,
        "estimatedHours": 0,
        "issueType": {
            "manhourStatisticMode": 0,
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
    keyword = _search_keyword(variables)
    tasks = [
        fixture
        for fixture in (_task_fixture(config, task) for task in config.tasks)
        if (not issue_types or str(fixture["issueType"]["uuid"]) in issue_types)
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

    if requested_scope not in {None, config.project_scope_uuid} or requested_scope_type not in {
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


def create_app(settings: MockOnesConfig | MockOnesSettings | None = None) -> FastAPI:
    if settings is None:
        config = get_default_config()
    elif isinstance(settings, MockOnesSettings):
        config = settings.config
    else:
        config = settings

    app = FastAPI(title="Mock ONES API", version="0.3.0")
    app.state.ones_mock_config = config

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

    @app.get(
        "/project/api/project/team/{team_uuid}/project/{project_uuid}/role_members"
    )
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
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_query_type",
                "message": f"unsupported mock query type: {query_type}",
            },
        )

    return app


try:
    MOCK_ISSUE_TYPES = get_default_config().issue_types
except FileNotFoundError:
    MOCK_ISSUE_TYPES = {}
