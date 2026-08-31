from __future__ import annotations

import json
import re
from typing import Any, NoReturn, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from app.modules.dingding.infrastructure.dingtalk_delivery_clients import DingTalkAccessTokenClient
from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError


CARD_TEMPLATE_ID = "0ad7c643-7e30-4797-8284-da5ef89d3841.schema"
OPEN_API_BASE = "https://api.dingtalk.com"
LEGACY_API_BASE = "https://oapi.dingtalk.com"
LEGACY_ALLOWED_PATHS = frozenset(
    {
        "/topapi/user/listid",
        "/topapi/v2/department/get",
        "/topapi/v2/department/listsub",
        "/topapi/message/corpconversation/asyncsend_v2",
        "/topapi/message/corpconversation/getsendprogress",
        "/topapi/message/corpconversation/getsendresult",
    }
)
MAX_PROVIDER_ERROR_BODY_BYTES = 64 * 1024
_PROVIDER_ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")


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
            diagnostics = _provider_http_error_diagnostics(exc)
            provider_code = str(diagnostics.get("provider_error_code") or "")
            if status in {401, 403}:
                raise NonRetryableExecutionError(
                    (
                        f"DingTalk governed request permission denied status={status}"
                        f" provider_code={provider_code or 'unavailable'}"
                    ),
                    safe_message=_provider_safe_message(
                        "钉钉应用缺少此能力所需权限或可见范围",
                        provider_code,
                    ),
                    error_code="dingtalk_permission_denied",
                    diagnostics=diagnostics,
                ) from exc
            if status == 429:
                raise RetryableExecutionError(
                    "DingTalk governed request was rate limited",
                    safe_message=_provider_safe_message(
                        "钉钉开放接口请求过于频繁",
                        provider_code,
                    ),
                    error_code="dingtalk_rate_limited",
                    diagnostics=diagnostics,
                ) from exc
            error = NonRetryableExecutionError if 400 <= status < 500 else RetryableExecutionError
            raise error(
                (
                    f"DingTalk governed request failed status={status}"
                    f" provider_code={provider_code or 'unavailable'}"
                ),
                safe_message=_provider_safe_message(
                    "钉钉开放接口请求失败",
                    provider_code,
                ),
                error_code=f"dingtalk_http_{status or 'unknown'}",
                diagnostics=diagnostics,
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
            provider_code = _safe_provider_error_code(code)
            raise NonRetryableExecutionError(
                f"DingTalk provider rejected request code={provider_code or 'unavailable'}",
                safe_message=_provider_safe_message(
                    "钉钉开放接口拒绝了该操作",
                    provider_code,
                ),
                error_code="dingtalk_provider_rejected",
                diagnostics=(
                    {"provider_error_code": provider_code}
                    if provider_code
                    else {}
                ),
            )
        return value


def _provider_http_error_diagnostics(exc: HTTPError) -> dict[str, object]:
    try:
        body = exc.read(MAX_PROVIDER_ERROR_BODY_BYTES + 1)
    except Exception:
        return {}
    if not isinstance(body, bytes) or len(body) > MAX_PROVIDER_ERROR_BODY_BYTES:
        return {}
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    for key in ("code", "errcode", "errorCode"):
        provider_code = _safe_provider_error_code(value.get(key))
        if provider_code:
            return {"provider_error_code": provider_code}
    return {}


def _safe_provider_error_code(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    candidate = str(value)
    return candidate if _PROVIDER_ERROR_CODE_PATTERN.fullmatch(candidate) else ""


def _provider_safe_message(message: str, provider_code: str) -> str:
    return f"{message}（钉钉错误码：{provider_code}）" if provider_code else message


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
        if not task_id:
            _raise_response_invalid("dingtalk.todo.create", response)
        return {"task_id": task_id, "created": True}

    def update_for_self(self, *, union_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        task_id = str(arguments["task_id"])
        payload: dict[str, Any] = {
            "subject": arguments["subject"],
            "description": arguments.get("description", ""),
        }
        if arguments.get("due_time_ms") is not None:
            payload["dueTime"] = int(arguments["due_time_ms"])
        response = self.transport.request_json(
            "PUT",
            (
                f"{OPEN_API_BASE}/v1.0/todo/users/{quote(union_id, safe='')}/"
                f"tasks/{quote(task_id, safe='')}"
            ),
            payload,
            {"x-acs-dingtalk-access-token": self.token_client.access_token()},
            self.timeout_seconds,
        )
        if response.get("result") is not True:
            _raise_response_invalid("dingtalk.todo.update", response)
        return {"task_id": task_id, "updated": True}

    def complete_for_self(
        self,
        *,
        union_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = str(arguments["task_id"])
        response = self.transport.request_json(
            "PUT",
            (
                f"{OPEN_API_BASE}/v1.0/todo/users/{quote(union_id, safe='')}/"
                f"tasks/{quote(task_id, safe='')}/executorStatus"
            ),
            {"executorStatusList": [{"id": union_id, "isDone": True}]},
            {"x-acs-dingtalk-access-token": self.token_client.access_token()},
            self.timeout_seconds,
        )
        if response.get("result") is not True:
            _raise_response_invalid("dingtalk.todo.complete", response)
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
        if legacy and path not in LEGACY_ALLOWED_PATHS:
            raise ValueError("DingTalk legacy operation is not allowlisted")
        if not legacy and path.startswith("/topapi/"):
            raise ValueError("DingTalk topapi operation must be explicitly legacy")
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
        rows = _provider_items(
            response,
            "list",
            operation="dingtalk.contact.user.search",
        )
        return _page(
            "users",
            [_project_search_user(row) for row in rows],
            response,
            page_size,
            offset=offset,
        )

    def get_user(self, *, user_id: str, language: str) -> dict[str, Any]:
        # The latest contact_1.0 BatchGetUser API accepts enterprise user IDs
        # directly. `language` remains accepted here only so historical Job
        # snapshots can execute after the current catalog removes that legacy
        # argument.
        del language
        response = self._request(
            "GET",
            "/v1.0/contact/users/batch/get",
            query={
                "userIdList": json.dumps(
                    [user_id],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            },
        )
        unauthorized = response.get("unauthorizedUserIdList", [])
        if not isinstance(unauthorized, list):
            _raise_response_invalid("dingtalk.contact.user.get", response)
        if user_id in unauthorized:
            raise NonRetryableExecutionError(
                "DingTalk user detail is outside the application visible scope",
                safe_message="钉钉应用无权查看该用户",
                error_code="dingtalk_permission_denied",
            )
        rows = _provider_items(
            response,
            "userList",
            operation="dingtalk.contact.user.get",
        )
        if not rows:
            raise NonRetryableExecutionError(
                "DingTalk user detail was not visible",
                safe_message="钉钉未返回该用户，用户可能不存在或不在应用可见范围",
                error_code="dingtalk_user_not_visible",
            )
        if len(rows) != 1 or not isinstance(rows[0], dict):
            _raise_response_invalid("dingtalk.contact.user.get", response)
        user = _project_user(rows[0])
        _require_projected_fields("dingtalk.contact.user.get", user, "user_id")
        if user["user_id"] != user_id:
            _raise_response_invalid("dingtalk.contact.user.get", response)
        return {"user": user, "untrusted_data": True}

    def list_department_users(self, *, department_id: int) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/topapi/user/listid",
            payload={"dept_id": department_id},
            legacy=True,
        )
        rows = _provider_items(
            _legacy_result_object(
                response,
                operation="dingtalk.contact.department_users.list",
            ),
            "userid_list",
            operation="dingtalk.contact.department_users.list",
        )
        users = [_project_user(row if isinstance(row, dict) else {"userid": row}) for row in rows]
        _require_projected_items("dingtalk.contact.department_users.list", users, "user_id")
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
        rows = _provider_items(
            response,
            "list",
            operation="dingtalk.department.search",
        )
        departments = [_project_department(row) for row in rows]
        _require_projected_items("dingtalk.department.search", departments, "department_id")
        return _page(
            "departments",
            departments,
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
        department = _project_department(
            _legacy_result_object(response, operation="dingtalk.department.get")
        )
        _require_projected_fields(
            "dingtalk.department.get",
            department,
            "department_id",
            "name",
        )
        return {
            "department": department,
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
        rows = _legacy_result_items(
            response,
            operation="dingtalk.department.children.list",
        )
        departments = [_project_department(row) for row in rows]
        _require_projected_items(
            "dingtalk.department.children.list",
            departments,
            "department_id",
            "name",
        )
        return _page(
            "departments",
            departments,
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
        rows = _provider_items(
            response,
            "todoCards",
            operation="dingtalk.todo.list",
        )
        todos = [_project_todo(row) for row in rows]
        _require_projected_items("dingtalk.todo.list", todos, "task_id", "subject")
        return _page("todos", todos, response, 50)


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
        event = _project_event(response)
        _require_projected_fields(
            "dingtalk.calendar.event.get",
            event,
            "event_id",
            "title",
            "start_time",
            "end_time",
        )
        return {"event": event, "untrusted_data": True}

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
        rows = _provider_items(
            response,
            "events",
            operation="dingtalk.calendar.event.list",
        )
        events = [_project_event(row) for row in rows]
        _require_projected_items(
            "dingtalk.calendar.event.list",
            events,
            "event_id",
            "title",
            "start_time",
            "end_time",
        )
        return _page("events", events, response, page_size)

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
        rows = _provider_items(
            response,
            "attendees",
            operation="dingtalk.calendar.attendee.list",
        )
        attendees = [_project_attendee(row) for row in rows]
        _require_projected_items(
            "dingtalk.calendar.attendee.list",
            attendees,
            "union_id",
        )
        return _page(
            "attendees",
            attendees,
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
        rows = _provider_items(
            response,
            "items",
            operation="dingtalk.aitable.search",
        )
        aitables = [_project_aitable(row) for row in rows]
        _require_projected_items("dingtalk.aitable.search", aitables, "base_id", "name")
        return _page("aitables", aitables, response, page_size)

    def list_sheets(self, *, operator_id: str, base_id: str) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"/v1.0/notable/bases/{quote(base_id, safe='')}/sheets",
            query={"operatorId": operator_id},
        )
        rows = _provider_items(
            response,
            "value",
            operation="dingtalk.aitable.sheet.list",
        )
        sheets = [_project_sheet(row) for row in rows]
        _require_projected_items("dingtalk.aitable.sheet.list", sheets, "sheet_id", "name")
        return _page("sheets", sheets, response, 50)

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
        sheet = _project_sheet(response)
        _require_projected_fields(
            "dingtalk.aitable.sheet.get",
            sheet,
            "sheet_id",
            "name",
        )
        return {"sheet": sheet, "untrusted_data": True}

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
        rows = _provider_items(
            response,
            "value",
            operation="dingtalk.aitable.field.list",
        )
        fields = [_project_field(row) for row in rows]
        _require_projected_items(
            "dingtalk.aitable.field.list",
            fields,
            "field_id",
            "name",
            "field_type",
        )
        return _page("fields", fields, response, 50)

    def list_records(
        self,
        *,
        operator_id: str,
        base_id: str,
        sheet_id: str,
        page_size: int,
        cursor: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"maxResults": page_size}
        if cursor:
            payload["nextToken"] = cursor
        response = self._request(
            "POST",
            (
                f"/v1.0/notable/bases/{quote(base_id, safe='')}/"
                f"sheets/{quote(sheet_id, safe='')}/records/list"
            ),
            query={"operatorId": operator_id},
            payload=payload,
        )
        rows = _provider_items(
            response,
            "records",
            operation="dingtalk.aitable.record.list",
        )
        records = [_project_record(row) for row in rows]
        _require_projected_items(
            "dingtalk.aitable.record.list",
            records,
            "record_id",
        )
        return _page("records", records, response, page_size)

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
        record = _project_record(response)
        _require_projected_fields(
            "dingtalk.aitable.record.get",
            record,
            "record_id",
        )
        return {"record": record, "untrusted_data": True}


class DingTalkWorkNotificationReadClient(_FixedDingTalkClient):
    def get_progress(self, *, agent_id: int, task_id: int) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/topapi/message/corpconversation/getsendprogress",
            payload={"agent_id": agent_id, "task_id": task_id},
            legacy=True,
        )
        return {
            "progress": _project_notice_progress(
                _provider_nested_object(
                    response,
                    "progress",
                    operation="dingtalk.work_notification.progress.get",
                ),
                task_id,
            ),
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
            "result": _project_notice_result(
                _provider_nested_object(
                    response,
                    "send_result",
                    operation="dingtalk.work_notification.result.get",
                ),
                task_id,
            ),
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
        event = response
        event_id = _text(event.get("id") or event.get("eventId"), 512)
        if not event_id:
            _raise_response_invalid("dingtalk.calendar.event.create", response)
        return {
            "event_id": event_id,
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
        response = self._request(
            "PUT",
            (
                f"/v1.0/calendar/users/{quote(union_id, safe='')}/calendars/primary/"
                f"events/{quote(event_id, safe='')}"
            ),
            payload=payload,
        )
        returned = response
        returned_event_id = _text(returned.get("id") or returned.get("eventId"), 512)
        if not returned_event_id or returned_event_id != event_id:
            _raise_response_invalid("dingtalk.calendar.event.update", response)
        return {"event_id": event_id, "updated": True}


class DingTalkAiTableMutationClient(_FixedDingTalkClient):
    def create_sheet(
        self,
        *,
        operator_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": arguments["name"]}
        if arguments.get("fields"):
            payload["fields"] = arguments["fields"]
        response = self._request(
            "POST",
            f"/v1.0/notable/bases/{quote(str(arguments['base_id']), safe='')}/sheets",
            query={"operatorId": operator_id},
            payload=payload,
        )
        sheet = _project_sheet(response)
        _require_projected_fields(
            "dingtalk.aitable.sheet.create",
            sheet,
            "sheet_id",
            "name",
        )
        if sheet["name"] != str(arguments["name"]):
            _raise_response_invalid("dingtalk.aitable.sheet.create", response)
        return {**sheet, "created": True}

    def update_sheet(
        self,
        *,
        operator_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        sheet_id = str(arguments["sheet_id"])
        response = self._request(
            "PUT",
            (
                f"/v1.0/notable/bases/{quote(str(arguments['base_id']), safe='')}/"
                f"sheets/{quote(sheet_id, safe='')}"
            ),
            query={"operatorId": operator_id},
            payload={"name": arguments["name"]},
        )
        sheet = _project_sheet(response)
        _require_projected_fields(
            "dingtalk.aitable.sheet.update",
            sheet,
            "sheet_id",
            "name",
        )
        if sheet != {"sheet_id": sheet_id, "name": str(arguments["name"])}:
            _raise_response_invalid("dingtalk.aitable.sheet.update", response)
        return {**sheet, "updated": True}

    def create_field(
        self,
        *,
        operator_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": arguments["name"],
            "type": arguments["type"],
        }
        if "property" in arguments:
            payload["property"] = arguments["property"]
        response = self._request(
            "POST",
            (
                f"/v1.0/notable/bases/{quote(str(arguments['base_id']), safe='')}/"
                f"sheets/{quote(str(arguments['sheet_id']), safe='')}/fields"
            ),
            query={"operatorId": operator_id},
            payload=payload,
        )
        field = _project_field(response)
        _require_projected_fields(
            "dingtalk.aitable.field.create",
            field,
            "field_id",
            "name",
            "field_type",
        )
        if (
            field["name"] != str(arguments["name"])
            or field["field_type"] != str(arguments["type"])
        ):
            _raise_response_invalid("dingtalk.aitable.field.create", response)
        return {
            "field_id": field["field_id"],
            "name": field["name"],
            "field_type": field["field_type"],
            "created": True,
        }

    def update_field(
        self,
        *,
        operator_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        field_id = str(arguments["field_id"])
        payload: dict[str, Any] = {"name": arguments["name"]}
        if "property" in arguments:
            payload["property"] = arguments["property"]
        response = self._request(
            "PUT",
            (
                f"/v1.0/notable/bases/{quote(str(arguments['base_id']), safe='')}/"
                f"sheets/{quote(str(arguments['sheet_id']), safe='')}/fields/"
                f"{quote(field_id, safe='')}"
            ),
            query={"operatorId": operator_id},
            payload=payload,
        )
        returned_field_id = _text(response.get("id") or response.get("fieldId"), 512)
        if returned_field_id != field_id:
            _raise_response_invalid("dingtalk.aitable.field.update", response)
        return {"field_id": field_id, "updated": True}

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
        rows = _provider_items(
            response,
            "value",
            operation="dingtalk.aitable.record.insert",
        )
        record_ids = [
            _text(row.get("id") or row.get("recordId"), 512)
            for row in rows
            if isinstance(row, dict) and (row.get("id") or row.get("recordId"))
        ]
        if (
            len(record_ids) != len(arguments["records"])
            or len(set(record_ids)) != len(record_ids)
        ):
            _raise_response_invalid("dingtalk.aitable.record.insert", response)
        return {
            "record_ids": record_ids,
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
        response = self._request(
            "PUT",
            (
                f"/v1.0/notable/bases/{quote(str(arguments['base_id']), safe='')}/"
                f"sheets/{quote(str(arguments['sheet_id']), safe='')}/records"
            ),
            query={"operatorId": operator_id},
            payload={"records": records},
        )
        rows = _provider_items(
            response,
            "value",
            operation="dingtalk.aitable.record.update",
        )
        updated_ids = [
            _text(row.get("id") or row.get("recordId"), 512)
            for row in rows
            if isinstance(row, dict) and (row.get("id") or row.get("recordId"))
        ]
        expected_ids = [str(row["id"]) for row in records]
        if len(updated_ids) != len(records) or sorted(updated_ids) != sorted(expected_ids):
            _raise_response_invalid("dingtalk.aitable.record.update", response)
        return {
            "record_ids": updated_ids,
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
        request_id = _text(response.get("processQueryKey"), 512)
        if not request_id:
            _raise_response_invalid(
                "dingtalk.robot.batch_send_message_to_users",
                response,
            )
        filtered = _provider_optional_id_list(
            response,
            "filteredStaffIdList",
            operation="dingtalk.robot.batch_send_message_to_users",
        )
        flow_controlled = _provider_optional_id_list(
            response,
            "flowControlledStaffIdList",
            operation="dingtalk.robot.batch_send_message_to_users",
        )
        invalid = _provider_optional_id_list(
            response,
            "invalidStaffIdList",
            operation="dingtalk.robot.batch_send_message_to_users",
        )
        requested = set(user_ids)
        not_accepted = set(filtered) | set(flow_controlled) | set(invalid)
        if not not_accepted.issubset(requested):
            _raise_response_invalid(
                "dingtalk.robot.batch_send_message_to_users",
                response,
            )
        return {
            "message_request_id": request_id,
            "recipient_count": len(user_ids),
            "accepted_count": max(0, len(user_ids) - len(not_accepted)),
            "not_accepted_count": len(not_accepted),
            "filtered_count": len(set(filtered)),
            "flow_controlled_count": len(set(flow_controlled)),
            "invalid_count": len(set(invalid)),
            "fully_accepted": not not_accepted,
            "accepted": True,
        }

    def send_to_group(self, *, arguments: dict[str, Any]) -> dict[str, Any]:
        target = arguments.get("_target")
        if (
            not isinstance(target, dict)
            or not str(target.get("robot_code") or "")
            or not str(target.get("open_conversation_id") or "")
        ):
            raise NonRetryableExecutionError(
                "DingTalk robot target is invalid",
                safe_message="钉钉机器人群聊目标无效",
                error_code="dingtalk_robot_target_invalid",
            )
        payload: dict[str, Any] = {
            "robotCode": str(target["robot_code"]),
            "openConversationId": str(target["open_conversation_id"]),
            "msgKey": "sampleMarkdown",
            "msgParam": _robot_markdown_msg_param(
                title=arguments["title"],
                text=arguments["text"],
            ),
        }
        response = self._request(
            "POST",
            "/v1.0/robot/groupMessages/send",
            payload=payload,
        )
        request_id = _text(response.get("processQueryKey"), 512)
        if not request_id:
            _raise_response_invalid("dingtalk.robot.group_message.send", response)
        return {"message_request_id": request_id, "accepted": True}


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
        )
        if task_id <= 0:
            _raise_response_invalid("dingtalk.work_notification.send", response)
        return {"task_id": task_id, "accepted": True}


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
    all_day = bool(arguments.get("all_day"))
    if arguments.get("start_time"):
        payload["start"] = (
            {"date": arguments["start_time"]}
            if all_day
            else {"dateTime": arguments["start_time"], "timeZone": time_zone}
        )
    if arguments.get("end_time"):
        payload["end"] = (
            {"date": arguments["end_time"]}
            if all_day
            else {"dateTime": arguments["end_time"], "timeZone": time_zone}
        )
    return payload


def _legacy_result_object(
    response: dict[str, Any],
    *,
    operation: str,
) -> dict[str, Any]:
    value = response.get("result")
    if isinstance(value, dict):
        return value
    _raise_response_invalid(operation, response)


def _legacy_result_items(
    response: dict[str, Any],
    *,
    operation: str,
) -> list[Any]:
    value = response.get("result")
    if isinstance(value, list):
        return value
    _raise_response_invalid(operation, response)


def _provider_nested_object(
    response: dict[str, Any],
    key: str,
    *,
    operation: str,
) -> dict[str, Any]:
    if key in response:
        value = response.get(key)
        if isinstance(value, dict):
            return value
        _raise_response_invalid(operation, response)
    _raise_response_invalid(operation, response)


def _provider_items(
    response: dict[str, Any],
    *keys: str,
    operation: str,
) -> list[Any]:
    for key in keys:
        if key in response:
            value = response.get(key)
            if isinstance(value, list):
                return value
            _raise_response_invalid(operation, response)
    _raise_response_invalid(operation, response)


def _provider_optional_id_list(
    response: dict[str, Any],
    key: str,
    *,
    operation: str,
) -> list[str]:
    if key not in response:
        return []
    value = response.get(key)
    if not isinstance(value, list):
        _raise_response_invalid(operation, response)
    projected: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            _raise_response_invalid(operation, response)
        projected.append(item)
    return projected


def _require_projected_items(
    operation: str,
    items: list[dict[str, Any]],
    *required_fields: str,
) -> None:
    for item in items:
        _require_projected_fields(operation, item, *required_fields)


def _require_projected_fields(
    operation: str,
    item: dict[str, Any],
    *required_fields: str,
) -> None:
    for field in required_fields:
        value = item.get(field)
        if (
            value is None
            or value == ""
            or (not isinstance(value, bool) and value == 0)
            or (isinstance(value, (dict, list)) and not value)
        ):
            _raise_response_invalid(operation, item)


def _raise_response_invalid(operation: str, response: dict[str, Any]) -> NoReturn:
    keys = sorted(str(key)[:64] for key in response)[:20]
    raise RetryableExecutionError(
        f"DingTalk {operation} response shape was invalid keys={keys}",
        safe_message="钉钉开放接口响应结构无效",
        error_code="dingtalk_response_invalid",
    )


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
    source = response
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
    departments = (
        row.get("dept_id_list")
        if "dept_id_list" in row
        else row.get("departmentIds")
        if "departmentIds" in row
        else None
    )
    output: dict[str, Any] = {
        "user_id": _text(row.get("userid") or row.get("userId") or row.get("id"), 512),
    }
    optional = {
        "union_id": _text(row.get("unionid") or row.get("unionId"), 512),
        "name": _text(row.get("name"), 200),
        "job_number": _text(row.get("job_number") or row.get("jobNumber"), 200),
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
    if isinstance(value, (int, str)) and not isinstance(value, bool):
        department_id = _integer(value, 0)
        if department_id > 0:
            return {"department_id": department_id}
    row = value if isinstance(value, dict) else {}
    output: dict[str, Any] = {
        "department_id": _integer(row.get("dept_id") or row.get("deptId") or row.get("id"), 0),
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
    if not isinstance(value, dict):
        _raise_response_invalid("dingtalk.todo.list", {})
    row = value
    done_key = "done" if "done" in row else "isDone" if "isDone" in row else ""
    if not done_key or not isinstance(row.get(done_key), bool):
        _raise_response_invalid("dingtalk.todo.list", row)
    return {
        "task_id": _text(row.get("taskId") or row.get("id"), 512),
        "subject": _text(row.get("subject") or row.get("title"), 200),
        "description": _text(row.get("description"), 2000),
        "due_time": _text(row.get("dueTime") or row.get("due_time"), 64),
        "done": bool(row[done_key]),
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
    if not isinstance(value, dict):
        _raise_response_invalid("dingtalk.calendar.event", {})
    row = value
    if not isinstance(row.get("start"), dict) or not isinstance(row.get("end"), dict):
        _raise_response_invalid("dingtalk.calendar.event", row)
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
    if not isinstance(value, dict):
        _raise_response_invalid("dingtalk.aitable.search", {})
    row = value
    creator = row.get("creator")
    creator_user_id = (
        _text(creator.get("userId"), 512)
        if isinstance(creator, dict)
        else _text(row.get("creatorId"), 512)
    )
    return {
        "base_id": _text(row.get("dentryUuid") or row.get("baseId") or row.get("id"), 512),
        "name": _text(row.get("name") or row.get("title"), 300),
        **({"creator_user_id": creator_user_id} if creator_user_id else {}),
        **(
            {"updated_at": _text(row.get("lastModifyTime") or row.get("modifiedTime"), 64)}
            if row.get("lastModifyTime") or row.get("modifiedTime")
            else {}
        ),
    }


def _project_sheet(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        _raise_response_invalid("dingtalk.aitable.sheet", {})
    row = value
    return {
        "sheet_id": _text(row.get("id") or row.get("sheetId"), 512),
        "name": _text(row.get("name"), 300),
    }


def _project_field(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        _raise_response_invalid("dingtalk.aitable.field.list", {})
    row = value
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
    if depth >= 2:
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
    if not isinstance(value, dict):
        _raise_response_invalid("dingtalk.aitable.record", {})
    row = value
    raw_fields = row.get("fields")
    if not isinstance(raw_fields, dict):
        _raise_response_invalid("dingtalk.aitable.record", row)
    fields = dict(raw_fields)
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
    status = _integer(row.get("status"), -1)
    progress = _integer(row.get("progress_in_percent"), -1)
    if status not in {0, 1, 2} or not 0 <= progress <= 100:
        _raise_response_invalid("dingtalk.work_notification.progress.get", row)
    return {
        "task_id": task_id,
        "status": status,
        "progress_percent": progress,
    }


def _project_notice_result(value: object, task_id: int) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    list_fields = {
        "invalid_user_ids": ("invalid_user_id_list", "invalid_user_count"),
        "forbidden_user_ids": ("forbidden_user_id_list", "forbidden_user_count"),
        "failed_user_ids": ("failed_user_id_list", "failed_user_count"),
        "read_user_ids": ("read_user_id_list", "read_user_count"),
        "unread_user_ids": ("unread_user_id_list", "unread_user_count"),
    }
    output: dict[str, Any] = {"task_id": task_id}
    truncated = False
    for output_key, (provider_key, count_key) in list_fields.items():
        values = _legacy_list_value(row.get(provider_key))
        projected: list[str] = []
        for item in values:
            if not isinstance(item, str) or not item:
                _raise_response_invalid("dingtalk.work_notification.result.get", row)
            projected.append(_text(item, 512))
        output[output_key] = projected[:50]
        output[count_key] = len(projected)
        truncated = truncated or len(projected) > 50
    department_values = _legacy_list_value(row.get("invalid_dept_id_list"))
    department_ids: list[int] = []
    for item in department_values:
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            _raise_response_invalid("dingtalk.work_notification.result.get", row)
        parsed = _integer(item, 0)
        if parsed <= 0 or (isinstance(item, str) and str(parsed) != item):
            _raise_response_invalid("dingtalk.work_notification.result.get", row)
        department_ids.append(parsed)
    output["invalid_department_ids"] = department_ids[:50]
    output["invalid_department_count"] = len(department_ids)
    output["truncated"] = truncated or len(department_ids) > 50
    return output


def _legacy_list_value(value: object) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("string", "number"):
            nested = value.get(key)
            if isinstance(nested, list):
                return nested
    _raise_response_invalid("dingtalk.work_notification.result.get", {"value": value})
