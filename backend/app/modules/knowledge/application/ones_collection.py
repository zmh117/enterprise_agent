"""按创建日完整枚举 ONES；完成的日期才可推进持久水位。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from time import sleep
from typing import Any, Protocol, TypeVar

from app.modules.knowledge.domain.normalization import ExportValidationError, identifier


PAGE_SIZE = 200
WINDOW_LIMIT = 1000
MAX_DOCUMENTS = 200_000
DETAIL_WORKERS = 16
RETRY_DELAYS = (0.5, 1.5)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CollectionPage:
    items: tuple[dict[str, Any], ...]
    total: int
    has_next: bool
    end_cursor: str | None
    count: int | None = None


class OnesCollectionProvider(Protocol):
    def catalog(
        self, issue_type_ids: tuple[str, ...], *, check_active: Callable[[], None]
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str]]: ...

    def count(self, issue_type_id: str, first: date, last: date) -> int: ...

    def page(
        self, issue_type_id: str, first: date, last: date, *, after: str | None
    ) -> CollectionPage: ...

    def detail(self, work_item_id: str) -> dict[str, Any]: ...


PageCommit = Callable[
    [str, tuple[tuple[dict[str, Any] | None, dict[str, Any]], ...], dict[str, Any]], None
]


def _validate_scope(
    issue_types: Mapping[str, tuple[str, ...]],
    project_ids: frozenset[str],
    first: date,
    last: date,
) -> None:
    if (
        first > last
        or not project_ids
        or set(issue_types) != {"defect", "ticket", "requirement"}
        or any(not ids for ids in issue_types.values())
    ):
        raise ExportValidationError("knowledge_collection_scope_invalid")
    for project_id in project_ids:
        identifier(project_id)
    typed_ids: set[str] = set()
    for kind, ids in issue_types.items():
        for issue_type_id in ids:
            identifier(issue_type_id)
            if issue_type_id in typed_ids:
                raise ExportValidationError("knowledge_collection_scope_invalid")
            typed_ids.add(issue_type_id)


def _request_with_retry(request: Callable[[], T]) -> T:
    for delay in (*RETRY_DELAYS, None):
        try:
            return request()
        except Exception as exc:
            if delay is None or getattr(exc, "error_code", "") not in {
                "ones_provider_unavailable",
                "ones_provider_rate_limited",
            }:
                raise
            sleep(delay)
    raise AssertionError("unreachable")


def _detail_with_retry(provider: OnesCollectionProvider, work_item_id: str) -> dict[str, Any]:
    return _request_with_retry(lambda: provider.detail(work_item_id))


def _details(
    provider: OnesCollectionProvider,
    ids: tuple[str, ...],
    check_active: Callable[[], None],
) -> tuple[dict[str, Any], ...]:
    """只并发无状态 HTTP；数据库写入、取消和进度均留在调用线程。"""
    if not ids:
        return ()
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        results: list[dict[str, Any] | None] = [None] * len(ids)
        for offset in range(0, len(ids), DETAIL_WORKERS):
            check_active()
            futures = {
                executor.submit(_detail_with_retry, provider, value): index
                for index, value in enumerate(ids[offset : offset + DETAIL_WORKERS], offset)
            }
            failure: Exception | None = None
            for future in as_completed(futures):
                try:
                    results[futures[future]] = future.result()
                except Exception as exc:
                    failure = failure or exc
            if failure is not None:
                raise failure
        check_active()
    if any(value is None for value in results):
        raise ExportValidationError("knowledge_collection_detail_mismatch")
    return tuple(value for value in results if value is not None)


def _listed_id(
    item: dict[str, Any],
    issue_type_id: str,
    project_ids: frozenset[str],
    seen: set[str],
) -> str:
    if not isinstance(item, dict):
        raise ExportValidationError("knowledge_collection_page_invalid")
    work_item_id = identifier(item.get("uuid"))
    listed_type = item.get("issueType") or {}
    listed_project = item.get("project") or {}
    listed_parent = item.get("parent") or {}
    listed_subtype = item.get("subIssueType") or {}
    if (
        not isinstance(listed_type, dict)
        or listed_type.get("uuid") != issue_type_id
        or not isinstance(listed_project, dict)
        or listed_project.get("uuid") not in project_ids
        or not isinstance(listed_parent, dict)
        or listed_parent.get("uuid")
        or not isinstance(listed_subtype, dict)
        or listed_subtype.get("uuid")
        or work_item_id in seen
    ):
        raise ExportValidationError("knowledge_collection_scope_changed")
    return work_item_id


def _item_detail(
    item: dict[str, Any],
    detail: dict[str, Any],
    issue_type_id: str,
    seen: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    work_item_id = item["uuid"]
    listed_project = item["project"]
    if (
        not isinstance(detail, dict)
        or detail.get("uuid") != work_item_id
        or detail.get("issue_type_uuid") != issue_type_id
        or detail.get("project_uuid") != listed_project["uuid"]
        or detail.get("create_time") != item.get("createTime")
        or detail.get("parent_uuid")
        or detail.get("sub_issue_type_uuid")
    ):
        raise ExportValidationError("knowledge_collection_detail_mismatch")
    seen.add(work_item_id)
    return item, detail


def _collect_window(
    provider: OnesCollectionProvider,
    kind: str,
    issue_type_id: str,
    project_ids: frozenset[str],
    first: date,
    last: date,
    total: int,
    seen: set[str],
    children: dict[str, str],
    commit_page: PageCommit,
    check_active: Callable[[], None],
    staged_ids: frozenset[str],
) -> int:
    cursors: set[str] = set()
    after: str | None = None
    enumerated = 0
    while True:
        check_active()
        page = _request_with_retry(lambda: provider.page(issue_type_id, first, last, after=after))
        if (
            type(page.total) is not int
            or page.total != total
            or type(page.has_next) is not bool
            or not page.items
            or len(page.items) > PAGE_SIZE
            or page.count is not None
            and page.count != len(page.items)
            or enumerated + len(page.items) > total
        ):
            raise ExportValidationError("knowledge_collection_page_invalid")
        # Validate page identities before issuing concurrent detail requests.
        listed_ids = tuple(
            _listed_id(item, issue_type_id, project_ids, seen) for item in page.items
        )
        if len(set(listed_ids)) != len(listed_ids):
            raise ExportValidationError("knowledge_collection_scope_changed")
        # Story details must be read even on replay: their live subtask list is not
        # stored in the normalized parent revision.
        pending = tuple(
            value for value in listed_ids if kind == "requirement" or value not in staged_ids
        )
        details = dict(zip(pending, _details(provider, pending, check_active), strict=True))
        batch = tuple(
            _item_detail(item, details[value], issue_type_id, seen)
            for item, value in zip(page.items, listed_ids, strict=True)
            if value in details
        )
        seen.update(value for value in listed_ids if value not in details)
        if kind == "requirement":
            for item, detail in batch:
                subtasks = detail.get("subtasks") or []
                if not isinstance(subtasks, list):
                    raise ExportValidationError("knowledge_collection_child_invalid")
                for child in subtasks:
                    child_id = identifier(
                        child
                        if isinstance(child, str)
                        else child.get("uuid")
                        if isinstance(child, dict)
                        else None
                    )
                    if child_id in seen or child_id in children:
                        raise ExportValidationError("knowledge_collection_child_invalid")
                    children[child_id] = item["uuid"]
                    if len(seen) + len(children) > MAX_DOCUMENTS:
                        raise ExportValidationError("knowledge_sync_source_limit")
        enumerated += len(page.items)
        next_cursor = page.end_cursor
        if page.has_next and (
            not isinstance(next_cursor, str)
            or not next_cursor
            or next_cursor == after
            or next_cursor in cursors
            or enumerated == total
        ):
            raise ExportValidationError("knowledge_collection_cursor_invalid")
        if not page.has_next and enumerated != total:
            raise ExportValidationError("knowledge_collection_incomplete")
        to_commit = tuple(pair for pair in batch if pair[0]["uuid"] not in staged_ids)
        if to_commit:
            commit_page(
                kind,
                to_commit,
                {
                    "kind": kind,
                    "issue_type_id": issue_type_id,
                    "first": first.isoformat(),
                    "last": last.isoformat(),
                    "next_cursor": next_cursor if page.has_next else None,
                    "enumerated": enumerated,
                    "expected": total,
                },
            )
        if not page.has_next:
            return enumerated
        assert next_cursor is not None
        cursors.add(next_cursor)
        after = next_cursor


def _collect_children(
    provider: OnesCollectionProvider,
    children: dict[str, str],
    project_ids: frozenset[str],
    child_type_ids: frozenset[str],
    seen: set[str],
    commit_page: PageCommit,
    check_active: Callable[[], None],
    staged_ids: frozenset[str],
) -> int:
    parents: dict[str, str] = {}
    batch: list[tuple[dict[str, Any] | None, dict[str, Any]]] = []
    child_ids = tuple(children)
    for offset in range(0, len(child_ids), PAGE_SIZE):
        check_active()
        ids = child_ids[offset : offset + PAGE_SIZE]
        details = _details(provider, ids, check_active)
        for child_id, detail in zip(ids, details, strict=True):
            if child_id in seen:
                raise ExportValidationError("knowledge_collection_child_invalid")
            if not isinstance(detail, dict) or detail.get("uuid") != child_id:
                raise ExportValidationError("knowledge_collection_detail_mismatch")
            if (
                detail.get("project_uuid") not in project_ids
                or detail.get("issue_type_uuid") not in child_type_ids
                or detail.get("sub_issue_type_uuid") not in child_type_ids
            ):
                raise ExportValidationError("knowledge_collection_scope_changed")
            parents[child_id] = identifier(detail.get("parent_uuid"))
            seen.add(child_id)
            if child_id not in staged_ids:
                batch.append((None, detail))
        if batch:
            commit_page(
                "requirement",
                tuple(batch),
                {
                    "kind": "requirement",
                    "children_processed": offset + len(ids),
                    "children_total": len(children),
                },
            )
            batch.clear()
    for child_id, root in children.items():
        visited = {child_id}
        parent = parents[child_id]
        while parent in parents:
            if parent in visited:
                raise ExportValidationError("knowledge_collection_child_cycle")
            visited.add(parent)
            parent = parents[parent]
        if parent != root:
            raise ExportValidationError("knowledge_collection_child_invalid")
    return len(children)


def collect_all(
    provider: OnesCollectionProvider,
    *,
    issue_types: Mapping[str, tuple[str, ...]],
    project_ids: frozenset[str],
    first: date,
    last: date,
    child_type_ids: frozenset[str],
    commit_page: PageCommit,
    check_active: Callable[[], None] = lambda: None,
    on_day_complete: Callable[[date, dict[str, int]], None] = lambda _day, _counts: None,
    initial_counts: Mapping[str, int] | None = None,
    staged_ids: frozenset[str] = frozenset(),
) -> dict[str, int]:
    """按创建日枚举根工作项；日期分片不是更新时间过滤。"""
    _validate_scope(issue_types, project_ids, first, last)
    if not child_type_ids:
        raise ExportValidationError("knowledge_collection_scope_invalid")
    for value in child_type_ids:
        identifier(value)
    seen: set[str] = set()
    counts = {kind: (initial_counts or {}).get(kind, 0) for kind in issue_types}
    day = first
    while day <= last:
        children: dict[str, str] = {}
        for kind, ids in issue_types.items():
            for issue_type_id in ids:
                check_active()
                total = _request_with_retry(lambda: provider.count(issue_type_id, day, day))
                if type(total) is not int or total < 0:
                    raise ExportValidationError("knowledge_collection_count_invalid")
                if total >= WINDOW_LIMIT:
                    raise ExportValidationError("knowledge_collection_window_limit")
                if not total:
                    continue
                if sum(counts.values()) + total + len(children) > MAX_DOCUMENTS:
                    raise ExportValidationError("knowledge_sync_source_limit")
                counts[kind] += _collect_window(
                    provider,
                    kind,
                    issue_type_id,
                    project_ids,
                    day,
                    day,
                    total,
                    seen,
                    children,
                    commit_page,
                    check_active,
                    staged_ids,
                )
                if sum(counts.values()) > MAX_DOCUMENTS:
                    raise ExportValidationError("knowledge_sync_source_limit")
        counts["requirement"] += _collect_children(
            provider,
            children,
            project_ids,
            child_type_ids,
            seen,
            commit_page,
            check_active,
            staged_ids,
        )
        if sum(counts.values()) > MAX_DOCUMENTS:
            raise ExportValidationError("knowledge_sync_source_limit")
        check_active()
        on_day_complete(day, dict(counts))
        day += timedelta(days=1)
    return counts
