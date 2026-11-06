"""Snapshot-isolated vector writes, exact visibility verification and content-hash reuse."""

from collections.abc import Callable
from typing import Any, Protocol

from app.modules.knowledge.application.ports import EmbeddingPort, QdrantPort
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_projection import (
    PROJECTION_HASH,
    MAX_POINTS,
    fragments,
    cache_point,
)
from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import digest, canonical_json
from app.modules.knowledge.domain.vector_contract import validate_vector
from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository
from app.modules.knowledge.infrastructure.code_repository import decoded
from app.modules.knowledge.infrastructure.embedding_profile import profile
from app.modules.knowledge.infrastructure.storage import insert, table, source_lock
from app.shared.database import Database


class CodeIndexStore:
    def __init__(self, database: Database) -> None:
        self.db = database

    def ensure(self, source_id: str) -> dict[str, Any]:
        binding = CodeBuildRepository(self.db).content.binding(source_id)
        identifier = stable_id(
            "code_index", binding["knowledge_base_id"], digest(profile()), PROJECTION_HASH
        )
        values = {
            "id": identifier,
            "code": "code-" + identifier,
            "knowledge_base_id": binding["knowledge_base_id"],
            "source_id": source_id,
            "profile": profile(),
            "profile_hash": digest(profile()),
            "chunk_profile_hash": PROJECTION_HASH,
            "corpus_hash": digest(["code-snapshots/v1", source_id, PROJECTION_HASH]),
            "collection_name": "knowledge_" + identifier.replace("-", ""),
            "incremental": 1,
        }
        with source_lock(self.db, source_id), self.db.unit_of_work():
            existing = self.db.execute_one(
                f"select * from {table(self.db, 'vector_index')} where id=?", (identifier,)
            )
            if existing:
                existing["profile"] = decoded(existing["profile"])
                if (
                    any(existing[key] != value for key, value in values.items())
                    or existing["state"] == "RETIRED"
                ):
                    raise CodeKnowledgeError("code_index_configuration_changed")
                return existing
            insert(
                self.db,
                "vector_index",
                {
                    **values,
                    "state": "BUILDING",
                    "expected_document_count": 0,
                    "expected_chunk_count": 0,
                    "created_at": now(),
                    "updated_at": now(),
                },
            )
        return {**values, "state": "BUILDING"}

    def rows(self, index: dict[str, Any], snapshot_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            f"select m.document_id,m.revision_id,r.attributes from {table(self.db, 'code_member')} m "
            f"join {table(self.db, 'document_revision')} r on r.id=m.revision_id and r.document_id=m.document_id "
            f"join {table(self.db, 'code_snapshot')} s on s.id=m.snapshot_id "
            "where m.snapshot_id=? and s.knowledge_base_id=? order by m.document_id limit 20001",
            (snapshot_id, index["knowledge_base_id"]),
        )
        result = []
        for row in rows:
            value = {
                "knowledge_id": row["document_id"],
                "revision_id": row["revision_id"],
                **decoded(row["attributes"]),
            }
            result.extend(fragments(index, snapshot_id, value))
            if len(result) > MAX_POINTS:
                raise CodeKnowledgeError("code_index_point_budget_exhausted")
        if not result:
            raise CodeKnowledgeError("code_index_candidate_empty")
        return result


class CodeQdrantPort(QdrantPort, Protocol):
    def code_count(self, index: dict[str, Any], snapshot_id: str) -> int: ...


