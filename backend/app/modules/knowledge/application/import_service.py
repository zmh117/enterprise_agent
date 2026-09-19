"""离线导入用例；存储事务与 SQL 由仓储实现。"""

from collections.abc import Callable
from typing import Any
from app.modules.knowledge.application.ports import ImportRepository
from app.modules.knowledge.domain.normalization import (
    ExportValidationError,
    PreparedExport,
    identifier,
    digest,
)
from app.modules.knowledge.domain.identity import stable_id


class KnowledgeImportService:
    def __init__(self, repository: ImportRepository) -> None:
        self.repository = repository

    def import_export(
        self,
        prepared: PreparedExport,
        *,
        source_code: str,
        knowledge_base_code: str,
        progress: Callable[[dict[str, int]], None] | None = None,
    ) -> dict[str, Any]:
        identifier(source_code)
        identifier(knowledge_base_code)
        source_id = stable_id("source", source_code)
        base_id = stable_id("base", knowledge_base_code)
        run_id = stable_id("import", source_id, base_id, digest(prepared.manifest))
        repo = self.repository
        with repo.source_lock(source_id):
            run = repo.begin(
                prepared,
                source_code,
                knowledge_base_code,
                source_id,
                base_id,
                run_id,
                digest(prepared.manifest),
            )
            replayed = run["state"] == "completed"
            if not replayed:
                try:
                    for index in range(int(run["processed_count"]), len(prepared.records)):
                        repo.commit_record(prepared.records[index], source_id, base_id, run_id)
                        if progress and (
                            (index + 1) % 250 == 0 or index + 1 == len(prepared.records)
                        ):
                            progress({"processed": index + 1, "total": len(prepared.records)})
                    repo.complete(source_id, run_id)
                except Exception as exc:
                    code = (
                        exc.code
                        if isinstance(exc, ExportValidationError)
                        else "knowledge_import_failed"
                    )
                    repo.fail(run_id, code)
                    raise ExportValidationError(code) from None
            return {
                **repo.result(run_id),
                "run_id": run_id,
                "replayed": replayed,
                "verification": repo.verify(prepared, source_id=source_id, base_id=base_id),
            }
