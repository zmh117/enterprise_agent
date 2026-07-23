from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class MockOnesSettings:
    email: str = "mock.user@example.test"
    password: str = "ones-mock-password-not-a-secret"
    user_uuid: str = "MOCK-ONES-USER-001"
    user_name: str = "Mock ONES User"
    token: str = "MOCK-ONES-TOKEN-NOT-A-SECRET"
    team_uuid: str = "MOCK-ONES-TEAM-001"
    team_name: str = "Mock ONES Team"
    project_scope_uuid: str = "MOCK-ONES-PROJECT-SCOPE-001"

    @classmethod
    def from_environment(cls) -> MockOnesSettings:
        return cls(
            email=os.getenv("ONES_MOCK_EMAIL", cls.email),
            password=os.getenv("ONES_MOCK_PASSWORD", cls.password),
            user_uuid=os.getenv("ONES_MOCK_USER_UUID", cls.user_uuid),
            user_name=os.getenv("ONES_MOCK_USER_NAME", cls.user_name),
            token=os.getenv("ONES_MOCK_TOKEN", cls.token),
            team_uuid=os.getenv("ONES_MOCK_TEAM_UUID", cls.team_uuid),
            team_name=os.getenv("ONES_MOCK_TEAM_NAME", cls.team_name),
            project_scope_uuid=os.getenv("ONES_MOCK_PROJECT_SCOPE_UUID", cls.project_scope_uuid),
        )


class LoginRequest(BaseModel):
    email: str
    password: str


class GraphqlRequest(BaseModel):
    query: str = Field(min_length=1)
    variables: dict[str, Any] = Field(default_factory=dict)


MOCK_ISSUE_TYPES = {
    "demand": {
        "uuid": "MOCK-ISSUE-TYPE-DEMAND",
        "scope_uuid": "MOCK-ISSUE-SCOPE-DEMAND",
        "name": "需求",
        "name_pinyin": "xu1qiu2",
        "detail_type": 1,
        "icon": 3,
    },
    "task": {
        "uuid": "MOCK-ISSUE-TYPE-TASK",
        "scope_uuid": "MOCK-ISSUE-SCOPE-TASK",
        "name": "任务",
        "name_pinyin": "ren4wu4",
        "detail_type": 2,
        "icon": 1,
    },
    "defect": {
        "uuid": "MOCK-ISSUE-TYPE-DEFECT",
        "scope_uuid": "MOCK-ISSUE-SCOPE-DEFECT",
        "name": "缺陷",
        "name_pinyin": "que1xian4",
        "detail_type": 3,
        "icon": 2,
    },
}


def _task_fixture(
    *,
    number: int,
    name: str,
    issue_type_key: str,
    owner_uuid: str,
) -> dict[str, Any]:
    issue_type = MOCK_ISSUE_TYPES[issue_type_key]
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
        "name": name,
        "number": number,
        "owner": {
            "avatar": "",
            "key": f"user-{owner_uuid}",
            "name": "Mock Owner",
            "uuid": owner_uuid,
        },
        "parent": {"uuid": ""},
        "path": task_uuid,
        "position": 0,
        "priority": {
            "bgColor": "#e8f5e9",
            "color": "#2e7d32",
            "position": 2,
            "uuid": "MOCK-PRIORITY-NORMAL",
            "value": "普通",
        },
        "project": {
            "key": "project-MOCK-ONES-PROJECT-001",
            "name": "Mock Manufacturing Project",
            "uuid": "MOCK-ONES-PROJECT-001",
        },
        "remainingManhour": 0,
        "serverUpdateStamp": 1784736001000000 + number,
        "status": {
            "category": "to_do",
            "name": "待处理",
            "uuid": "MOCK-STATUS-TODO",
        },
        "subIssueType": None,
        "subTaskCount": 0,
        "subTaskDoneCount": 0,
        "subTasks": [],
        "totalEstimatedHours": 0,
        "totalRemainingHours": 0,
        "uuid": task_uuid,
    }


