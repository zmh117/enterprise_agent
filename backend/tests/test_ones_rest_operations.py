from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.shared.exceptions import AppError
from services.ones_mcp_server.provider.rest.operations.project_role_members import (
    PROJECT_ROLE_MEMBERS_OPERATION,
    TEAM_USERS_OPERATION,
)


class _RecordingHttp:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.target = SimpleNamespace(base_url="http://ones-mock:8001")
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        self.calls.append(
            {"method": "GET", "path": path, "payload": payload, "headers": headers}
        )
        return self.responses.pop(0)

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        self.calls.append(
            {"method": "POST", "path": path, "payload": payload, "headers": headers}
        )
        return self.responses.pop(0)


def test_explicit_rest_operations_use_the_supplied_contract_and_drop_extra_fields() -> None:
    http = _RecordingHttp(
        [
            {
                "role_members": [
                    {
                        "role": {
                            "uuid": "ROLE-1",
                            "name": "Project Members",
                            "built_in": True,
                        },
                        "members": ["USER-1", "USER-2"],
                    }
                ]
            },
            {
                "users": [
                    {
                        "uuid": "USER-1",
                        "name": "Synthetic User One",
                        "email": "discarded@example.test",
                        "phone": "discarded",
                    },
                    {"uuid": "USER-2", "name": "Synthetic User Two", "avatar": "discarded"},
                ]
            },
        ]
    )

    roles = PROJECT_ROLE_MEMBERS_OPERATION.execute(
        http,  # type: ignore[arg-type]
        team_uuid="TEAM-1",
        project_uuid="PROJECT-1",
        token="synthetic-token",
        user_id="USER-1",
    )
    users = TEAM_USERS_OPERATION.execute(
        http,  # type: ignore[arg-type]
        team_uuid="TEAM-1",
        member_uuids=["USER-1", "USER-2"],
        token="synthetic-token",
        user_id="USER-1",
    )

    assert roles.output == [
        {
            "role_uuid": "ROLE-1",
            "role_name": "Project Members",
            "member_uuids": ["USER-1", "USER-2"],
        }
    ]
    assert users.output == {
        "USER-1": "Synthetic User One",
        "USER-2": "Synthetic User Two",
    }
    assert http.calls[0] == {
        "method": "GET",
        "path": "/project/api/project/team/TEAM-1/project/PROJECT-1/role_members",
        "payload": {},
        "headers": {
            "Ones-Auth-Token": "synthetic-token",
            "Ones-User-Id": "USER-1",
            "Referer": "http://ones-mock:8001",
            "cache-control": "no-cache",
        },
    }
    assert http.calls[1]["method"] == "POST"
    assert http.calls[1]["path"] == "/project/api/project/team/TEAM-1/users"
    assert http.calls[1]["payload"] == {"uuids": ["USER-1", "USER-2"]}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"role_members": "invalid"},
        {"role_members": [{}]},
        {"role_members": [{"role": {"uuid": "R", "name": "N"}, "members": "U"}]},
        {
            "role_members": [
                {"role": {"uuid": "R", "name": "N"}, "members": ["U", "U"]}
            ]
        },
    ],
)
def test_project_role_members_parser_rejects_contract_drift(payload: dict[str, Any]) -> None:
    with pytest.raises(AppError) as raised:
        PROJECT_ROLE_MEMBERS_OPERATION.parse_response(payload)
    assert raised.value.error_code == "ones_provider_schema_invalid"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"users": "invalid"},
        {"users": [{}]},
        {"users": [{"uuid": "U", "name": "N"}, {"uuid": "U", "name": "N2"}]},
    ],
)
def test_team_users_parser_rejects_contract_drift(payload: dict[str, Any]) -> None:
    with pytest.raises(AppError) as raised:
        TEAM_USERS_OPERATION.parse_response(payload)
    assert raised.value.error_code == "ones_provider_schema_invalid"
