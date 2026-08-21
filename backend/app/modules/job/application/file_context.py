from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import re
import unicodedata
from typing import Literal
from zoneinfo import ZoneInfo

FileCapability = Literal["METADATA", "ORIGINAL", "READABLE_CONTENT"]
BindReason = Literal[
    "CURRENT_MESSAGE",
    "EXPLICIT_REFERENCE",
    "QUOTE",
    "FILENAME",
    "DEIXIS",
    "TIME_WINDOW",
]
GateAction = Literal["enqueue_job", "wait_source", "system_notice"]

SHANGHAI = ZoneInfo("Asia/Shanghai")
TIME_WINDOW_METADATA_LIMIT = 20

GENERIC_DEIXIS_PATTERNS: tuple[str, ...] = (
    "这个文件",
    "这份文件",
    "该文件",
    "刚才那个文件",
    "刚才那个",
    "刚才的文件",
    "刚才那份",
    "刚才上传的文件",
    "上面的附件",
    "这个附件",
    "这份附件",
    "这个表",
    "这张表",
    "该文档",
    "这份文档",
    "这个文档",
)

IMAGE_DEIXIS_PATTERNS: tuple[str, ...] = (
    "这张图",
    "这张图片",
    "那张图",
    "那张图片",
    "这个图",
    "这个图片",
    "发的图片",
    "发的图",
    "传来的图片",
    "上传的图片",
    "刚才的图片",
    "刚才那张",
    "图片什么内容",
    "图片的内容",
    "图片里",
)

DEIXIS_PATTERNS: tuple[str, ...] = GENERIC_DEIXIS_PATTERNS + IMAGE_DEIXIS_PATTERNS
IMAGE_NAME_SUFFIXES: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")

PLURAL_DEIXIS_PATTERNS: tuple[str, ...] = (
    "这些文件",
    "这几个文件",
    "那几个文件",
    "几个文件",
    "多份文件",
    "这些附件",
    "刚才那些",
)

RECENT_EXPLICIT_COUNT_PATTERN = re.compile(
    r"刚才(?:发送|上传|发|传)(?:的)?(?P<count>[一二两三四五六七八九十\d]+)"
    r"(?:个|份|张)?(?:文件|附件|图片|文档)"
)
_CHINESE_NUMERALS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

FILE_REFERRING_TOKENS: tuple[str, ...] = (
    "文件",
    "附件",
    "图片",
    "文档",
    "材料",
    "表格",
    "xlsx",
    "docx",
    "pptx",
    "pdf",
    ".txt",
    ".md",
    ".log",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    "图",
    "表",
)
GENERIC_FILE_REFERRING_TOKENS: tuple[str, ...] = (
    "文件",
    "附件",
    "文档",
    "材料",
    "表格",
    "xlsx",
    "docx",
    "pptx",
    "pdf",
    ".txt",
    ".md",
    ".log",
)
IMAGE_FILE_REFERRING_TOKENS: tuple[str, ...] = (
    "图片",
    "的图",
    "张图",
    "个图",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
)

PREVIOUS_WEEK_TOKENS: tuple[str, ...] = ("上个星期", "上星期", "上周")
CURRENT_WEEK_TOKENS: tuple[str, ...] = ("这个星期", "这一周", "这周", "本周")
PREVIOUS_MONTH_TOKENS: tuple[str, ...] = ("上个月", "上月")
TODAY_TOKENS: tuple[str, ...] = ("今天", "今日")
YESTERDAY_TOKENS: tuple[str, ...] = ("昨天", "昨日")

DATE_RANGE_CN = re.compile(
    r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]\s*(?:到|至|~|—|-)\s*(?:(\d{1,2})月)?(\d{1,2})[日号]"
)
DATE_RANGE_ISO = re.compile(
    r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s*(?:到|至|~|—)\s*(?:(\d{4})[-/])?(\d{1,2})[-/](\d{1,2})"
)
SINGLE_DATE_CN = re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]")
SINGLE_DATE_ISO = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")

METADATA_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"叫什么",
        r"文件名",
        r"什么格式",
        r"什么类型",
        r"多大",
        r"多少\s*(mb|mi?b|kb)",
        r"上传时间",
        r"何时上传",
        r"什么时候(传|上传)",
        r"哪些文件",
        r"哪些附件",
        r"发了哪些",
        r"传了哪些",
        r"有哪些(文件|附件|图)",
        r"有什么(文件|附件)",
        r"file\s*name",
        r"how\s+big",
        r"what\s+format",
    )
)

ORIGINAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"原文件",
        r"原件",
        r"转发原",
        r"下载原",
        r"把.{0,12}(原文件|原件|原pdf|原docx).{0,12}(发|给)",
        r"send\s+(me\s+)?the\s+original",
        r"forward\s+the\s+original",
        r"download\s+the\s+original",
    )
)

SOURCE_TERMINAL = frozenset({"READY", "REJECTED", "FAILED", "stored_not_interpreted"})
READABLE_READY = frozenset({"AVAILABLE", "PARTIAL", "NOT_REQUIRED"})
READABLE_FAILED = frozenset({"NO_TEXT", "UNAVAILABLE"})
KNOWN_BIND_REASONS = {
    "CURRENT_MESSAGE",
    "EXPLICIT_REFERENCE",
    "QUOTE",
    "FILENAME",
    "DEIXIS",
    "TIME_WINDOW",
}


@dataclass(frozen=True, slots=True)
class TimeWindow:
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class TimeWindowParse:
    window: TimeWindow | None = None
    matched: bool = False
    invalid: bool = False


@dataclass(frozen=True, slots=True)
class WorkspaceFileCandidate:
    file_id: str
    version_id: str
    display_name: str
    attachment_id: str = ""
    message_external_id: str = ""
    source_status: str = ""
    readability_status: str = "NOT_REQUIRED"
    source_ready_at: str | None = None
    source_received_at: str | None = None
    content_available: bool = True


@dataclass(frozen=True, slots=True)
class CurrentMessageAttachment:
    file_name: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class FileDependency:
    required_capability: FileCapability
    reason: BindReason
    file_id: str = ""
    version_id: str = ""
    attachment_id: str = ""
    display_name: str = ""
    source_status: str = ""
    readability_status: str = "NOT_REQUIRED"
    source_received_at: str | None = None
    content_available: bool = True


@dataclass(frozen=True, slots=True)
class ResolverDecision:
    dependencies: tuple[FileDependency, ...]
    ambiguous: bool = False
    clarification_names: tuple[str, ...] = ()
    quote_unresolved: bool = False
    notice_kind: str = ""


@dataclass(frozen=True, slots=True)
class GateDecision:
    action: GateAction
    reason_code: str
    notice_kind: str = ""
    dependencies: tuple[FileDependency, ...] = ()


def resolver_now() -> datetime:
    return datetime.now(SHANGHAI)


