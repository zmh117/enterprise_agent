"""只从指定同步运行的冻结成员读取，不依赖 current_revision_id。"""

from collections.abc import Iterator
from typing import Any

from app.modules.knowledge.domain.chunking import ChunkProfile, PreparedChunks
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.vector_contract import VectorError, fingerprint
from app.modules.knowledge.domain.work_items import DOCUMENT_KINDS
from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository, json_value
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.shared.database import Database


class CandidateCorpus:
    def __init__(self, repository: SyncRepository, run_id: str) -> None:
        self.repository = repository
        self.run_id = run_id

    def scope(self, base_id: str) -> str:
        run = self.repository.run(self.run_id)
        binding = self.repository.assert_configuration(run)
        ids = {
            stable_id("base", code) for code in binding["configuration_json"]["base_codes"].values()
        }
        if run["phase"] not in {"STAGED", "CHUNKING", "INDEXING", "VERIFIED"} or base_id not in ids:
            raise ExportValidationError("knowledge_sync_phase_invalid")
        base = self.repository.database.execute_one(
            f"select state from {self.repository.t('knowledge_base')} where id=?", (base_id,)
        )
        if not base or base["state"] != "storage_only":
            raise ExportValidationError("knowledge_base_binding_conflict")
        return str(run["source_id"])

    def member_filter(self, base_id: str) -> tuple[str, tuple[str, str]]:
        self.scope(base_id)
        if self.repository.database.engine == "postgres":
            return "x.run_id=? and x.candidate_members_json->>?='included'", (self.run_id, base_id)
        return "x.run_id=? and json_extract(x.candidate_members_json,?)='included'", (
            self.run_id,
            '$."' + base_id + '"',
        )

    def count(self, base_id: str) -> int:
        clause, params = self.member_filter(base_id)
        found = self.repository.database.execute_one(
            f"select count(*) as n from {self.repository.t('sync_candidate')} x where {clause}",
            params,
        )
        assert found is not None
        return int(found["n"])

    def records(self, base_id: str, *, metadata_only: bool = False) -> Iterator[dict[str, Any]]:
        clause, params = self.member_filter(base_id)
        columns = "x.document_id,r.id as revision_id,r.content_hash"
        if not metadata_only:
            columns += ",x.candidate_kind as document_kind,r.title,r.body_text,r.source_project_name,r.normalizer_version,r.attributes,r.completeness"
        cursor = ""
        while True:
            rows = self.repository.database.execute(
                f"select {columns} from {self.repository.t('sync_candidate')} x join {self.repository.t('document_revision')} r "
                f"on r.id=x.candidate_revision_id and r.document_id=x.document_id where {clause} and x.document_id>? order by x.document_id limit 100",
                (*params, cursor),
            )
            if not rows:
                return
            for row in rows:
                if not metadata_only:
                    row["attributes"] = json_value(row["attributes"])
                    row["completeness"] = json_value(row["completeness"])
                yield row
            cursor = rows[-1]["document_id"]


