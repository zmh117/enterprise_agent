from __future__ import annotations

import re
from typing import Any, Final

from services.ones_mcp_server.errors import invalid_provider_field
from services.ones_mcp_server.provider.graphql.operations.normalization import (
    bounded_int,
    bounded_string,
    normalized_list,
    require_list,
    require_mapping,
    timestamp_text,
)
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient
from services.ones_mcp_server.provider.rest.operations.common import (
    RestExecution,
    request_headers,
)


_URL = re.compile(r"https?://\S+", re.IGNORECASE)


class ProjectSprintsOperation:
    code = "project_sprints"
    method = "POST"
    path_template = "/project/api/project/team/{team_uuid}/project/{project_uuid}/stamps/data"
    query = {"t": "sprint"}

    def execute(
        self,
        http: OnesProviderHttpClient,
        *,
        team_uuid: str,
        project_uuid: str,
        limit: int,
        token: str,
        user_id: str,
    ) -> RestExecution:
        path = self.path_template.format(team_uuid=team_uuid, project_uuid=project_uuid)
        body = {"sprint": 0}
        response = http.post_json(
            path,
            body,
            headers=request_headers(http, token=token, user_id=user_id),
            query=self.query,
        )
        return RestExecution(
            request={
                "operation": self.code,
                "method": self.method,
                "project_uuid": project_uuid,
                "limit": limit,
            },
            response=response,
            output=self.parse_response(
                response,
                project_uuid=project_uuid,
                limit=limit,
            ),
        )

    @staticmethod
    def parse_response(
        payload: dict[str, Any],
        *,
        project_uuid: str,
        limit: int,
    ) -> dict[str, Any]:
        wrapper = require_mapping(payload.get("sprint"), path="sprint")
        raw_items = require_list(wrapper.get("sprints"), path="sprint.sprints")
        sprints: list[dict[str, Any]] = []
        for index, item in enumerate(raw_items[:limit]):
            path = f"sprint.sprints[{index}]"
            raw = require_mapping(item, path=path)
            current_status = None
            statuses = raw.get("statuses") or []
            require_list(statuses, path=f"{path}.statuses")
            for status in statuses:
                if isinstance(status, dict) and status.get("is_current_status") is True:
                    current_status = status
                    break
            status_text = (
                bounded_string(
                    current_status.get("category"), maximum=64, path=f"{path}.statuses.category"
                )
                if isinstance(current_status, dict)
                else str(raw.get("status") or "unknown")[:64]
            )
            response_project_uuid = raw.get("project_uuid")
            if (
                response_project_uuid is not None
                and bounded_string(response_project_uuid, maximum=128, path=f"{path}.project_uuid")
                != project_uuid
            ):
                raise invalid_provider_field(
                    f"{path}.project_uuid", "与请求项目一致的标识", response_project_uuid
                )
            sprint: dict[str, Any] = {
                "uuid": bounded_string(raw.get("uuid"), maximum=128, path=f"{path}.uuid"),
                "name": bounded_string(raw.get("title"), maximum=300, path=f"{path}.title"),
                "project_uuid": project_uuid,
                "status": status_text,
            }
            if isinstance(raw.get("project_name"), str):
                sprint["project_name"] = str(raw["project_name"])[:300]
            for source, target in (("start_time", "start_at"), ("end_time", "end_at")):
                if raw.get(source) is not None:
                    sprint[target] = timestamp_text(
                        raw.get(source), unit="seconds", path=f"{path}.{source}"
                    )
            if raw.get("progress") is not None:
                progress = bounded_int(raw.get("progress"), path=f"{path}.progress")
                if progress > 10_000_000:
                    raise invalid_provider_field(
                        f"{path}.progress", "0至10000000的定点进度整数", progress
                    )
                sprint["progress"] = progress / 100_000
            sprints.append(sprint)
        return normalized_list(
            "sprints",
            sprints,
            total=len(raw_items),
            truncated=len(raw_items) > limit,
        )