def normalize_display_name(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold().strip()


def infer_capability(text: str) -> FileCapability:
    if any(pattern.search(text) for pattern in ORIGINAL_PATTERNS):
        return "ORIGINAL"
    if any(pattern.search(text) for pattern in METADATA_PATTERNS):
        return "METADATA"
    return "READABLE_CONTENT"


def has_generic_deixis(text: str) -> bool:
    return any(token in text for token in GENERIC_DEIXIS_PATTERNS)


def has_image_deixis(text: str) -> bool:
    return any(token in text for token in IMAGE_DEIXIS_PATTERNS)


def has_deixis(text: str) -> bool:
    return has_generic_deixis(text) or has_image_deixis(text)


def has_plural_deixis(text: str) -> bool:
    return any(token in text for token in PLURAL_DEIXIS_PATTERNS)


def explicit_recent_file_count(text: str) -> int | None:
    matched = RECENT_EXPLICIT_COUNT_PATTERN.search(text)
    if matched is None:
        return None
    raw = matched.group("count")
    if raw.isdigit():
        value = int(raw)
    elif raw in _CHINESE_NUMERALS:
        value = _CHINESE_NUMERALS[raw]
    elif raw.startswith("十") and raw[1:] in _CHINESE_NUMERALS:
        value = 10 + _CHINESE_NUMERALS[raw[1:]]
    else:
        return None
    return value if 1 <= value <= 20 else None


def has_file_referring_token(text: str) -> bool:
    return any(token in text for token in FILE_REFERRING_TOKENS)


def is_image_only_file_query(text: str) -> bool:
    has_image = any(token in text for token in IMAGE_FILE_REFERRING_TOKENS) or (
        "图" in text and "文件" not in text and "附件" not in text and "文档" not in text
    )
    has_generic = any(token in text for token in GENERIC_FILE_REFERRING_TOKENS)
    return has_image and not has_generic


def parse_time_window(text: str, *, now: datetime | None = None) -> TimeWindow | None:
    return _parse_time_window(text, now=now).window


def _parse_time_window(text: str, *, now: datetime | None = None) -> TimeWindowParse:
    moment = (now or resolver_now()).astimezone(SHANGHAI)
    if any(token in text for token in PREVIOUS_WEEK_TOKENS):
        current = _week_start(moment)
        return TimeWindowParse(
            window=TimeWindow(start=current - timedelta(days=7), end=current),
            matched=True,
        )
    if any(token in text for token in CURRENT_WEEK_TOKENS):
        current = _week_start(moment)
        return TimeWindowParse(
            window=TimeWindow(start=current, end=current + timedelta(days=7)),
            matched=True,
        )
    if any(token in text for token in PREVIOUS_MONTH_TOKENS):
        first_this_month = datetime(moment.year, moment.month, 1, tzinfo=SHANGHAI)
        last_month = first_this_month - timedelta(days=1)
        start = datetime(last_month.year, last_month.month, 1, tzinfo=SHANGHAI)
        return TimeWindowParse(
            window=TimeWindow(start=start, end=first_this_month),
            matched=True,
        )
    if any(token in text for token in TODAY_TOKENS):
        return TimeWindowParse(window=_day_window(moment.date()), matched=True)
    if any(token in text for token in YESTERDAY_TOKENS):
        return TimeWindowParse(
            window=_day_window(moment.date() - timedelta(days=1)), matched=True
        )
    ranged = _parse_date_range(text, moment)
    if ranged.matched:
        return ranged
    return _parse_single_date(text, moment)


def resolve_file_context(
    *,
    text: str,
    current_attachments: tuple[CurrentMessageAttachment, ...] = (),
    explicit_references: tuple[tuple[str, str], ...] = (),
    quoted_external_message_id: str = "",
    candidates: tuple[WorkspaceFileCandidate, ...] = (),
    retained_candidates: tuple[WorkspaceFileCandidate, ...] = (),
    now: datetime | None = None,
) -> ResolverDecision:
    capability = infer_capability(text)
    if current_attachments:
        return ResolverDecision(
            dependencies=tuple(
                FileDependency(
                    required_capability=capability,
                    reason="CURRENT_MESSAGE",
                    display_name=item.file_name,
                    attachment_id=f"current:{item.ordinal}",
                    source_status="PENDING",
                    readability_status="PENDING",
                )
                for item in current_attachments
            )
        )

    if explicit_references:
        bound: list[FileDependency] = []
        by_identity = {
            (item.file_id, item.version_id): item for item in candidates if item.file_id
        }
        for file_id, version_id in explicit_references:
            match = by_identity.get((file_id, version_id))
            if match is None:
                bound.append(
                    FileDependency(
                        file_id=file_id,
                        version_id=version_id,
                        required_capability=capability,
                        reason="EXPLICIT_REFERENCE",
                    )
                )
                continue
            bound.append(_dependency_from_candidate(match, capability, "EXPLICIT_REFERENCE"))
        return ResolverDecision(dependencies=tuple(bound))

    skip_deixis = False
    if quoted_external_message_id:
        quoted = tuple(
            item
            for item in candidates
            if item.message_external_id == quoted_external_message_id
        )
        if quoted:
            return ResolverDecision(
                dependencies=tuple(
                    _dependency_from_candidate(item, capability, "QUOTE") for item in quoted
                )
            )
        skip_deixis = True

    filename_hits = _unique_filename_hits(text, candidates)
    if filename_hits == "ambiguous":
        names = tuple(
            sorted({item.display_name for item in candidates if _name_mentioned(text, item)})
        )
        return ResolverDecision(
            dependencies=(),
            ambiguous=True,
            clarification_names=names,
        )
    if filename_hits:
        return ResolverDecision(
            dependencies=tuple(
                _dependency_from_candidate(item, capability, "FILENAME")
                for item in filename_hits
            )
        )

    parsed_window = _parse_time_window(text, now=now)
    if parsed_window.invalid and has_file_referring_token(text) and not skip_deixis:
        return ResolverDecision(dependencies=(), notice_kind="invalid_time_window")
    window = parsed_window.window
    if window is not None and has_file_referring_token(text) and not skip_deixis:
        return _resolve_time_window(
            text=text,
            capability=capability,
            window=window,
            candidates=candidates,
            retained_candidates=retained_candidates,
        )

    if skip_deixis:
        return ResolverDecision(dependencies=(), quote_unresolved=True)
    recent_count = explicit_recent_file_count(text)
    if recent_count is not None:
        unique: dict[tuple[str, str], WorkspaceFileCandidate] = {}
        for item in candidates:
            if item.source_status not in SOURCE_TERMINAL:
                continue
            identity = (item.file_id, item.version_id)
            previous = unique.get(identity)
            if previous is None or (not previous.attachment_id and item.attachment_id):
                unique[identity] = item
        pool = list(unique.values())
        if len(pool) < recent_count:
            return ResolverDecision(
                dependencies=(),
                ambiguous=True,
                clarification_names=tuple(sorted({item.display_name for item in pool})),
            )
        selected = sorted(
            pool,
            key=lambda item: (
                item.source_received_at or "",
                item.source_ready_at or "",
                item.display_name,
                item.file_id,
            ),
            reverse=True,
        )[:recent_count]
        return ResolverDecision(
            dependencies=tuple(
                _dependency_from_candidate(item, capability, "DEIXIS")
                for item in reversed(selected)
            )
        )
    if has_plural_deixis(text):
        pool = [item for item in candidates if item.source_status in SOURCE_TERMINAL]
        if not pool:
            pool = list(candidates)
        if len(pool) > 1:
            return ResolverDecision(
                dependencies=(),
                ambiguous=True,
                clarification_names=tuple(sorted({item.display_name for item in pool})),
            )
    if not has_deixis(text) and not has_plural_deixis(text):
        return ResolverDecision(dependencies=())

    pool = _deixis_candidate_pool(text, candidates)
    if not pool:
        return ResolverDecision(dependencies=())
    ready = [item for item in pool if item.source_status in SOURCE_TERMINAL]
    if not ready:
        ready = list(pool)
    if len(ready) == 1:
        return ResolverDecision(
            dependencies=(_dependency_from_candidate(ready[0], capability, "DEIXIS"),)
        )
    latest = max(
        (item.source_ready_at or "" for item in ready),
        default="",
    )
    winners = [
        item
        for item in ready
        if (item.source_ready_at or "") == latest and latest
    ]
    if len(winners) != 1:
        return ResolverDecision(
            dependencies=(),
            ambiguous=True,
            clarification_names=tuple(sorted({item.display_name for item in ready})),
        )
    return ResolverDecision(
        dependencies=(_dependency_from_candidate(winners[0], capability, "DEIXIS"),)
    )


def evaluate_file_gate(decision: ResolverDecision) -> GateDecision:
    if decision.notice_kind == "invalid_time_window":
        return GateDecision(
            action="system_notice",
            reason_code="invalid_time_window",
            notice_kind="invalid_time_window",
            dependencies=(),
        )
    if decision.notice_kind == "time_window_empty":
        return GateDecision(
            action="system_notice",
            reason_code="time_window_empty",
            notice_kind="time_window_empty",
            dependencies=(),
        )
    if decision.notice_kind == "time_window_too_many":
        return GateDecision(
            action="system_notice",
            reason_code="time_window_too_many",
            notice_kind="time_window_too_many",
            dependencies=(),
        )
    if decision.notice_kind == "content_unavailable":
        return GateDecision(
            action="system_notice",
            reason_code="file_content_unavailable",
            notice_kind="content_unavailable",
            dependencies=decision.dependencies,
        )
    if decision.ambiguous:
        notice_kind = decision.notice_kind or "ambiguous"
        reason_code = (
            "time_window_ambiguous"
            if notice_kind == "time_window_ambiguous"
            else "file_binding_ambiguous"
        )
        return GateDecision(
            action="system_notice",
            reason_code=reason_code,
            notice_kind=notice_kind,
            dependencies=(),
        )
    if not decision.dependencies:
        return GateDecision(action="enqueue_job", reason_code="no_file_dependency")

    waiting_source: list[FileDependency] = []
    not_ready: list[FileDependency] = []
    failed: list[FileDependency] = []
    for item in decision.dependencies:
        if _source_pending(item):
            waiting_source.append(item)
            continue
        if item.source_status in {"REJECTED", "FAILED"}:
            failed.append(item)
            continue
        if item.required_capability in {"METADATA", "ORIGINAL"}:
            continue
        if item.readability_status in READABLE_FAILED:
            failed.append(item)
        elif item.readability_status not in READABLE_READY:
            not_ready.append(item)

    if waiting_source:
        return GateDecision(
            action="wait_source",
            reason_code="file_source_pending",
            dependencies=decision.dependencies,
        )
    if failed:
        return GateDecision(
            action="system_notice",
            reason_code="file_processing_failed",
            notice_kind="failed",
            dependencies=tuple(failed),
        )
    if not_ready:
        return GateDecision(
            action="system_notice",
            reason_code="file_readable_content_not_ready",
            notice_kind="pending",
            dependencies=tuple(not_ready),
        )
    return GateDecision(
        action="enqueue_job",
        reason_code="file_capability_ready",
        dependencies=decision.dependencies,
    )


def system_notice_markdown(
    *,
    notice_kind: str,
    display_names: tuple[str, ...],
) -> tuple[str, str]:
    names = "、".join(_safe_file_name(name) for name in display_names if name) or "该文件"
    if notice_kind == "pending":
        return (
            "文件尚未可阅读",
            f"《{names}》原件已保存，正在生成可读内容，当前还不能基于该文件回答。其他问题可以继续发送。",
        )
    if notice_kind == "failed":
        return (
            "文件尚未可阅读",
            f"《{names}》原件已保存，但可读内容生成失败。请更换文件或稍后再试。其他问题可以继续发送。",
        )
    if notice_kind == "ambiguous":
        listed = "、".join(_safe_file_name(name) for name in display_names) or "多份文件"
        return (
            "请指明要使用的文件",
            f"工作区里有多份可能相关的文件（{listed}）。请回复具体文件、引用那条文件消息，或写出完整文件名。",
        )
    if notice_kind == "time_window_ambiguous":
        listed = "、".join(_safe_file_name(name) for name in display_names) or "多份文件"
        return (
            "请指明要使用的文件",
            f"该时段有多份仍可访问的文件（{listed}）。请引用那条文件消息，或写出完整文件名。",
        )
    if notice_kind == "time_window_too_many":
        return (
            "请缩小文件范围",
            "该时段仍可访问的文件超过 20 个。请缩小到某一天，或写出完整文件名。",
        )
    if notice_kind == "time_window_empty":
        return (
            "该时段没有仍可访问的文件",
            "该时段没有仍可访问的文件。其他问题可以继续发送。",
        )
    if notice_kind == "invalid_time_window":
        return (
            "请提供有效日期",
            "指定的日期或日期范围无效。请按实际日历日期重新描述文件时间范围。",
        )
    if notice_kind == "content_unavailable":
        return (
            "文件内容已不可用",
            f"《{names}》内容已按保留策略清理，请重新发送文件。其他问题可以继续发送。",
        )
    if notice_kind == "ready":
        return (
            "文件已可继续提问",
            f"《{names}》可读内容已经生成，现在可以继续提问。",
        )
    return ("文件尚未可阅读", "当前还不能基于该文件回答。其他问题可以继续发送。")


def _resolve_time_window(
    *,
    text: str,
    capability: FileCapability,
    window: TimeWindow,
    candidates: tuple[WorkspaceFileCandidate, ...],
    retained_candidates: tuple[WorkspaceFileCandidate, ...],
) -> ResolverDecision:
    pool = _window_candidates(window, candidates, retained_candidates)
    if is_image_only_file_query(text):
        pool = [item for item in pool if _is_image_candidate(item)]
    if not pool:
        return ResolverDecision(
            dependencies=(),
            notice_kind="time_window_empty",
        )
    if len(pool) > TIME_WINDOW_METADATA_LIMIT:
        return ResolverDecision(
            dependencies=(),
            notice_kind="time_window_too_many",
            clarification_names=tuple(sorted({item.display_name for item in pool[:20]})),
        )
    return ResolverDecision(
        dependencies=tuple(
            _dependency_from_candidate(item, "METADATA", "TIME_WINDOW") for item in pool
        )
    )


def _window_candidates(
    window: TimeWindow,
    candidates: tuple[WorkspaceFileCandidate, ...],
    retained_candidates: tuple[WorkspaceFileCandidate, ...],
) -> list[WorkspaceFileCandidate]:
    merged: dict[tuple[str, str], WorkspaceFileCandidate] = {}
    for item in (*retained_candidates, *candidates):
        if not item.file_id or not item.version_id:
            continue
        if not _received_at_in_window(item.source_received_at, window):
            continue
        identity = (item.file_id, item.version_id)
        previous = merged.get(identity)
        if previous is None or (not previous.attachment_id and item.attachment_id):
            merged[identity] = item
    return list(merged.values())


def _received_at_in_window(value: str | None, window: TimeWindow) -> bool:
    parsed = _parse_instant(value)
    if parsed is None:
        return False
    return window.start <= parsed < window.end


def _parse_instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _week_start(moment: datetime) -> datetime:
    local = moment.astimezone(SHANGHAI)
    monday = local.date() - timedelta(days=local.weekday())
    return datetime.combine(monday, time.min, tzinfo=SHANGHAI)


def _day_window(day: date) -> TimeWindow:
    start = datetime.combine(day, time.min, tzinfo=SHANGHAI)
    return TimeWindow(start=start, end=start + timedelta(days=1))


def _parse_date_range(text: str, moment: datetime) -> TimeWindowParse:
    iso = DATE_RANGE_ISO.search(text)
    if iso is not None:
        start_year, start_month, start_day, end_year, end_month, end_day = (
            _optional_int(iso.group(1)),
            int(iso.group(2)),
            int(iso.group(3)),
            _optional_int(iso.group(4)),
            int(iso.group(5)),
            int(iso.group(6)),
        )
        start = _resolve_date(start_year, start_month, start_day, moment)
        if start is None:
            return TimeWindowParse(matched=True, invalid=True)
        end = _resolve_date(end_year or start.year, end_month, end_day, moment, year_locked=True)
        window = _inclusive_days(start, end) if end is not None else None
        return TimeWindowParse(window=window, matched=True, invalid=window is None)
    match = DATE_RANGE_CN.search(text)
    if match is None:
        return TimeWindowParse()
    year = _optional_int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))
    range_end_month = _optional_int(match.group(4))
    range_end_day = int(match.group(5))
    start = _resolve_date(year, month, day, moment)
    if start is None:
        return TimeWindowParse(matched=True, invalid=True)
    end = _resolve_date(
        year or start.year,
        range_end_month or month,
        range_end_day,
        moment,
        year_locked=True,
    )
    window = _inclusive_days(start, end) if end is not None else None
    return TimeWindowParse(window=window, matched=True, invalid=window is None)


