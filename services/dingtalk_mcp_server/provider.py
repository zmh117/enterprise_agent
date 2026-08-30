from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from app.modules.dingding.infrastructure.dingtalk_delivery_clients import DingTalkAccessTokenClient
from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError


CARD_TEMPLATE_ID = "0ad7c643-7e30-4797-8284-da5ef89d3841.schema"
OPEN_API_BASE = "https://api.dingtalk.com"
LEGACY_API_BASE = "https://oapi.dingtalk.com"


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
            data=(
                None
                if method.upper() == "GET"
                else json.dumps(payload, ensure_ascii=False).encode()
            ),
            headers={"content-type": "application/json", **headers},
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(256 * 1024 + 1)
        except HTTPError as exc:
            status = int(getattr(exc, "code", 0) or 0)
            if status in {401, 403}:
                raise NonRetryableExecutionError(
                    f"DingTalk governed request permission denied status={status}",
                    safe_message="钉钉应用缺少此能力所需权限或可见范围",
                    error_code="dingtalk_permission_denied",
                ) from exc
            if status == 429:
                raise RetryableExecutionError(
                    "DingTalk governed request was rate limited",
                    safe_message="钉钉开放接口请求过于频繁",
                    error_code="dingtalk_rate_limited",
                ) from exc
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

    def update_for_self(self, *, union_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        task_id = str(arguments["task_id"])
        payload: dict[str, Any] = {
            "subject": arguments["subject"],
            "description": arguments.get("description", ""),
        }
        if arguments.get("due_time_ms") is not None:
            payload["dueTime"] = int(arguments["due_time_ms"])
        self.transport.request_json(
            "PUT",
            (
                f"{OPEN_API_BASE}/v1.0/todo/users/{quote(union_id, safe='')}/"
                f"tasks/{quote(task_id, safe='')}"
            ),
            payload,
            {"x-acs-dingtalk-access-token": self.token_client.access_token()},
            self.timeout_seconds,
        )
        return {"task_id": task_id, "updated": True}

    def complete_for_self(
        self,
        *,
        union_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = str(arguments["task_id"])
        self.transport.request_json(
            "PUT",
            (
                f"{OPEN_API_BASE}/v1.0/todo/users/{quote(union_id, safe='')}/"
                f"tasks/{quote(task_id, safe='')}"
            ),
            {"subject": arguments["subject"], "done": True},
            {"x-acs-dingtalk-access-token": self.token_client.access_token()},
            self.timeout_seconds,
        )
        return {"task_id": task_id, "completed": True}


class _FixedDingTalkClient:
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

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        legacy: bool = False,
    ) -> dict[str, Any]:
        base = LEGACY_API_BASE if legacy else OPEN_API_BASE
        url = f"{base}{path}"
        clean_query = {
            str(key): str(value)
            for key, value in (query or {}).items()
            if value is not None and str(value) != ""
        }
        access_token = self.token_client.access_token()
        if legacy:
            # DingTalk's legacy oapi endpoints authenticate with the app access
            # token in the query string. The newer api.dingtalk.com endpoints
            # use the x-acs-dingtalk-access-token header instead.
            clean_query["access_token"] = access_token
        if clean_query:
            url = f"{url}?{urlencode(clean_query)}"
        return self.transport.request_json(
            method,
            url,
            payload or {},
            {} if legacy else {"x-acs-dingtalk-access-token": access_token},
            self.timeout_seconds,
        )


class DingTalkContactsClient(_FixedDingTalkClient):
    def search_users(
        self,
        *,
        query: str,
        offset: int,
        page_size: int,
        exact_match: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "queryWord": query,
            "offset": offset,
            "size": page_size,
        }
        if exact_match:
            payload["fullMatchField"] = 1
        response = self._request(
            "POST",
            "/v1.0/contact/users/search",
            payload=payload,
        )
        rows = _provider_items(response, "list", "users", "items")
        return _page(
            "users",
            [_project_search_user(row) for row in rows],
            response,
            page_size,
            offset=offset,
        )

    def get_user(self, *, user_id: str, language: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/topapi/v2/user/get",
            payload={"userid": user_id, "language": language},
            legacy=True,
        )
        return {"user": _project_user(_provider_object(response)), "untrusted_data": True}

    def list_department_users(self, *, department_id: int) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/topapi/user/listid",
            payload={"dept_id": department_id},
            legacy=True,
        )
        rows = _provider_items(response, "userid_list", "userIds", "list")[:50]
        users = [_project_user(row if isinstance(row, dict) else {"userid": row}) for row in rows]
        return _page("users", users, response, 50)