class WorkItemMessagesOperation:
    code = "work_item_messages"
    method = "GET"
    path_template = "/project/api/project/team/{team_uuid}/task/{work_item_uuid}/messages"

    def execute(
        self,
        http: OnesProviderHttpClient,
        *,
        team_uuid: str,
        work_item_uuid: str,
        limit: int,
        token: str,
        user_id: str,
    ) -> RestExecution:
        path = self.path_template.format(
            team_uuid=team_uuid,
            work_item_uuid=work_item_uuid,
        )
        response = http.get_json(
            path,
            None,
            headers=request_headers(http, token=token, user_id=user_id),
        )
        return RestExecution(
            request={
                "operation": self.code,
                "method": self.method,
                "work_item_uuid": work_item_uuid,
                "limit": limit,
            },
            response=response,
            output=self.parse_response(response, limit=limit),
        )

    @staticmethod
    def parse_response(payload: dict[str, Any], *, limit: int) -> dict[str, Any]:
        raw_messages = require_list(payload.get("messages"), path="messages")
        messages: list[dict[str, Any]] = []
        for index, value in enumerate(raw_messages[:limit]):
            path = f"messages[{index}]"
            raw = require_mapping(value, path=path)
            text = bounded_string(
                raw.get("text", ""), maximum=10000, allow_empty=True, path=f"{path}.text"
            )
            messages.append(
                {
                    "uuid": bounded_string(raw.get("uuid"), maximum=128, path=f"{path}.uuid"),
                    "type": bounded_string(raw.get("type"), maximum=80, path=f"{path}.type"),
                    "sent_at": timestamp_text(
                        raw.get("send_time"), unit="microseconds", path=f"{path}.send_time"
                    ),
                    "text": _URL.sub("[link omitted]", text)[:2000],
                }
            )
        total_value = payload.get("count", len(raw_messages))
        total = bounded_int(total_value, path="count")
        has_next = payload.get("has_next", False)
        if type(has_next) is not bool:
            raise invalid_provider_field("has_next", "布尔值", has_next)
        return normalized_list(
            "messages",
            messages,
            total=total,
            truncated=has_next or total > len(messages) or len(raw_messages) > limit,
        )


class TeamUserSearchOperation:
    code = "team_user_search"
    method = "POST"
    path_template = "/project/api/project/team/{team_uuid}/users/search"

    def execute(
        self,
        http: OnesProviderHttpClient,
        *,
        team_uuid: str,
        keyword: str,
        project_uuid: str,
        limit: int,
        token: str,
        user_id: str,
    ) -> RestExecution:
        path = self.path_template.format(team_uuid=team_uuid)
        body: dict[str, Any] = {
            "keyword": keyword,
            "status": [1],
            "team_member_status": [1, 4],
            "need_user_list_filter": True,
            "types": [1, 10],
        }
        if project_uuid:
            body["project_uuid"] = project_uuid
        response = http.post_json(
            path,
            body,
            headers=request_headers(http, token=token, user_id=user_id),
        )
        return RestExecution(
            request={
                "operation": self.code,
                "method": self.method,
                "keyword": keyword,
                "project_uuid": project_uuid,
                "limit": limit,
            },
            response=response,
            output=self.parse_response(response, limit=limit),
        )

    @staticmethod
    def parse_response(payload: dict[str, Any], *, limit: int) -> dict[str, Any]:
        raw_users = require_list(payload.get("users"), path="users")
        users: list[dict[str, str]] = []
        seen: set[str] = set()
        for index, value in enumerate(raw_users):
            path = f"users[{index}]"
            raw = require_mapping(value, path=path)
            uuid = bounded_string(raw.get("uuid"), maximum=128, path=f"{path}.uuid")
            if uuid in seen:
                continue
            seen.add(uuid)
            if len(users) < limit:
                users.append(
                    {
                        "uuid": uuid,
                        "name": bounded_string(raw.get("name"), maximum=200, path=f"{path}.name"),
                    }
                )
        return normalized_list(
            "users",
            users,
            total=len(seen),
            truncated=len(seen) > limit,
        )


PROJECT_SPRINTS_OPERATION: Final = ProjectSprintsOperation()
WORK_ITEM_MESSAGES_OPERATION: Final = WorkItemMessagesOperation()
TEAM_USER_SEARCH_OPERATION: Final = TeamUserSearchOperation()
