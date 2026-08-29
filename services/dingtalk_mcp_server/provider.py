from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.modules.dingding.infrastructure.dingtalk_delivery_clients import DingTalkAccessTokenClient
from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError


CARD_TEMPLATE_ID = "0ad7c643-7e30-4797-8284-da5ef89d3841.schema"
OPEN_API_BASE = "https://api.dingtalk.com"


class DingTalkJsonTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]: ...


class UrllibDingTalkJsonTransport:
    def request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        assert_external_io_allowed("dingtalk.governed_action_http")
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"content-type": "application/json", **headers},
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(256 * 1024 + 1)
        except HTTPError as exc:
            status = int(getattr(exc, "code", 0) or 0)
            error = NonRetryableExecutionError if 400 <= status < 500 else RetryableExecutionError
            raise error(
                f"DingTalk governed request failed status={status}",
                safe_message="钉钉开放接口请求失败",
                error_code=f"dingtalk_http_{status or 'unknown'}",
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise RetryableExecutionError(
                "DingTalk governed request transport failed",
                safe_message="钉钉开放接口暂时不可用",
                error_code="dingtalk_transport_failed",
            ) from exc
        if len(body) > 256 * 1024:
            raise RetryableExecutionError(
                "DingTalk response exceeded limit",
                safe_message="钉钉开放接口响应超限",
                error_code="dingtalk_response_too_large",
            )
        if not body:
            return {}
        try:
            value = json.loads(body.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RetryableExecutionError(
                "DingTalk response was not JSON",
                safe_message="钉钉开放接口响应无效",
                error_code="dingtalk_response_invalid",
            ) from exc
        if not isinstance(value, dict):
            raise RetryableExecutionError(
                "DingTalk response was not an object",
                safe_message="钉钉开放接口响应无效",
                error_code="dingtalk_response_invalid",
            )
        code = value.get("errcode", value.get("code", 0))
        if str(code) not in {"0", "", "None"}:
            raise NonRetryableExecutionError(
                f"DingTalk provider rejected request code={str(code)[:64]}",
                safe_message="钉钉开放接口拒绝了该操作",
                error_code="dingtalk_provider_rejected",
            )
        return value


class DingTalkCardClient:
    def __init__(
        self,
        token_client: DingTalkAccessTokenClient,
        *,
        transport: DingTalkJsonTransport | None = None,
        timeout_seconds: int = 5,
    ) -> None:
        self.token_client = token_client
        self.transport = transport or UrllibDingTalkJsonTransport()
        self.timeout_seconds = timeout_seconds

    def create_confirmation(
        self,
        *,
        out_track_id: str,
        staff_id: str,
        card_fields: dict[str, Any],
        private_fields: dict[str, Any],
    ) -> None:
        self._request(
            "POST",
            "/v1.0/card/instances/createAndDeliver",
            {
                "cardTemplateId": CARD_TEMPLATE_ID,
                "outTrackId": out_track_id,
                "userId": staff_id,
                "cardData": {"cardParamMap": card_fields},
                "privateData": {
                    staff_id: {"cardParamMap": private_fields},
                },
                "callbackType": "STREAM",
                "imRobotOpenSpaceModel": {"supportForward": False},
                "openSpaceId": f"dtv1.card//IM_ROBOT.{staff_id}",
                "imRobotOpenDeliverModel": {"spaceType": "IM_ROBOT"},
                "userIdType": 1,
            },
        )

    def update(self, *, out_track_id: str, card_fields: dict[str, Any]) -> None:
        self._request(
            "PUT",
            "/v1.0/card/instances",
            {
                "outTrackId": out_track_id,
                "cardData": {"cardParamMap": card_fields},
                "cardUpdateOptions": {
                    "updateCardDataByKey": True,
                    "updatePrivateDataByKey": False,
                },
            },
        )

    def _request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.transport.request_json(
            method,
            f"{OPEN_API_BASE}{path}",
            payload,
            {"x-acs-dingtalk-access-token": self.token_client.access_token()},
            self.timeout_seconds,
        )


class DingTalkTodoClient:
    def __init__(
        self,
        token_client: DingTalkAccessTokenClient,
        *,
        transport: DingTalkJsonTransport | None = None,
        timeout_seconds: int = 5,
    ) -> None:
        self.token_client = token_client
        self.transport = transport or UrllibDingTalkJsonTransport()
        self.timeout_seconds = timeout_seconds

    def create_for_self(self, *, union_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "subject": arguments["subject"],
            "description": arguments.get("description", ""),
            "executorIds": [union_id],
            "participantIds": [union_id],
        }
        if arguments.get("due_time_ms") is not None:
            payload["dueTime"] = int(arguments["due_time_ms"])
        response = self.transport.request_json(
            "POST",
            f"{OPEN_API_BASE}/v1.0/todo/users/{quote(union_id, safe='')}/tasks",
            payload,
            {"x-acs-dingtalk-access-token": self.token_client.access_token()},
            self.timeout_seconds,
        )
        task_id = str(response.get("id") or response.get("taskId") or "")
        return {"task_id": task_id, "created": True}