class CodeSnapshotIndexer:
    def __init__(
        self, database: Database, embedding: EmbeddingPort, qdrant: CodeQdrantPort
    ) -> None:
        self.db, self.embedding, self.qdrant = database, embedding, qdrant
        self.builds, self.store = CodeBuildRepository(database), CodeIndexStore(database)

    def index(self, build_id: str, lease: int) -> bool:
        build = self.builds._leased(build_id, lease)
        snapshot = self.builds.content.snapshot(
            self.builds.content.binding(build["source_id"])["knowledge_base_id"],
            build["snapshot_id"],
            ready=False,
        )
        validation = decoded(snapshot["validation_json"])
        if (
            build["stage"] != "INDEXING"
            or not validation.get("machine_valid")
            or validation.get("activation_blocked", True)
            or not validation.get("business_verified")
        ):
            raise CodeKnowledgeError("code_snapshot_validation_incomplete")
        index = self.store.ensure(build["source_id"])
        rows = self.store.rows(index, build["snapshot_id"])
        expected = {row["id"]: digest(row["payload"]) for row in rows}
        state = decoded(snapshot["index_manifest"])
        fixed = {
            "index_id": index["id"],
            "expected_digest": digest(expected),
            "expected_count": len(rows),
        }
        if state and any(state.get(key) != value for key, value in fixed.items()):
            raise CodeKnowledgeError("code_index_manifest_changed")
        written, verified = state.get("written_count", 0), state.get("verified_count", 0)
        if (
            type(written) is not int
            or type(verified) is not int
            or not 0 <= verified <= written <= len(rows)
        ):
            raise CodeKnowledgeError("code_index_checkpoint_invalid")
        self.qdrant.ensure(index)

        def check() -> None:
            self.builds.renew(build_id, lease)

        if written < len(rows):
            self.embedding.check()
            self._batch(index, rows[written : written + 16], check)
            written = min(written + 16, len(rows))
        elif verified < len(rows):
            batch = rows[verified : verified + 32]
            check()
            points = self.qdrant.retrieve(index, [row["id"] for row in batch])
            for row in batch:
                if row["id"] not in points:
                    raise CodeKnowledgeError("code_index_visibility_incomplete")
                self._valid(points[row["id"]], row)
            verified += len(batch)
        ready = bool(verified == len(rows))
        if ready and self.qdrant.code_count(index, build["snapshot_id"]) != len(rows):
            raise CodeKnowledgeError("code_index_visibility_incomplete")
        with self.db.unit_of_work():
            self.builds._leased(build_id, lease)
            current = self.builds.content.snapshot(
                index["knowledge_base_id"], build["snapshot_id"], ready=False
            )
            if (
                decoded(current["validation_json"]) != validation
                or decoded(current["index_manifest"]) != state
            ):
                raise CodeKnowledgeError("code_index_checkpoint_changed")
            self.db.execute(
                f"update {table(self.db, 'code_snapshot')} set index_manifest=? where id=? and state='CANDIDATE'",
                (
                    canonical_json({**fixed, "written_count": written, "verified_count": verified}),
                    build["snapshot_id"],
                ),
            )
            if ready:
                self.db.execute(
                    f"update {table(self.db, 'vector_index')} set state='READY',updated_at=? where id=?",
                    (now(), index["id"]),
                )
                self.builds.make_ready(
                    build_id,
                    lease,
                    validation=validation,
                    expected_points=expected,
                    visible_points=expected,
                )
        return ready

    def _batch(
        self, index: dict[str, Any], rows: list[dict[str, Any]], check: Callable[[], None]
    ) -> None:
        check()
        existing = self.qdrant.retrieve(index, [row["id"] for row in rows])
        missing = []
        for row in rows:
            if row["id"] in existing:
                self._valid(existing[row["id"]], row)
            else:
                missing.append(row)
        if not missing:
            return
        definitions = {cache_point(index, row)["id"]: cache_point(index, row) for row in missing}
        cached = self.qdrant.retrieve(index, list(definitions))
        vectors = {}
        for key, value in cached.items():
            self._valid(value, definitions[key])
            vectors[key] = value["vector"]
        writes = []
        for row in missing:
            check()
            cache = cache_point(index, row)
            if cache["id"] not in vectors:
                # One bounded text at a time also stays within the shared batch
                # token budget for Unicode-heavy business explanations.
                vector = self.embedding.call([row["text"]], encode=True)["vectors"][0]
                vectors[cache["id"]] = validate_vector(vector)
                writes.append({**cache, "vector": vector})
            writes.append(
                {"id": row["id"], "payload": row["payload"], "vector": vectors[cache["id"]]}
            )
        check()
        self.qdrant.upsert(index, writes)

    @staticmethod
    def _valid(actual: dict[str, Any], expected: dict[str, Any]) -> None:
        if actual.get("id") != expected["id"] or actual.get("payload") != expected["payload"]:
            raise CodeKnowledgeError("code_index_point_conflict")
        validate_vector(actual.get("vector"))