def _parse_single_date(text: str, moment: datetime) -> TimeWindowParse:
    iso = SINGLE_DATE_ISO.search(text)
    if iso is not None:
        day = _resolve_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)), moment)
        return TimeWindowParse(
            window=_day_window(day) if day is not None else None,
            matched=True,
            invalid=day is None,
        )
    match = SINGLE_DATE_CN.search(text)
    if match is None:
        return TimeWindowParse()
    day = _resolve_date(
        _optional_int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        moment,
    )
    return TimeWindowParse(
        window=_day_window(day) if day is not None else None,
        matched=True,
        invalid=day is None,
    )


def _inclusive_days(start: date, end: date) -> TimeWindow | None:
    if end < start:
        return None
    first = datetime.combine(start, time.min, tzinfo=SHANGHAI)
    last = datetime.combine(end, time.min, tzinfo=SHANGHAI) + timedelta(days=1)
    return TimeWindow(start=first, end=last)


def _resolve_date(
    year: int | None,
    month: int,
    day: int,
    moment: datetime,
    *,
    year_locked: bool = False,
) -> date | None:
    try:
        if year is not None:
            return datetime(year, month, day, tzinfo=SHANGHAI).date()
        candidate = datetime(moment.year, month, day, tzinfo=SHANGHAI)
    except ValueError:
        return None
    if year_locked:
        return candidate.date()
    if candidate > moment:
        try:
            return datetime(moment.year - 1, month, day, tzinfo=SHANGHAI).date()
        except ValueError:
            return candidate.date()
    return candidate.date()


