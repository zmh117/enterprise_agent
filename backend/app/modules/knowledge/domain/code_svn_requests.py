"""Canonical structured history requests; no command or executable is caller-controlled."""

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.knowledge.domain.code_answers import (
    bounded_json,
    code_path,
    path_in_scope,
    svn_revision,
    utc_time,
)
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError


def history_request(kind: str, value: Any, *, upper: int, paths: list[str]) -> dict[str, Any]:
    bounded_json(value, expected=dict, limit=4096)
    fields = {
        "info": {"target", "path", "revision"},
        "log": {"path", "selector", "peg_revision", "limit", "include_message", "before_revision"},
        "diff": {"path", "selector", "peg_revision", "mode", "offset"},
        "blame": {"path", "revision", "peg_revision", "start_line", "end_line"},
    }
    if kind not in fields or set(value) - fields[kind] or "path" not in value:
        raise CodeKnowledgeError("CODE_HISTORY_REQUEST_INVALID")
    path = code_path(value["path"], root=kind != "blame")
    projected_parent = kind in {"log", "diff", "info"} and value.get("mode", "summary") == "summary"
    if not path_in_scope(path, paths) and not (
        projected_parent and any(path == "" or p.startswith(path + "/") for p in paths)
    ):
        raise CodeKnowledgeError("CODE_HISTORY_PATH_DENIED")

    def revision(n: Any) -> int:
        number = svn_revision(n)
        if number > upper:
            raise CodeKnowledgeError("CODE_HISTORY_VERSION_DENIED")
        return number

    if kind == "info":
        selected = revision(value.get("revision"))
        target = value.get("target")
        if target not in {"repository", "checkout"} or (
            target == "checkout" and (path or selected != upper)
        ):
            raise CodeKnowledgeError("CODE_HISTORY_REQUEST_INVALID")
        return {"path": path, "target": target, "revision": selected, "peg": selected}

    peg = revision(value.get("peg_revision", upper))
    result: dict[str, Any] = {"path": path, "peg": peg}
    if kind == "blame":
        start, end = value.get("start_line"), value.get("end_line")
        if type(start) is not int or type(end) is not int or not 1 <= start <= end < start + 400:
            raise CodeKnowledgeError("CODE_HISTORY_LINES_INVALID")
        return {
            **result,
            "revision": revision(value.get("revision")),
            "start_line": start,
            "end_line": end,
        }
    selector = value.get("selector")
    if not isinstance(selector, dict):
        raise CodeKnowledgeError("CODE_HISTORY_SELECTOR_INVALID")
    if kind == "log":
        result.update(_log_selector(selector, revision, upper))
        limit = value.get("limit", 100)
        include = value.get("include_message", False)
        if type(limit) is not int or not 1 <= limit <= 200 or type(include) is not bool:
            raise CodeKnowledgeError("CODE_HISTORY_REQUEST_INVALID")
        result.update(limit=limit, include_message=include)
        if "before_revision" in value:
            before = revision(value["before_revision"])
            if not result["start"] <= before <= result["end"]:
                raise CodeKnowledgeError("CODE_HISTORY_CURSOR_INVALID")
            result["before"] = before
        return result
    return _diff_request(selector, revision, value, result)


def _diff_request(
    selector: dict[str, Any], revision: Any, value: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    selected = selector.get("kind")
    path = result["path"]
    if selected == "change" and set(selector) == {"kind", "change_revision"}:
        end = revision(selector["change_revision"])
        if end == 0:
            raise CodeKnowledgeError("CODE_HISTORY_RANGE_INVALID")
        start = end - 1
    elif selected == "range" and set(selector) == {"kind", "from_revision", "to_revision"}:
        start, end = revision(selector["from_revision"]), revision(selector["to_revision"])
    else:
        raise CodeKnowledgeError("CODE_HISTORY_SELECTOR_INVALID")
    mode, offset = value.get("mode", "summary"), value.get("offset", 0)
    if mode not in {"summary", "text"} or type(offset) is not int or not 0 <= offset <= 10000:
        raise CodeKnowledgeError("CODE_HISTORY_DIFF_INVALID")
    if mode == "text" and (not path or offset):
        raise CodeKnowledgeError("CODE_HISTORY_SINGLE_FILE_REQUIRED")
    return {**result, "start": start, "end": end, "mode": mode, "offset": offset}


def _log_selector(selector: dict[str, Any], revision: Any, upper: int) -> dict[str, Any]:
    kind = selector.get("kind")
    if kind == "latest" and set(selector) == {"kind"}:
        return {"start": 0, "end": upper}
    if kind == "revision" and set(selector) == {"kind", "revision"}:
        n = revision(selector["revision"])
        return {"start": n, "end": n}
    if kind == "revision_range" and set(selector) == {"kind", "from_revision", "to_revision"}:
        start, end = revision(selector["from_revision"]), revision(selector["to_revision"])
        if start > end:
            raise CodeKnowledgeError("CODE_HISTORY_RANGE_INVALID")
        return {"start": start, "end": end}
    if kind == "time_range" and set(selector) == {"kind", "start_time", "end_time", "timezone"}:
        start, end = time_range(selector["start_time"], selector["end_time"], selector["timezone"])
        return {"start": 0, "end": upper, "start_time": start, "end_time": end}
    raise CodeKnowledgeError("CODE_HISTORY_SELECTOR_INVALID")


def time_range(start: Any, end: Any, zone: Any) -> tuple[str, str]:
    try:
        if not all(isinstance(v, str) and 1 <= len(v) <= 80 for v in (start, end, zone)):
            raise ValueError
        tz = ZoneInfo(zone)
        if len(start) == len(end) == 10:
            left = datetime.combine(date.fromisoformat(start), time.min, tz)
            right = datetime.combine(date.fromisoformat(end) + timedelta(days=1), time.min, tz)
        else:
            left, right = utc_time(start), utc_time(end)
        if left >= right:
            raise ValueError
        return utc_time(left).isoformat(), utc_time(right).isoformat()
    except (ValueError, KeyError, TypeError):
        raise CodeKnowledgeError("CODE_HISTORY_TIME_INVALID") from None
