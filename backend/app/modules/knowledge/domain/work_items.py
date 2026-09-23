"""明确的离线来源分类和版本顺序；不从显示名称反推 ONES UUID。"""

from typing import Any, Literal

from app.modules.knowledge.domain.normalization import ExportValidationError


DOCUMENT_KINDS = frozenset({"defect", "ticket", "requirement"})
OFFLINE_SOURCE_TYPES = {
    "缺陷": "defect",
    "MES工单": "ticket",
    "Story": "requirement",
    "Sub-task": "requirement",
    "演示子任务": "requirement",
}
KIND_LABELS = {"defect": "缺陷", "ticket": "工单", "requirement": "需求"}
DEFAULT_BASE_CODES = {
    "defect": "ones-defects-offline",
    "ticket": "ones-tickets-offline",
    "requirement": "ones-stories-offline",
}


def document_kind(value: Any) -> str:
    if not isinstance(value, str) or value not in DOCUMENT_KINDS:
        raise ExportValidationError("knowledge_document_kind_invalid")
    return value


def check_offline_type(kind: str, source_type: Any) -> None:
    document_kind(kind)
    if not isinstance(source_type, str) or OFFLINE_SOURCE_TYPES.get(source_type) != kind:
        raise ExportValidationError("knowledge_source_type_mismatch")


def compare_version(
    *,
    old_stamp: int | None,
    new_stamp: int | None,
    old_hash: str,
    new_hash: str,
    old_kind: str,
    new_kind: str,
) -> Literal["unchanged", "stale", "revised"]:
    """分类属于有效内容。先比较来源顺序，不能用相同内容复活过时成员。"""
    document_kind(old_kind)
    document_kind(new_kind)
    for stamp in (old_stamp, new_stamp):
        if stamp is not None and (type(stamp) is not int or stamp <= 0):
            raise ExportValidationError("knowledge_timestamp_invalid")
    if old_stamp is not None and (new_stamp is None or new_stamp < old_stamp):
        return "stale"
    if old_hash == new_hash and old_kind == new_kind:
        return "unchanged"
    if old_stamp == new_stamp:
        raise ExportValidationError("knowledge_source_version_conflict")
    return "revised"
