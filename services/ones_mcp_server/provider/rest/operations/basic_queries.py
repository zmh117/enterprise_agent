from __future__ import annotations

import re
from typing import Any, Final

from services.ones_mcp_server.errors import invalid_provider_response
from services.ones_mcp_server.provider.graphql.operations.normalization import (
    bounded_int,
    bounded_string,
    normalized_list,
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
        wrapper = payload.get("sprint")
        if not isinstance(wrapper, dict) or not isinstance(wrapper.get("sprints"), list):
            raise invalid_provider_response("ones_provider_schema_invalid")
        raw_items = wrapper["sprints"]
        sprints: list[dict[str, Any]] = []
        for raw in raw_items[:limit]:
            if not isinstance(raw, dict):
                raise invalid_provider_response("ones_provider_schema_invalid")
            current_status = None
            statuses = raw.get("statuses") or []
            if not isinstance(statuses, list):
                raise invalid_provider_response("ones_provider_schema_invalid")
            for status in statuses:
                if isinstance(status, dict) and status.get("is_current_status") is True:
                    current_status = status
                    break
            status_text = (
                bounded_string(current_status.get("category"), maximum=64)
                if isinstance(current_status, dict)
                else str(raw.get("status") or "unknown")[:64]
            )
            response_project_uuid = raw.get("project_uuid")
            if response_project_uuid is not None and bounded_string(
                response_project_uuid, maximum=128
            ) != project_uuid:
                raise invalid_provider_response("ones_provider_schema_invalid")
            sprint: dict[str, Any] = {
                "uuid": bounded_string(raw.get("uuid"), maximum=128),
                "name": bounded_string(raw.get("title"), maximum=300),
                "project_uuid": project_uuid,
                "status": status_text,
            }
            if isinstance(raw.get("project_name"), str):
                sprint["project_name"] = str(raw["project_name"])[:300]
            for source, target in (("start_time", "start_at"), ("end_time", "end_at")):
                if raw.get(source) is not None:
                    sprint[target] = timestamp_text(raw.get(source))
            if raw.get("progress") is not None:
                progress = bounded_int(raw.get("progress"))
                if progress > 100:
                    raise invalid_provider_response("ones_provider_schema_invalid")
                sprint["progress"] = progress
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
        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list):
            raise invalid_provider_response("ones_provider_schema_invalid")
        messages: list[dict[str, Any]] = []
        for raw in raw_messages[:limit]:
            if not isinstance(raw, dict):
                raise invalid_provider_response("ones_provider_schema_invalid")
            text = bounded_string(
                raw.get("text", ""), maximum=10000, allow_empty=True
            )
            messages.append(
                {
                    "uuid": bounded_string(raw.get("uuid"), maximum=128),
                    "type": bounded_string(raw.get("type"), maximum=80),
                    "sent_at": timestamp_text(raw.get("send_time")),
                    "text": _URL.sub("[link omitted]", text)[:2000],
                }
            )
        total_value = payload.get("count", len(raw_messages))
        total = bounded_int(total_value)
        has_next = payload.get("has_next", False)
        if type(has_next) is not bool:
            raise invalid_provider_response("ones_provider_schema_invalid")
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
        raw_users = payload.get("users")
        if not isinstance(raw_users, list):
            raise invalid_provider_response("ones_provider_schema_invalid")
        users: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw in raw_users:
            if not isinstance(raw, dict):
                raise invalid_provider_response("ones_provider_schema_invalid")
            uuid = bounded_string(raw.get("uuid"), maximum=128)
            if uuid in seen:
                continue
            seen.add(uuid)
            if len(users) < limit:
                users.append(
                    {
                        "uuid": uuid,
                        "name": bounded_string(raw.get("name"), maximum=200),
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