def _optional_int(value: str | None) -> int | None:
    if not value:
        return None
    return int(value)


def _dependency_from_candidate(
    item: WorkspaceFileCandidate,
    capability: FileCapability,
    reason: BindReason,
) -> FileDependency:
    return FileDependency(
        file_id=item.file_id,
        version_id=item.version_id,
        attachment_id=item.attachment_id,
        display_name=item.display_name,
        required_capability=capability,
        reason=reason,
        source_status=item.source_status,
        readability_status=item.readability_status,
        source_received_at=item.source_received_at,
        content_available=item.content_available,
    )


def _deixis_candidate_pool(
    text: str,
    candidates: tuple[WorkspaceFileCandidate, ...],
) -> list[WorkspaceFileCandidate]:
    if has_image_deixis(text):
        return [item for item in candidates if _is_image_candidate(item)]
    return list(candidates)


def _is_image_candidate(item: WorkspaceFileCandidate) -> bool:
    name = normalize_display_name(item.display_name)
    return name.endswith(IMAGE_NAME_SUFFIXES)


def _unique_filename_hits(
    text: str,
    candidates: tuple[WorkspaceFileCandidate, ...],
) -> tuple[WorkspaceFileCandidate, ...] | Literal["ambiguous"] | tuple[()]:
    mentioned = [item for item in candidates if _name_mentioned(text, item)]
    if not mentioned:
        return ()
    unique: dict[tuple[str, str], WorkspaceFileCandidate] = {}
    for item in mentioned:
        key = (item.file_id, item.version_id or item.attachment_id)
        previous = unique.get(key)
        if previous is None or (not previous.attachment_id and item.attachment_id):
            unique[key] = item
    collapsed = tuple(unique.values())
    identities = {(item.file_id, item.version_id) for item in collapsed}
    names = {normalize_display_name(item.display_name) for item in collapsed}
    if len(identities) > 1 and len(names) == 1:
        return "ambiguous"
    return collapsed


