"""受管批次候选用例；现有内容只读，分块/索引/激活为后续明确阶段。"""

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from app.modules.knowledge.application.ports import SyncRepository
from app.modules.knowledge.domain.normalization import ExportValidationError, PreparedExport, digest
from app.modules.knowledge.domain.work_items import document_kind
from app.modules.knowledge.domain.sync import REPLACE_TEST_SNAPSHOT, replacement_manifest


class KnowledgeSyncService:
    def __init__(self, repository: SyncRepository) -> None:
        self.repository = repository

    def stage_test_replacement(
        self,
        binding_id: str,
        exports: tuple[PreparedExport, ...],
        *,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """仅维护入口显式调用；普通同步绝不把未出现的文档移出知识库。"""
        exports = tuple(
            replace(item, manifest={**item.manifest, "operation": REPLACE_TEST_SNAPSHOT})
            for item in exports
        )
        replacement_manifest({item.manifest["document_kind"]: item.manifest for item in exports})
        return self.stage_exports(binding_id, exports, progress=progress)

    def stage_exports(
        self,
        binding_id: str,
        exports: tuple[PreparedExport, ...],
        *,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if not 1 <= len(exports) <= 3:
            raise ExportValidationError("knowledge_sync_batch_invalid")
        kinds, seen = set(), set()
        for item in exports:
            kind = document_kind(item.manifest.get("document_kind"))
            if kind in kinds or not item.records:
                raise ExportValidationError("knowledge_sync_batch_invalid")
            kinds.add(kind)
            for record in item.records:
                if (
                    record.external_id in seen
                    or record.document_kind != kind
                    or record.content_hash != digest(record.values)
                ):
                    raise ExportValidationError("knowledge_sync_batch_invalid")
                seen.add(record.external_id)
                if len(seen) > 200_000:
                    raise ExportValidationError("knowledge_sync_source_limit")
        replacement_manifest({item.manifest["document_kind"]: item.manifest for item in exports})
        repo = self.repository
        binding = repo.binding(binding_id)
        with repo.source_lock(binding["source_id"]):
            run = repo.begin(binding_id, exports)
            if run["phase"] != "COLLECTING":
                return repo.summary(run["id"])
            try:
                for item in exports:
                    for index, record in enumerate(item.records):
                        repo.stage(run["id"], record)
                        if progress and (index + 1) % 250 == 0:
                            progress(repo.summary(run["id"]))
                return repo.finish_staging(run["id"])
            except Exception as exc:
                code = (
                    exc.code if isinstance(exc, ExportValidationError) else "knowledge_sync_failed"
                )
                repo.fail(run["id"], code)
                raise ExportValidationError(code) from None
