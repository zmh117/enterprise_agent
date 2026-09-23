"""完整 ONES 枚举合同；Provider 和持久化均由基础设施注入。

这里不执行导出脚本，不使用历史 done UUID 缓存，也不把缺页解释为删除。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterator, Protocol

from app.modules.knowledge.domain.normalization import ExportValidationError, identifier


PAGE_SIZE = 200
WINDOW_LIMIT = 1000
MAX_DOCUMENTS = 200_000


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


def _windows(
    provider: OnesCollectionProvider,
    issue_type_id: str,
    first: date,
    last: date,
    check_active: Callable[[], None],
) -> Iterator[tuple[date, date, int]]:
    pending = [(first, last)]
    while pending:
        window_first, window_last = pending.pop(0)
        check_active()
        total = provider.count(issue_type_id, window_first, window_last)
        if type(total) is not int or total < 0:
            raise ExportValidationError("knowledge_collection_count_invalid")
        if total >= WINDOW_LIMIT:
            if window_first == window_last:
                raise ExportValidationError("knowledge_collection_window_limit")
            midpoint = window_first + timedelta(days=(window_last - window_first).days // 2)
            pending[:0] = [
                (window_first, midpoint),
                (midpoint + timedelta(days=1), window_last),
            ]
        elif total:
            yield window_first, window_last, total


def _item_detail(
    provider: OnesCollectionProvider,
    item: dict[str, Any],
    issue_type_id: str,
    project_ids: frozenset[str],
    seen: set[str],
    check_active: Callable[[], None],
) -> tuple[dict[str, Any], dict[str, Any]]:
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
    check_active()
    detail = provider.detail(work_item_id)
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
) -> int:
    cursors: set[str] = set()
    after: str | None = None
    enumerated = 0
    while True:
        check_active()
        page = provider.page(issue_type_id, first, last, after=after)
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
        batch = tuple(
            _item_detail(provider, item, issue_type_id, project_ids, seen, check_active)
            for item in page.items
        )
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
        enumerated += len(batch)
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
        commit_page(
            kind,
            batch,
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
) -> int:
    parents: dict[str, str] = {}
    batch: list[tuple[dict[str, Any] | None, dict[str, Any]]] = []
    for index, child_id in enumerate(children, 1):
        check_active()
        if child_id in seen:
            raise ExportValidationError("knowledge_collection_child_invalid")
        detail = provider.detail(child_id)
        if not isinstance(detail, dict) or detail.get("uuid") != child_id:
            raise ExportValidationError("knowledge_collection_detail_mismatch")
        if (
            detail.get("project_uuid") not in project_ids
            or detail.get("issue_type_uuid") not in child_type_ids
            or detail.get("sub_issue_type_uuid") not in child_type_ids
        ):
            raise ExportValidationError("knowledge_collection_scope_changed")
        parent = identifier(detail.get("parent_uuid"))
        parents[child_id] = parent
        seen.add(child_id)
        batch.append((None, detail))
        if len(batch) == PAGE_SIZE or index == len(children):
            commit_page(
                "requirement",
                tuple(batch),
                {
                    "kind": "requirement",
                    "children_processed": index,
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
) -> dict[str, int]:
    """完整枚举并重取每条详情；日期分片不是更新时间过滤。"""
    _validate_scope(issue_types, project_ids, first, last)
    if not child_type_ids:
        raise ExportValidationError("knowledge_collection_scope_invalid")
    for value in child_type_ids:
        identifier(value)
    seen: set[str] = set()
    children: dict[str, str] = {}
    counts = {kind: 0 for kind in issue_types}
    for kind, ids in issue_types.items():
        for issue_type_id in ids:
            for window_first, window_last, total in _windows(
                provider, issue_type_id, first, last, check_active
            ):
                if sum(counts.values()) + total + len(children) > MAX_DOCUMENTS:
                    raise ExportValidationError("knowledge_sync_source_limit")
                counts[kind] += _collect_window(
                    provider,
                    kind,
                    issue_type_id,
                    project_ids,
                    window_first,
                    window_last,
                    total,
                    seen,
                    children,
                    commit_page,
                    check_active,
                )
                if sum(counts.values()) > MAX_DOCUMENTS:
                    raise ExportValidationError("knowledge_sync_source_limit")
    counts["requirement"] += _collect_children(
        provider, children, project_ids, child_type_ids, seen, commit_page, check_active
    )
    if sum(counts.values()) > MAX_DOCUMENTS:
        raise ExportValidationError("knowledge_sync_source_limit")
    return counts