def _name_mentioned(text: str, item: WorkspaceFileCandidate) -> bool:
    needle = normalize_display_name(item.display_name)
    if not needle or "." not in needle:
        return False
    return needle in normalize_display_name(text)


def _safe_file_name(value: str) -> str:
    cleaned = re.sub(r"[\r\n`]+", " ", value).strip()
    return cleaned[:80] or "文件"


def _source_pending(item: FileDependency) -> bool:
    if item.source_status in {"PENDING", "DOWNLOADING", "EXTRACTING"}:
        return True
    return item.reason == "CURRENT_MESSAGE" and item.source_status not in SOURCE_TERMINAL


def file_dependency_payload(item: FileDependency) -> dict[str, str]:
    return {
        "file_id": item.file_id,
        "version_id": item.version_id,
        "attachment_id": item.attachment_id,
        "display_name": item.display_name,
        "required_capability": item.required_capability,
        "reason": item.reason,
        "source_status": item.source_status,
        "readability_status": item.readability_status,
        "source_received_at": item.source_received_at or "",
        "content_available": "true" if item.content_available else "false",
    }


def file_dependency_from_payload(value: dict[str, object]) -> FileDependency:
    capability = str(value.get("required_capability") or "READABLE_CONTENT")
    reason = str(value.get("reason") or "FILENAME")
    if capability not in {"METADATA", "ORIGINAL", "READABLE_CONTENT"}:
        capability = "READABLE_CONTENT"
    if reason not in KNOWN_BIND_REASONS:
        reason = "FILENAME"
    content_available = str(value.get("content_available") or "true").lower() != "false"
    received = str(value.get("source_received_at") or "")
    return FileDependency(
        required_capability=capability,  # type: ignore[arg-type]
        reason=reason,  # type: ignore[arg-type]
        file_id=str(value.get("file_id") or ""),
        version_id=str(value.get("version_id") or ""),
        attachment_id=str(value.get("attachment_id") or ""),
        display_name=str(value.get("display_name") or ""),
        source_status=str(value.get("source_status") or ""),
        readability_status=str(value.get("readability_status") or "NOT_REQUIRED"),
        source_received_at=received or None,
        content_available=content_available,
    )