def _task_fixtures(owner_uuid: str) -> list[dict[str, Any]]:
    return [
        _task_fixture(
            number=900101,
            name="Mock requirement: add production order traceability",
            issue_type_key="demand",
            owner_uuid=owner_uuid,
        ),
        _task_fixture(
            number=900102,
            name="Mock task: verify production order synchronization",
            issue_type_key="task",
            owner_uuid=owner_uuid,
        ),
        _task_fixture(
            number=900103,
            name="Mock defect: order status is not refreshed",
            issue_type_key="defect",
            owner_uuid=owner_uuid,
        ),
    ]


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


def _group_task_data(settings: MockOnesSettings, variables: dict[str, Any]) -> dict[str, Any]:
    issue_types = _issue_type_filter(variables)
    keyword = _search_keyword(variables)
    tasks = [
        task
        for task in _task_fixtures(settings.user_uuid)
        if (not issue_types or str(task["issueType"]["uuid"]) in issue_types)
        and _matches_keyword(task, keyword)
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


def _issue_type_scopes(settings: MockOnesSettings, variables: dict[str, Any]) -> dict[str, Any]:
    requested_scope: str | None = None
    requested_scope_type: int | None = None
    filters = variables.get("filter")
    if isinstance(filters, dict):
        scope = filters.get("scope_equal")
        scope_type = filters.get("scopeType_equal")
        requested_scope = scope if isinstance(scope, str) else None
        requested_scope_type = scope_type if isinstance(scope_type, int) else None

    if requested_scope not in {None, settings.project_scope_uuid} or requested_scope_type not in {
        None,
        1,
    }:
        return {"data": {"issueTypeScopes": []}}

    scopes = []
    for issue_type in MOCK_ISSUE_TYPES.values():
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
                "scope": settings.project_scope_uuid,
                "scopeName": "Mock Manufacturing Project",
                "scopeNamePinyin": "mock-manufacturing-project",
                "scopeType": 1,
                "scopeTypeName": "项目",
                "text": f"{issue_type['name']} 项目 Mock Manufacturing Project",
                "uuid": issue_type["scope_uuid"],
            }
        )
    return {"data": {"issueTypeScopes": scopes}}


def create_app(settings: MockOnesSettings | None = None) -> FastAPI:
    resolved_settings = settings or MockOnesSettings.from_environment()
    app = FastAPI(title="Mock ONES API", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "ones-mock"}

    @app.post("/project/api/project/auth/login")
    async def login(payload: LoginRequest) -> dict[str, Any]:
        if (
            payload.email != resolved_settings.email
            or payload.password != resolved_settings.password
        ):
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_credentials", "message": "invalid email or password"},
            )
        return {
            "user": {
                "uuid": resolved_settings.user_uuid,
                "email": resolved_settings.email,
                "name": resolved_settings.user_name,
                "token": resolved_settings.token,
            },
            "teams": [
                {
                    "uuid": resolved_settings.team_uuid,
                    "name": resolved_settings.team_name,
                }
            ],
        }

    @app.post("/project/api/project/team/{team_uuid}/items/graphql")
    async def graphql(
        team_uuid: str,
        payload: GraphqlRequest,
        query_type: str = Query(alias="t"),
        ones_auth_token: str | None = Header(default=None, alias="Ones-Auth-Token"),
        ones_user_id: str | None = Header(default=None, alias="Ones-User-Id"),
    ) -> dict[str, Any]:
        if (
            ones_auth_token != resolved_settings.token
            or ones_user_id != resolved_settings.user_uuid
        ):
            raise HTTPException(
                status_code=401,
                detail={"code": "unauthorized", "message": "invalid ONES auth headers"},
            )
        if team_uuid != resolved_settings.team_uuid:
            raise HTTPException(
                status_code=404,
                detail={"code": "team_not_found", "message": "mock team does not exist"},
            )
        if query_type == "group-task-data":
            return _group_task_data(resolved_settings, payload.variables)
        if query_type == "issueTypeScopes":
            return _issue_type_scopes(resolved_settings, payload.variables)
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_query_type",
                "message": f"unsupported mock query type: {query_type}",
            },
        )

    return app