class DingTalkDepartmentClient(_FixedDingTalkClient):
    def search(
        self,
        *,
        query: str,
        offset: int,
        page_size: int,
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/v1.0/contact/departments/search",
            payload={"queryWord": query, "offset": offset, "size": page_size},
        )
        rows = _provider_items(response, "list", "departments", "items")[:page_size]
        return _page(
            "departments",
            [_project_department(row) for row in rows],
            response,
            page_size,
        )

    def get(self, *, department_id: int, language: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/topapi/v2/department/get",
            payload={"dept_id": department_id, "language": language},
            legacy=True,
        )
        return {
            "department": _project_department(_provider_object(response)),
            "untrusted_data": True,
        }

    def list_sub_departments(
        self,
        *,
        parent_department_id: int,
        language: str,
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/topapi/v2/department/listsub",
            payload={"dept_id": parent_department_id, "language": language},
            legacy=True,
        )
        rows = _provider_items(response, "list", "departments", "items")[:50]
        return _page(
            "departments",
            [_project_department(row) for row in rows],
            response,
            50,
        )


class DingTalkTodoReadClient(_FixedDingTalkClient):
    def list_for_self(
        self,
        *,
        union_id: str,
        cursor: str,
        is_done: bool | None,
        role_types: list[str],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"nextToken": cursor or "0"}
        if is_done is not None:
            payload["isDone"] = is_done
        if role_types:
            payload["roleTypes"] = [[role] for role in role_types]
        response = self._request(
            "POST",
            f"/v1.0/todo/users/{quote(union_id, safe='')}/org/tasks/query",
            payload=payload,
        )
        rows = _provider_items(response, "todoCards", "tasks", "items", "list")[:50]
        return _page("todos", [_project_todo(row) for row in rows], response, 50)


class DingTalkCalendarReadClient(_FixedDingTalkClient):
    def get_event(
        self,
        *,
        union_id: str,
        event_id: str,
        max_attendees: int,
    ) -> dict[str, Any]:
        response = self._request(
            "GET",
            (
                f"/v1.0/calendar/users/{quote(union_id, safe='')}/calendars/primary/"
                f"events/{quote(event_id, safe='')}"
            ),
            query={"maxAttendees": max_attendees},
        )
        return {"event": _project_event(_provider_object(response)), "untrusted_data": True}

    def list_events(
        self,
        *,
        union_id: str,
        time_min: str,
        time_max: str,
        page_size: int,
        cursor: str,
        max_attendees: int,
    ) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"/v1.0/calendar/users/{quote(union_id, safe='')}/calendars/primary/eventsview",
            query={
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": page_size,
                "nextToken": cursor,
                "maxAttendees": max_attendees,
            },
        )
        rows = _provider_items(response, "events", "items", "list")[:page_size]
        return _page("events", [_project_event(row) for row in rows], response, page_size)

    def list_attendees(
        self,
        *,
        union_id: str,
        event_id: str,
        page_size: int,
        cursor: str,
    ) -> dict[str, Any]:
        response = self._request(
            "GET",
            (
                f"/v1.0/calendar/users/{quote(union_id, safe='')}/calendars/primary/"
                f"events/{quote(event_id, safe='')}/attendees"
            ),
            query={"maxResults": page_size, "nextToken": cursor},
        )
        rows = _provider_items(response, "attendees", "items", "list")[:page_size]
        return _page(
            "attendees",
            [_project_attendee(row) for row in rows],
            response,
            page_size,
        )


