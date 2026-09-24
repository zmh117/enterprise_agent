"""默认关闭的 ONES 全量采集用例；仅生成候选，不修改当前发布。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.modules.knowledge.application.ones_collection import OnesCollectionProvider, collect_all
from app.modules.knowledge.application.ones_collection_normalizer import OnesCollectionNormalizer
from app.modules.knowledge.application.ports import SyncRepository
from app.modules.knowledge.domain.normalization import ExportValidationError


_PROVIDER_FAILURES = {
    "ones_provider_unauthorized": "knowledge_collection_unauthorized",
    "ones_provider_forbidden": "knowledge_collection_forbidden",
    "ones_provider_operation_unavailable": "knowledge_collection_not_found",
    "ones_provider_unavailable": "knowledge_collection_provider_unavailable",
    "ones_provider_rate_limited": "knowledge_collection_rate_limited",
    "ones_provider_response_too_large": "knowledge_collection_response_too_large",
}


class KnowledgeOnesCollectionService:
    def __init__(
        self,
        repository: SyncRepository,
        provider_factory: Callable[[dict[str, Any]], OnesCollectionProvider],
        *,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self.repository = repository
        self.provider_factory = provider_factory
        self.cancelled = cancelled

    def collect_once(
        self,
        binding_id: str,
        *,
        scan_at: str | None = None,
        through: date | None = None,
        on_run_started: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        repo = self.repository
        binding = repo.binding(binding_id)
        collector = binding["configuration_json"].get("collector")
        if not collector or binding["enabled"] != 1:
            raise ExportValidationError("knowledge_collection_disabled")
        with repo.source_lock(binding["source_id"]):
            active = repo.active_collection(binding_id)
            new_run = active is None
            if active is None:
                started = scan_at or datetime.now(timezone.utc).isoformat()
                run = repo.begin_collection(binding_id, started)
            else:
                run = active
            if run["phase"] != "COLLECTING":
                summary: dict[str, Any] = repo.summary(run["id"])
                return summary
            try:
                if new_run and on_run_started is not None:
                    on_run_started(run["id"])
                provider = self.provider_factory(collector)
                issue_types = {
                    kind: tuple(values) for kind, values in collector["issue_types"].items()
                }
                type_ids = tuple(
                    sorted(
                        {value for values in issue_types.values() for value in values}
                        | set(collector["child_type_ids"])
                    )
                )

                def check_active() -> None:
                    if self.cancelled():
                        raise ExportValidationError("knowledge_sync_cancelled")
                    if repo.binding(binding_id)["enabled"] != 1:
                        repo.cancel_disabled_collection(run["id"])
                        raise ExportValidationError("knowledge_collection_disabled")

                check_active()
                fields, names = provider.catalog(type_ids, check_active=check_active)
                normalizer = OnesCollectionNormalizer(fields=fields, names=names)

                def commit_page(
                    kind: str,
                    pairs: tuple[tuple[dict[str, Any] | None, dict[str, Any]], ...],
                    checkpoint: dict[str, Any],
                ) -> None:
                    check_active()
                    records = tuple(
                        normalizer.normalize(listing, detail, kind=kind)
                        for listing, detail in pairs
                    )
                    repo.commit_collection_page(run["id"], records, checkpoint)

                counts = collect_all(
                    provider,
                    issue_types=issue_types,
                    project_ids=frozenset(collector["project_ids"]),
                    first=date.fromisoformat(collector["first_date"]),
                    last=through
                    or (
                        datetime.fromisoformat(run["manifest_json"]["defect"]["scan_at"])
                        .astimezone(timezone.utc)
                        .date()
                        + timedelta(days=1)
                    ),
                    child_type_ids=frozenset(collector["child_type_ids"]),
                    commit_page=commit_page,
                    check_active=check_active,
                )
                check_active()
                if not any(counts.values()):
                    raise ExportValidationError("knowledge_collection_empty_scope")
                completed: dict[str, Any] = repo.complete_collection(run["id"], counts)
                return completed
            except Exception as exc:
                code = (
                    exc.code
                    if isinstance(exc, ExportValidationError)
                    else _PROVIDER_FAILURES.get(
                        getattr(exc, "error_code", ""), "knowledge_collection_failed"
                    )
                )
                repo.fail(run["id"], code)
                raise ExportValidationError(code) from None
