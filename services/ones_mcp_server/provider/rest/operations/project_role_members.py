from __future__ import annotations

from typing import Any

from services.ones_mcp_server.contracts import PROJECT_ROLE_MEMBER_LIMITS
from services.ones_mcp_server.errors import invalid_provider_response
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient
from services.ones_mcp_server.provider.rest.operations.common import (
    RestExecution,
    request_headers,
)


def _bounded_string(value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise invalid_provider_response("ones_provider_schema_invalid")
    return value


class ProjectRoleMembersOperation:
    code = "project_role_members"
    method = "GET"
    path_template = "/project/api/project/team/{team_uuid}/project/{project_uuid}/role_members"

    def execute(
        self,
        http: OnesProviderHttpClient,
        *,
        team_uuid: str,
        project_uuid: str,
        token: str,
        user_id: str,
    ) -> RestExecution:
        path = self.path_template.format(
            team_uuid=team_uuid,
            project_uuid=project_uuid,
        )
        body: dict[str, Any] = {}
        response = http.get_json(
            path,
            body,
            headers=request_headers(http, token=token, user_id=user_id),
        )
        return RestExecution(
            request={"operation": self.code, "method": self.method, "path": path, "body": body},
            response=response,
            output=self.parse_response(response),
        )

    @staticmethod
    def parse_response(payload: dict[str, Any]) -> list[dict[str, Any]]:
        role_members = payload.get("role_members") if isinstance(payload, dict) else None
        if not isinstance(role_members, list) or len(role_members) > PROJECT_ROLE_MEMBER_LIMITS[
            "roles"
        ]:
            raise invalid_provider_response("ones_provider_schema_invalid")
        normalized: list[dict[str, Any]] = []
        seen_roles: set[str] = set()
        unique_members: set[str] = set()
        for item in role_members:
            if not isinstance(item, dict):
                raise invalid_provider_response("ones_provider_schema_invalid")
            role = item.get("role")
            members = item.get("members")
            if (
                not isinstance(role, dict)
                or not isinstance(members, list)
                or len(members) > PROJECT_ROLE_MEMBER_LIMITS["members_per_role"]
            ):
                raise invalid_provider_response("ones_provider_schema_invalid")
            role_uuid = _bounded_string(
                role.get("uuid"),
                maximum=PROJECT_ROLE_MEMBER_LIMITS["role_uuid"],
            )
            role_name = _bounded_string(
                role.get("name"),
                maximum=PROJECT_ROLE_MEMBER_LIMITS["role_name"],
            )
            if role_uuid in seen_roles:
                raise invalid_provider_response("ones_provider_schema_invalid")
            seen_roles.add(role_uuid)
            normalized_members: list[str] = []
            seen_in_role: set[str] = set()
            for value in members:
                member_uuid = _bounded_string(
                    value,
                    maximum=PROJECT_ROLE_MEMBER_LIMITS["member_uuid"],
                )
                if member_uuid in seen_in_role:
                    raise invalid_provider_response("ones_provider_schema_invalid")
                seen_in_role.add(member_uuid)
                unique_members.add(member_uuid)
                normalized_members.append(member_uuid)
            if len(unique_members) > PROJECT_ROLE_MEMBER_LIMITS["unique_members"]:
                raise invalid_provider_response("ones_provider_schema_invalid")
            normalized.append(
                {
                    "role_uuid": role_uuid,
                    "role_name": role_name,
                    "member_uuids": normalized_members,
                }
            )
        return normalized


class TeamUsersOperation:
    code = "team_users"
    method = "POST"
    path_template = "/project/api/project/team/{team_uuid}/users"

    def execute(
        self,
        http: OnesProviderHttpClient,
        *,
        team_uuid: str,
        member_uuids: list[str],
        token: str,
        user_id: str,
    ) -> RestExecution:
        if (
            not member_uuids
            or len(member_uuids) > PROJECT_ROLE_MEMBER_LIMITS["unique_members"]
            or len(set(member_uuids)) != len(member_uuids)
        ):
            raise ValueError("ONES Team users request UUIDs are invalid")
        path = self.path_template.format(team_uuid=team_uuid)
        body = {"uuids": list(member_uuids)}
        response = http.post_json(
            path,
            body,
            headers=request_headers(http, token=token, user_id=user_id),
        )
        return RestExecution(
            request={"operation": self.code, "method": self.method, "path": path, "body": body},
            response=response,
            output=self.parse_response(response),
        )

    @staticmethod
    def parse_response(payload: dict[str, Any]) -> dict[str, str]:
        users = payload.get("users") if isinstance(payload, dict) else None
        if not isinstance(users, list) or len(users) > PROJECT_ROLE_MEMBER_LIMITS[
            "unique_members"
        ]:
            raise invalid_provider_response("ones_provider_schema_invalid")
        normalized: dict[str, str] = {}
        for user in users:
            if not isinstance(user, dict):
                raise invalid_provider_response("ones_provider_schema_invalid")
            user_uuid = _bounded_string(
                user.get("uuid"),
                maximum=PROJECT_ROLE_MEMBER_LIMITS["member_uuid"],
            )
            name = _bounded_string(
                user.get("name"),
                maximum=PROJECT_ROLE_MEMBER_LIMITS["member_name"],
            )
            if user_uuid in normalized:
                raise invalid_provider_response("ones_provider_schema_invalid")
            normalized[user_uuid] = name
        return normalized


PROJECT_ROLE_MEMBERS_OPERATION = ProjectRoleMembersOperation()
TEAM_USERS_OPERATION = TeamUsersOperation()