class DingTalkAiTableReadClient(_FixedDingTalkClient):
    def search(
        self,
        *,
        operator_id: str,
        query: str,
        page_size: int,
        cursor: str,
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/v2.0/storage/dentries/search",
            query={"operatorId": operator_id},
            payload={
                "keyword": query,
                "option": {
                    "dentryCategories": ["alidoc"],
                    "creatorIds": [],
                    "nextToken": cursor,
                    "maxResults": page_size,
                },
            },
        )
        rows = _provider_items(response, "dentries", "items", "list")[:page_size]
        return _page("aitables", [_project_aitable(row) for row in rows], response, page_size)

    def list_sheets(self, *, operator_id: str, base_id: str) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"/v1.0/notable/bases/{quote(base_id, safe='')}/sheets",
            query={"operatorId": operator_id},
        )
        rows = _provider_items(response, "sheets", "items", "list")[:50]
        return _page("sheets", [_project_sheet(row) for row in rows], response, 50)

    def get_sheet(
        self,
        *,
        operator_id: str,
        base_id: str,
        sheet_id: str,
    ) -> dict[str, Any]:
        response = self._request(
            "GET",
            (f"/v1.0/notable/bases/{quote(base_id, safe='')}/sheets/{quote(sheet_id, safe='')}"),
            query={"operatorId": operator_id},
        )
        return {"sheet": _project_sheet(_provider_object(response)), "untrusted_data": True}

    def list_fields(
        self,
        *,
        operator_id: str,
        base_id: str,
        sheet_id: str,
    ) -> dict[str, Any]:
        response = self._request(
            "GET",
            (
                f"/v1.0/notable/bases/{quote(base_id, safe='')}/"
                f"sheets/{quote(sheet_id, safe='')}/fields"
            ),
            query={"operatorId": operator_id},
        )
        rows = _provider_items(response, "fields", "items", "list")[:50]
        return _page("fields", [_project_field(row) for row in rows], response, 50)

    def list_records(
        self,
        *,
        operator_id: str,
        base_id: str,
        sheet_id: str,
        page_size: int,
        cursor: str,
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            (
                f"/v1.0/notable/bases/{quote(base_id, safe='')}/"
                f"sheets/{quote(sheet_id, safe='')}/records/list"
            ),
            query={"operatorId": operator_id},
            payload={"maxResults": page_size, "nextToken": cursor},
        )
        rows = _provider_items(response, "records", "items", "list")[:page_size]
        return _page("records", [_project_record(row) for row in rows], response, page_size)

    def get_record(
        self,
        *,
        operator_id: str,
        base_id: str,
        sheet_id: str,
        record_id: str,
    ) -> dict[str, Any]:
        response = self._request(
            "GET",
            (
                f"/v1.0/notable/bases/{quote(base_id, safe='')}/"
                f"sheets/{quote(sheet_id, safe='')}/records/{quote(record_id, safe='')}"
            ),
            query={"operatorId": operator_id},
        )
        return {"record": _project_record(_provider_object(response)), "untrusted_data": True}


class DingTalkWorkNotificationReadClient(_FixedDingTalkClient):
    def get_progress(self, *, agent_id: int, task_id: int) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/topapi/message/corpconversation/getsendprogress",
            payload={"agent_id": agent_id, "task_id": task_id},
            legacy=True,
        )
        return {
            "progress": _project_notice_progress(_provider_object(response), task_id),
            "untrusted_data": True,
        }

    def get_result(self, *, agent_id: int, task_id: int) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/topapi/message/corpconversation/getsendresult",
            payload={"agent_id": agent_id, "task_id": task_id},
            legacy=True,
        )
        return {
            "result": _project_notice_result(_provider_object(response), task_id),
            "untrusted_data": True,
        }