class CandidateChunkRepository(ChunkRepository):
    def __init__(self, database: Database, run_id: str, *, profile: ChunkProfile) -> None:
        super().__init__(database, profile=profile)
        self.corpus = CandidateCorpus(SyncRepository(database), run_id)

    def scope(self, code: str) -> tuple[str, str]:
        base_id = stable_id("base", code)
        return base_id, self.corpus.scope(base_id)

    def count(self, base_id: str, source_id: str) -> int:
        if self.corpus.scope(base_id) != source_id:
            raise ExportValidationError("knowledge_sync_baseline_invalid")
        return self.corpus.count(base_id)

    def rows(
        self, base_id: str, source_id: str, *, metadata_only: bool = False
    ) -> Iterator[dict[str, Any]]:
        if self.corpus.scope(base_id) != source_id:
            raise ExportValidationError("knowledge_sync_baseline_invalid")
        return self.corpus.records(base_id, metadata_only=metadata_only)

    def save(
        self, record: dict[str, Any], prepared: PreparedChunks, base_id: str, source_id: str
    ) -> str:
        with self.database.unit_of_work():
            run = self.corpus.repository.run(self.corpus.run_id, lock=True)
            if self.corpus.scope(base_id) != source_id or run["phase"] not in {
                "STAGED",
                "CHUNKING",
            }:
                raise ExportValidationError("knowledge_sync_phase_invalid")
            candidate = self.corpus.repository.candidate(self.corpus.run_id, record["document_id"])
            if (
                not candidate
                or candidate["candidate_revision_id"] != record["revision_id"]
                or candidate["candidate_members_json"].get(base_id) != "included"
            ):
                raise ExportValidationError("knowledge_sync_candidate_conflict")
            revision = self.corpus.repository.revision(record["revision_id"])
            if revision["content_hash"] != record["content_hash"]:
                raise ExportValidationError("knowledge_sync_candidate_conflict")
            return self._save_immutable(record, prepared)


class CandidateVectorRepository(VectorRepository):
    def __init__(self, database: Database, run_id: str) -> None:
        super().__init__(database)
        self.corpus = CandidateCorpus(SyncRepository(database), run_id)

    def index_code(self, base_id: str) -> str:
        self.corpus.scope(base_id)
        return "sync-" + stable_id("sync-index", self.corpus.run_id, base_id)

    def create(self, code: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        base_id = snapshot["knowledge_base_id"]
        if code != self.index_code(base_id) or base_id not in self.corpus.repository.changed_bases(
            self.corpus.run_id
        ):
            raise VectorError("knowledge_vector_index_conflict")
        with self.database.unit_of_work():
            found = self.get(code)
            if found and found.get("sync_run_id") != self.corpus.run_id:
                raise VectorError("knowledge_vector_index_conflict")
            index = super().create(code, snapshot)
            source_id = self.corpus.scope(base_id)
            self.database.execute(
                f"update {self.t('vector_index')} set sync_run_id=?,source_id=? where id=?",
                (self.corpus.run_id, source_id, index["id"]),
            )
        return {**index, "sync_run_id": self.corpus.run_id, "source_id": source_id}

    def _document_count(self, base_id: str) -> int:
        return self.corpus.count(base_id)

    def rows(self, base_id: str, chunk_profile: str) -> Iterator[dict[str, Any]]:
        clause, params = self.corpus.member_filter(base_id)
        cursor = ""
        while True:
            rows = self.database.execute(
                "select c.*,s.document_id,s.document_revision_id,s.profile_hash as chunk_profile_hash,"
                "s.source_content_hash,s.chunk_count,r.content_hash,x.candidate_kind as document_kind "
                f"from {self.t('sync_candidate')} x join {self.t('document_chunk_set')} s "
                "on s.document_id=x.document_id and s.document_revision_id=x.candidate_revision_id "
                f"join {self.t('document_revision')} r on r.id=s.document_revision_id and r.document_id=x.document_id "
                f"join {self.t('document_chunk')} c on c.chunk_set_id=s.id "
                f"where {clause} and s.profile_hash=? and c.id>? order by c.id limit 32",
                (*params, chunk_profile, cursor),
            )
            if not rows:
                return
            for row in rows:
                if (
                    row["document_kind"] not in DOCUMENT_KINDS
                    or row["source_content_hash"] != row["content_hash"]
                    or fingerprint(row["embedding_text"]) != row["embedding_hash"]
                    or fingerprint(row["evidence_text"]) != row["evidence_hash"]
                ):
                    raise VectorError("knowledge_vector_source_invalid")
                yield row
            cursor = rows[-1]["id"]

    def evidence_many(
        self, index: dict[str, Any], chunk_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        # 构建用适配器绝不能向在线查询暴露未激活证据。
        raise VectorError("knowledge_vector_candidate_not_queryable")
