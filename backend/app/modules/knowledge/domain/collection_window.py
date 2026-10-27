"""显式创建日补采只扩展单次运行，不改变绑定或常规七日策略。"""

from datetime import date
from typing import Any

from app.modules.knowledge.domain.normalization import ExportValidationError


def validate_backfill(first: date, last: date, earliest: date, today: date) -> None:
    if not earliest <= first <= last <= today:
        raise ExportValidationError("knowledge_collection_range_invalid")


def check_resumed_range(run: dict[str, Any], window: tuple[date, date] | None) -> None:
    manifests = list(run.get("manifest_json", {}).values())
    if window is not None and not manifests:
        raise ExportValidationError("knowledge_collection_range_changed")
    for manifest in manifests:
        backfill = manifest.get("scan_mode") == "backfill"
        if window is None:
            if backfill:
                raise ExportValidationError("knowledge_collection_range_changed")
        elif not backfill or (manifest.get("scan_first"), manifest.get("scan_last")) != tuple(
            day.isoformat() for day in window
        ):
            raise ExportValidationError("knowledge_collection_range_changed")