class DingTalkCalendarMutationClient(_FixedDingTalkClient):
    def create_for_self(
        self,
        *,
        union_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"/v1.0/calendar/users/{quote(union_id, safe='')}/calendars/primary/events",
            payload=_calendar_payload(arguments),
        )
        event = _provider_object(response)
        return {
            "event_id": _text(event.get("id") or event.get("eventId"), 512),
            "created": True,
        }

    def update_for_self(
        self,
        *,
        union_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        event_id = str(arguments["event_id"])
        payload = {"id": event_id, **_calendar_payload(arguments)}
        self._request(
            "PUT",
            (
                f"/v1.0/calendar/users/{quote(union_id, safe='')}/calendars/primary/"
                f"events/{quote(event_id, safe='')}"
            ),
            payload=payload,
        )
        return {"event_id": event_id, "updated": True}


class DingTalkAiTableMutationClient(_FixedDingTalkClient):
    def insert_records(
        self,
        *,
        operator_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            (
                f"/v1.0/notable/bases/{quote(str(arguments['base_id']), safe='')}/"
                f"sheets/{quote(str(arguments['sheet_id']), safe='')}/records"
            ),
            query={"operatorId": operator_id},
            payload={"records": arguments["records"]},
        )
        rows = _provider_items(response, "records", "items", "list")[:20]
        return {
            "record_ids": [
                _text(row.get("id") or row.get("recordId"), 512)
                for row in rows
                if isinstance(row, dict) and (row.get("id") or row.get("recordId"))
            ],
            "inserted_count": len(arguments["records"]),
        }

    def update_records(
        self,
        *,
        operator_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        records = [
            {"id": str(row["record_id"]), "fields": row["fields"]} for row in arguments["records"]
        ]
        self._request(
            "PUT",
            (
                f"/v1.0/notable/bases/{quote(str(arguments['base_id']), safe='')}/"
                f"sheets/{quote(str(arguments['sheet_id']), safe='')}/records"
            ),
            query={"operatorId": operator_id},
            payload={"records": records},
        )
        return {
            "record_ids": [str(row["record_id"]) for row in arguments["records"]],
            "updated_count": len(records),
        }


class DingTalkRobotMutationClient(_FixedDingTalkClient):
    def batch_send_to_users(self, *, arguments: dict[str, Any]) -> dict[str, Any]:
        target = arguments.get("_target")
        user_ids = arguments.get("user_ids")
        msg_param = arguments.get("msg_param")
        if (
            not isinstance(target, dict)
            or not str(target.get("robot_code") or "")
            or not isinstance(user_ids, list)
            or not user_ids
            or any(not isinstance(user_id, str) or not user_id for user_id in user_ids)
            or type(target.get("recipient_count")) is not int
            or target.get("recipient_count") != len(user_ids)
            or not isinstance(msg_param, dict)
            or set(msg_param) != {"title", "text"}
            or not isinstance(msg_param.get("title"), str)
            or not isinstance(msg_param.get("text"), str)
        ):
            raise NonRetryableExecutionError(
                "DingTalk robot user batch target is invalid",
                safe_message="钉钉机器人批量收件人或消息参数无效",
                error_code="dingtalk_robot_user_batch_invalid",
            )
        response = self._request(
            "POST",
            "/v1.0/robot/oToMessages/batchSend",
            payload={
                "robotCode": str(target["robot_code"]),
                "userIds": list(user_ids),
                "msgKey": "sampleMarkdown",
                "msgParam": _robot_markdown_msg_param(
                    title=msg_param["title"],
                    text=msg_param["text"],
                ),
            },
        )
        request_id = _text(
            response.get("processQueryKey") or response.get("requestId"),
            512,
        )
        process_query_keys = response.get("processQueryKeys")
        if not request_id and isinstance(process_query_keys, list) and process_query_keys:
            request_id = _text(process_query_keys[0], 512)
        return {
            "message_request_id": request_id,
            "recipient_count": len(user_ids),
            "sent": True,
        }

    def send_current(self, *, arguments: dict[str, Any]) -> dict[str, Any]:
        target = arguments.get("_target")
        if not isinstance(target, dict):
            raise NonRetryableExecutionError(
                "DingTalk robot target is invalid",
                safe_message="钉钉机器人目标无效",
                error_code="dingtalk_robot_target_invalid",
            )
        payload: dict[str, Any] = {
            "robotCode": str(target["robot_code"]),
            "msgKey": "sampleMarkdown",
            "msgParam": _robot_markdown_msg_param(
                title=arguments["title"],
                text=arguments["text"],
            ),
        }
        if str(target.get("conversation_type")) == "group":
            path = "/v1.0/robot/groupMessages/send"
            payload["openConversationId"] = str(target["open_conversation_id"])
        elif str(target.get("conversation_type")) == "direct":
            path = "/v1.0/robot/oToMessages/batchSend"
            payload["userIds"] = [str(target["staff_id"])]
        else:
            raise NonRetryableExecutionError(
                "DingTalk robot conversation type is invalid",
                safe_message="钉钉机器人目标无效",
                error_code="dingtalk_robot_target_invalid",
            )
        response = self._request("POST", path, payload=payload)
        request_id = _text(
            response.get("processQueryKey")
            or response.get("processQueryKeys")
            or response.get("requestId"),
            512,
        )
        return {"message_request_id": request_id, "sent": True}


class DingTalkWorkNotificationMutationClient(_FixedDingTalkClient):
    def send_to_self(self, *, arguments: dict[str, Any]) -> dict[str, Any]:
        target = arguments.get("_target")
        if not isinstance(target, dict):
            raise NonRetryableExecutionError(
                "DingTalk work notification target is invalid",
                safe_message="钉钉工作通知目标无效",
                error_code="dingtalk_work_notification_target_invalid",
            )
        response = self._request(
            "POST",
            "/topapi/message/corpconversation/asyncsend_v2",
            legacy=True,
            payload={
                "agent_id": int(target["agent_id"]),
                "userid_list": str(target["staff_id"]),
                "to_all_user": False,
                "msg": {
                    "msgtype": "markdown",
                    "markdown": {
                        "title": arguments["title"],
                        "text": arguments["text"],
                    },
                },
            },
        )
        task_id = _integer(
            response.get("task_id")
            or response.get("taskId")
            or _provider_object(response).get("task_id")
        )
        return {"task_id": task_id, "sent": True}


def _robot_markdown_msg_param(*, title: str, text: str) -> str:
    return json.dumps(
        {"title": title, "text": text},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _calendar_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if "title" in arguments:
        payload["summary"] = arguments["title"]
    if "description" in arguments:
        payload["description"] = arguments["description"]
    if "all_day" in arguments:
        payload["isAllDay"] = bool(arguments["all_day"])
    if "location" in arguments:
        payload["location"] = {"displayName": arguments["location"]}
    time_zone = str(arguments.get("time_zone") or "")
    if arguments.get("start_time"):
        payload["start"] = {
            "dateTime": arguments["start_time"],
            "timeZone": time_zone,
        }
    if arguments.get("end_time"):
        payload["end"] = {"dateTime": arguments["end_time"], "timeZone": time_zone}
    return payload


def _provider_object(response: dict[str, Any]) -> dict[str, Any]:
    for key in ("result", "data"):
        value = response.get(key)
        if isinstance(value, dict):
            return value
    return response


def _provider_items(response: dict[str, Any], *keys: str) -> list[Any]:
    containers = (_provider_object(response), response)
    for container in containers:
        for key in keys:
            value = container.get(key)
            if isinstance(value, list):
                return value
    result = response.get("result")
    return result if isinstance(result, list) else []


def _text(value: object, maximum: int) -> str:
    return str(value or "")[:maximum]


def _integer(value: object, default: int = 0) -> int:
    try:
        if isinstance(value, (int, float)):
            return int(value)
        return int(str(value or default))
    except (TypeError, ValueError):
        return default


def _boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").lower() in {"1", "true", "yes"}


def _page(
    field: str,
    items: list[dict[str, Any]],
    response: dict[str, Any],
    maximum: int,
    *,
    offset: int = 0,
) -> dict[str, Any]:
    source = _provider_object(response)
    cursor = _text(
        source.get("nextToken") or source.get("next_token") or response.get("nextToken"),
        512,
    )
    has_more = _boolean(
        source.get("hasMore", source.get("has_more", response.get("hasMore", False)))
    )
    total_count = _integer(
        source.get(
            "totalCount",
            source.get("total_count", response.get("totalCount", -1)),
        ),
        -1,
    )
    returned = min(len(items), maximum)
    output: dict[str, Any] = {
        field: items[:maximum],
        "returned": returned,
        "truncated": (
            len(items) > maximum
            or bool(cursor)
            or has_more
            or (total_count >= 0 and total_count > max(0, offset) + returned)
        ),
        "untrusted_data": True,
    }
    if cursor:
        output["next_cursor"] = cursor
    return output


def _project_search_user(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        user_id = _text(value, 512)
        if user_id:
            return {"user_id": user_id}
    elif isinstance(value, dict):
        user = _project_user(value)
        if user.get("user_id"):
            return user
    raise RetryableExecutionError(
        "DingTalk user search item was invalid",
        safe_message="钉钉开放接口响应无效",
        error_code="dingtalk_response_invalid",
    )


def _project_user(value: object) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    departments = row.get("dept_id_list") or row.get("departmentIds") or []
    output: dict[str, Any] = {
        "user_id": _text(row.get("userid") or row.get("userId") or row.get("id"), 512),
    }
    optional = {
        "union_id": _text(row.get("unionid") or row.get("unionId"), 512),
        "name": _text(row.get("name"), 200),
        "title": _text(row.get("title"), 200),
    }
    output.update({key: item for key, item in optional.items() if item})
    if isinstance(departments, list):
        output["department_ids"] = [
            parsed for item in departments[:50] if (parsed := _integer(item, -1)) >= 1
        ]
    if "active" in row:
        output["active"] = _boolean(row.get("active"))
    if "admin" in row or "isAdmin" in row:
        output["admin"] = _boolean(row.get("admin", row.get("isAdmin")))
    return output


def _project_department(value: object) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    output: dict[str, Any] = {
        "department_id": _integer(row.get("dept_id") or row.get("deptId") or row.get("id"), 1),
        "name": _text(row.get("name"), 200),
    }
    parent = _integer(row.get("parent_id") or row.get("parentId"), -1)
    if parent >= 0:
        output["parent_department_id"] = parent
    if row.get("member_count") is not None or row.get("memberCount") is not None:
        output["member_count"] = max(0, _integer(row.get("member_count", row.get("memberCount"))))
    if "auto_add_user" in row:
        output["auto_add_user"] = _boolean(row.get("auto_add_user"))
    if "create_dept_group" in row:
        output["create_group"] = _boolean(row.get("create_dept_group"))
    return output


def _project_todo(value: object) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    return {
        "task_id": _text(row.get("taskId") or row.get("id"), 512),
        "subject": _text(row.get("subject") or row.get("title"), 200),
        "description": _text(row.get("description"), 2000),
        "due_time": _text(row.get("dueTime") or row.get("due_time"), 64),
        "done": _boolean(row.get("done") or row.get("isDone")),
        **({"created_at": _text(row.get("createdTime"), 64)} if row.get("createdTime") else {}),
        **({"updated_at": _text(row.get("modifiedTime"), 64)} if row.get("modifiedTime") else {}),
    }


def _time_value(value: object) -> tuple[str, str]:
    if not isinstance(value, dict):
        return _text(value, 64), ""
    return (
        _text(value.get("dateTime") or value.get("date"), 64),
        _text(value.get("timeZone"), 64),
    )


def _project_event(value: object) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    start, start_zone = _time_value(row.get("start"))
    end, end_zone = _time_value(row.get("end"))
    location = row.get("location")
    location_name = (
        _text(location.get("displayName"), 500)
        if isinstance(location, dict)
        else _text(location, 500)
    )
    attendees = row.get("attendees")
    return {
        "event_id": _text(row.get("id") or row.get("eventId"), 512),
        "title": _text(row.get("summary") or row.get("title"), 500),
        "description": _text(row.get("description"), 4000),
        "start_time": start,
        "end_time": end,
        "time_zone": start_zone or end_zone,
        "all_day": _boolean(row.get("isAllDay")),
        "location": location_name,
        **({"status": _text(row.get("status"), 64)} if row.get("status") else {}),
        **({"attendee_count": len(attendees)} if isinstance(attendees, list) else {}),
    }


def _project_attendee(value: object) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    return {
        "union_id": _text(row.get("id") or row.get("unionId"), 512),
        **(
            {"name": _text(row.get("displayName") or row.get("name"), 200)}
            if row.get("displayName") or row.get("name")
            else {}
        ),
        **(
            {"response_status": _text(row.get("responseStatus"), 64)}
            if row.get("responseStatus")
            else {}
        ),
        **({"optional": _boolean(row.get("isOptional"))} if "isOptional" in row else {}),
    }


def _project_aitable(value: object) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    return {
        "base_id": _text(row.get("dentryUuid") or row.get("baseId") or row.get("id"), 512),
        "name": _text(row.get("name") or row.get("title"), 300),
        **({"creator_user_id": _text(row.get("creatorId"), 512)} if row.get("creatorId") else {}),
        **({"updated_at": _text(row.get("modifiedTime"), 64)} if row.get("modifiedTime") else {}),
    }


def _project_sheet(value: object) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    return {
        "sheet_id": _text(row.get("id") or row.get("sheetId"), 512),
        "name": _text(row.get("name"), 300),
    }


def _project_field(value: object) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    return {
        "field_id": _text(row.get("id") or row.get("fieldId"), 512),
        "name": _text(row.get("name"), 300),
        "field_type": _text(row.get("type") or row.get("fieldType"), 64),
        **({"primary": _boolean(row.get("isPrimary"))} if "isPrimary" in row else {}),
    }


def _bounded_field_value(value: object, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:2000]
    if depth >= 1:
        return _text(value, 2000)
    if isinstance(value, list):
        return [_bounded_field_value(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, dict):
        return {
            _text(key, 128): _bounded_field_value(item, depth=depth + 1)
            for key, item in list(value.items())[:20]
            if _text(key, 128)
        }
    return _text(value, 2000)


def _project_record(value: object) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    raw_fields = row.get("fields")
    fields = dict(raw_fields) if isinstance(raw_fields, dict) else {}
    return {
        "record_id": _text(row.get("id") or row.get("recordId"), 512),
        "fields": {
            _text(key, 128): _bounded_field_value(item)
            for key, item in list(fields.items())[:50]
            if _text(key, 128)
        },
        **({"created_at": _text(row.get("createdTime"), 64)} if row.get("createdTime") else {}),
        **({"updated_at": _text(row.get("updatedTime"), 64)} if row.get("updatedTime") else {}),
    }


def _project_notice_progress(value: object, task_id: int) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    return {
        "task_id": task_id,
        "status": _text(row.get("status") or row.get("send_status") or "UNKNOWN", 64),
        **(
            {"progress": min(100, max(0, _integer(row.get("progress"))))}
            if row.get("progress") is not None
            else {}
        ),
        **(
            {"sent_count": max(0, _integer(row.get("send_count")))}
            if row.get("send_count") is not None
            else {}
        ),
        **(
            {"failed_count": max(0, _integer(row.get("failed_count")))}
            if row.get("failed_count") is not None
            else {}
        ),
    }


def _project_notice_result(value: object, task_id: int) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    invalid = row.get("invalid_user_id_list") or row.get("invalidUserIds") or []
    return {
        "task_id": task_id,
        "status": _text(row.get("status") or row.get("send_status") or "UNKNOWN", 64),
        **(
            {"sent_count": max(0, _integer(row.get("send_count")))}
            if row.get("send_count") is not None
            else {}
        ),
        **(
            {"failed_count": max(0, _integer(row.get("failed_count")))}
            if row.get("failed_count") is not None
            else {}
        ),
        **(
            {"invalid_user_ids": [_text(item, 512) for item in invalid[:50] if _text(item, 512)]}
            if isinstance(invalid, list)
            else {}
        ),
    }
