from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any, Final

from app.shared.secret_redaction import redact_sensitive_text
from app.shared.ones_io_budget import ones_io_budget, ones_io_timeout
from services.ones_mcp_server.errors import invalid_provider_field, invalid_provider_response
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


_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s<>\"']+", re.IGNORECASE)
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_SCALED_INTEGER = re.compile(r"[0-9]{1,18}\Z")
_HOURS_SCALE = 100_000
MESSAGE_PAGE_SIZE = 100
MAX_MESSAGES = 1000
MAX_MESSAGE_PAGES = 50
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_MESSAGE_TEXT = 16_000


class _TimelineText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        elif not self.hidden and tag in {"br", "p", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _safe_timeline_text(
    value: object, *, maximum: int = 500, truncation: list[bool] | None = None
) -> str:
    if not isinstance(value, str):
        return ""
    parser = _TimelineText()
    parser.feed(value[:100_000])
    parser.close()
    plain = unescape("".join(parser.parts))
    plain = _URL.sub("[link omitted]", plain)
    plain = redact_sensitive_text(plain, parse_json=False)
    plain = " ".join(plain.split())
    if truncation is not None and (len(value) > 100_000 or len(plain) > maximum):
        truncation.append(True)
    return plain[:maximum]


def _safe_timeline_id(value: object) -> str:
    return value if isinstance(value, str) and _SAFE_ID.fullmatch(value) else ""


def _hours(value: object) -> str:
    if type(value) is not int or value < 0:
        return ""
    whole, fraction = divmod(value, _HOURS_SCALE)
    return f"{whole}.{fraction:05d}".rstrip("0").rstrip(".")


def _signed_hours(value: int) -> str:
    magnitude = _hours(abs(value))
    return f"{'+' if value >= 0 else '-'}{magnitude}"


def _field_value(ext: dict[str, Any], prefix: str) -> str:
    option = ext.get(f"{prefix}_option")
    if isinstance(option, dict):
        name = _safe_timeline_text(option.get("name"), maximum=200)
        if name:
            return name
    multi = ext.get(f"{prefix}_multi_option")
    if isinstance(multi, list):
        names = [
            _safe_timeline_text(item.get("name"), maximum=100)
            for item in multi[:10]
            if isinstance(item, dict)
        ]
        names = [name for name in names if name]
        if names:
            return "、".join(names) + ("等" if len(multi) > 10 else "")
    value = ext.get(f"{prefix}_value")
    if (
        isinstance(value, str)
        and ext.get("field_type") in {3, 4}
        and _SCALED_INTEGER.fullmatch(value)
    ):
        return _hours(int(value))
    if ext.get("field_type") in {1, 8, 12, 13, 16}:
        return ""  # Unresolved option/user UUIDs are not display labels.
    return _safe_timeline_text(value, maximum=400)


def _system_timeline_text(raw: dict[str, Any]) -> str:
    raw_action = raw.get("action")
    action = raw_action if isinstance(raw_action, str) else ""
    verb = {"add": "新增", "update": "修改", "delete": "删除", "move": "移动", "copy": "复制"}.get(
        action, "操作"
    )
    raw_ext = raw.get("ext")
    ext = raw_ext if isinstance(raw_ext, dict) else {}
    attribute = raw.get("object_attr")
    if attribute == "manhours":
        owner = _safe_timeline_id(ext.get("owner"))
        before = _hours(ext.get("owner_old_total"))
        after = _hours(ext.get("owner_new_total"))
        total = _hours(ext.get("total"))
        parts = [f"{verb}登记工时"]
        if owner:
            parts.append(f"登记人 UUID {owner}")
        if before and after:
            difference = _signed_hours(ext["owner_new_total"] - ext["owner_old_total"])
            parts.append(f"个人累计 {before} → {after} 小时（本次净变化 {difference} 小时）")
        if total:
            parts.append(f"工作项累计 {total} 小时")
        return "；".join(parts)
    if attribute == "field":
        field_name = _safe_timeline_text(ext.get("field_name"), maximum=120) or "未命名属性"
        old = _field_value(ext, "old")
        new = _field_value(ext, "new")
        if old or new:
            return f"{verb}工作项属性「{field_name}」：{old or '空'} → {new or '空'}"
        return f"{verb}工作项属性「{field_name}」"
    if attribute == "attachments":
        attachments = ext.get("attachments")
        names = (
            [
                _safe_timeline_text(item.get("name"), maximum=180)
                for item in attachments[:5]
                if isinstance(item, dict)
            ]
            if isinstance(attachments, list)
            else []
        )
        names = [name for name in names if name]
        return f"{verb}附件" + (f"「{'、'.join(names)}」" if names else "")
    return f"{verb}工作项"


def _timeline_message_text(raw: dict[str, Any], *, path: str, truncation: list[bool]) -> str:
    source = raw.get("text")
    if source is not None and not isinstance(source, str):
        raise invalid_provider_field(f"{path}.text", "字符串或 null", source)
    if raw.get("type") == "system":
        summary = _system_timeline_text(raw)
        original_text = _safe_timeline_text(source, maximum=MAX_MESSAGE_TEXT, truncation=truncation)
        if original_text and original_text not in summary:
            summary = f"{summary}；{original_text}"
        return _safe_timeline_text(summary, maximum=MAX_MESSAGE_TEXT, truncation=truncation)
    text = _safe_timeline_text(source, maximum=MAX_MESSAGE_TEXT, truncation=truncation)
    if text:
        return text
    rich_text = raw.get("rich_text")
    text = _safe_timeline_text(rich_text, maximum=MAX_MESSAGE_TEXT, truncation=truncation)
    if text:
        return text
    resource = raw.get("resource")
    if isinstance(resource, dict):
        name = _safe_timeline_text(resource.get("name"), maximum=180)
        return f"上传附件「{name}」" if name else "上传附件"
    return ""


def enrich_timeline_user_names(output: dict[str, Any], names_by_uuid: dict[str, str]) -> None:
    """Add resolved Team user names without changing the underlying event evidence."""
    names = {
        uuid: safe_name
        for uuid, name in names_by_uuid.items()
        if _safe_timeline_id(uuid) and (safe_name := _safe_timeline_text(name, maximum=200))
    }
    for message in output["messages"]:
        actor_uuid = message.get("actor_uuid")
        actor_name = names.get(actor_uuid)
        if actor_name:
            message["actor"] = {"uuid": actor_uuid, "name": actor_name}
        owner_uuid = message.get("worklog_owner_uuid")
        owner_name = names.get(owner_uuid)
        if owner_name:
            message["worklog_owner"] = {"uuid": owner_uuid, "name": owner_name}
            truncation: list[bool] = []
            message["text"] = _safe_timeline_text(
                message["text"].replace(
                    f"登记人 UUID {owner_uuid}", f"登记人 {owner_name}（{owner_uuid}）"
                ),
                maximum=MAX_MESSAGE_TEXT,
                truncation=truncation,
            )
            message["text_truncated"] = message["text_truncated"] or bool(truncation)
    output["text_truncated_count"] = sum(bool(row["text_truncated"]) for row in output["messages"])
    if output["text_truncated_count"]:
        if "text_limit" not in output["incomplete_reasons"]:
            output["incomplete_reasons"].append("text_limit")
        output["truncated"] = True
        output["complete"] = False


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


def _timeline_result(
    messages: list[dict[str, Any]], *, more: bool, page_count: int, reasons: list[str]
) -> dict[str, Any]:
    text_truncated_count = sum(bool(item["text_truncated"]) for item in messages)
    incomplete = [*reasons, *(["text_limit"] if text_truncated_count else [])]
    return {
        "messages": messages,
        "total": len(messages),
        "total_known": not more,
        "returned": len(messages),
        "cumulative_returned": len(messages),
        "truncated": bool(incomplete),
        "pagination_limit_reached": more,
        "messages_complete": not more,
        "text_truncated_count": text_truncated_count,
        "complete": not incomplete,
        "incomplete_reasons": incomplete,
        "page_count": page_count,
        "newest_at": messages[0]["sent_at"] if messages else None,
        "oldest_at": messages[-1]["sent_at"] if messages else None,
        "untrusted_data": True,
    }


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
        token: str,
        user_id: str,
    ) -> RestExecution:
        path = self.path_template.format(
            team_uuid=team_uuid,
            work_item_uuid=work_item_uuid,
        )
        messages: list[dict[str, Any]] = []
        seen: set[str] = set()
        maximum: int | None = None
        size = 0
        more = False
        with ones_io_budget(90):
            for page_number in range(1, MAX_MESSAGE_PAGES + 1):
                ones_io_timeout(90)
                count = min(MESSAGE_PAGE_SIZE, MAX_MESSAGES - len(messages))
                query = {"count": str(count)}
                if maximum is not None:
                    query["max"] = str(maximum)
                response = http.get_json(
                    path,
                    None,
                    query=query,
                    headers=request_headers(http, token=token, user_id=user_id),
                )
                raw = require_list(response.get("messages"), path="messages")
                has_next = response.get("has_next")
                if type(has_next) is not bool:
                    raise invalid_provider_field("has_next", "布尔值", has_next)
                more = has_next
                if len(raw) > count or bounded_int(response.get("count"), path="count") != len(raw):
                    raise invalid_provider_response("ones_provider_page_size_invalid")
                if more and not raw:
                    raise invalid_provider_response("ones_pagination_cursor_missing")
                for value in raw:
                    item = require_mapping(value, path="messages.item")
                    stamp = bounded_int(item.get("send_time"), minimum=1, path="send_time")
                    uid = _safe_timeline_id(item.get("uuid"))
                    if not uid or uid in seen or (maximum is not None and stamp >= maximum):
                        raise invalid_provider_response("ones_pagination_unstable")
                    seen.add(uid)
                    maximum = stamp
                page = self.parse_response(response, limit=count)["messages"]
                size += len(json.dumps(page, ensure_ascii=False).encode("utf-8"))
                if size > MAX_MESSAGE_BYTES:
                    raise invalid_provider_response("ones_collection_size_exceeded")
                messages.extend(page)
                if not more or len(messages) >= MAX_MESSAGES:
                    break
        reasons = []
        if more:
            reasons.append("item_limit" if len(messages) >= MAX_MESSAGES else "page_limit")
        return RestExecution(
            request={
                "operation": self.code,
                "method": self.method,
                "work_item_uuid": work_item_uuid,
                "page_count": page_number,
                "returned": len(messages),
            },
            response={},
            output=_timeline_result(messages, more=more, page_count=page_number, reasons=reasons),
        )

    @staticmethod
    def parse_response(payload: dict[str, Any], *, limit: int) -> dict[str, Any]:
        raw_messages = require_list(payload.get("messages"), path="messages")
        messages: list[dict[str, Any]] = []
        for index, value in enumerate(raw_messages[:limit]):
            path = f"messages[{index}]"
            raw = require_mapping(value, path=path)
            message_type = bounded_string(raw.get("type"), maximum=80, path=f"{path}.type")
            truncation: list[bool] = []
            message = {
                "uuid": bounded_string(raw.get("uuid"), maximum=128, path=f"{path}.uuid"),
                "type": message_type,
                "sent_at": timestamp_text(
                    raw.get("send_time"), unit="microseconds", path=f"{path}.send_time"
                ),
                "text": _timeline_message_text(raw, path=path, truncation=truncation),
                "text_truncated": bool(truncation),
            }
            actor_uuid = _safe_timeline_id(
                raw.get("subject_id") if message_type == "system" else raw.get("from")
            )
            if actor_uuid and actor_uuid != "BOT":
                message["actor_uuid"] = actor_uuid
            if message_type == "system" and raw.get("object_attr") == "manhours":
                ext = raw.get("ext")
                if isinstance(ext, dict):
                    owner_uuid = _safe_timeline_id(ext.get("owner"))
                    if owner_uuid:
                        message["worklog_owner_uuid"] = owner_uuid
            messages.append(message)
        total_value = payload.get("count", len(raw_messages))
        total = bounded_int(total_value, path="count")
        has_next = payload.get("has_next", False)
        if type(has_next) is not bool:
            raise invalid_provider_field("has_next", "布尔值", has_next)
        more = has_next or total > len(messages) or len(raw_messages) > limit
        return _timeline_result(
            messages, more=more, page_count=1, reasons=["item_limit"] if more else []
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
