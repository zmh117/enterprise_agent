"""三 KB 测试快照维护；默认只预检，阶段命令显式写入且仅输出安全统计。"""

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, NoReturn

from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.application.sync_service import KnowledgeSyncService
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.domain.chunking import KEEP_IDS_PROFILE
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.sync import replacement_manifest
from app.modules.knowledge.domain.vector_contract import VectorError
from app.modules.knowledge.domain.work_items import DEFAULT_BASE_CODES
from app.modules.knowledge.infrastructure.candidate_corpus import (
    CandidateChunkRepository,
    CandidateVectorRepository,
)
from app.modules.knowledge.infrastructure.keep_ids_export import prepare_keep_ids
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from app.modules.knowledge.infrastructure.vector_clients import EmbeddingClient, QdrantClient
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.modules.knowledge.infrastructure.vector_capacity import VectorCapacity
from app.modules.knowledge.infrastructure.storage import table
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadError, SchemaHeadValidator


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ExportValidationError("knowledge_replacement_arguments_invalid")


def emit(event: str, value: dict[str, Any]) -> None:
    print(json.dumps({"event": event, **value}, ensure_ascii=False, default=str), flush=True)


def evaluate(
    database: Database,
    run: dict[str, Any],
    binding: dict[str, Any],
    embedding: EmbeddingClient,
    qdrant: QdrantClient,
) -> None:
    """固定 hash 取样的已知项自检；只输出聚合，不能作为真实问题召回率。"""
    if run["phase"] != "ACTIVATED":
        raise ExportValidationError("knowledge_replacement_not_activated")
    vectors = VectorRepository(database)
    service = VectorService(vectors, embedding, qdrant)
    total_failures = 0
    for kind, base_code in binding["configuration_json"]["base_codes"].items():
        base_id = stable_id("base", base_code)
        code = "sync-" + stable_id("sync-index", run["id"], base_id)
        index = vectors.get(code)
        if not index:
            raise VectorError("knowledge_vector_index_not_ready")
        vectors.assert_current(index)
        rows = database.execute(
            f"select d.id,r.title,r.body_text from {table(database, 'knowledge_base_document')} m "
            f"join {table(database, 'document')} d on d.id=m.document_id "
            f"join {table(database, 'document_revision')} r on r.id=d.current_revision_id "
            "where m.knowledge_base_id=? and m.state='included' and d.lifecycle_state='active' order by d.id",
            (base_id,),
        )
        for cohort in ("title_known_item", "body_excerpt_known_item"):
            eligible = [
                row
                for row in rows
                if cohort == "title_known_item" or len(row["body_text"] or "") >= 80
            ]
            sample = eligible[:10]
            for mode in ("bm25", "dense", "hybrid"):
                ranks, latencies, failures = [], [], 0
                for row in sample:
                    text = (
                        row["title"][:2000]
                        if cohort == "title_known_item"
                        else row["body_text"][:160]
                    )
                    tick = time.monotonic()
                    try:
                        result = service.query(code, base_code, text, mode=mode, top_k=10)
                        ids = [item["document_id"] for item in result["documents"]]
                        ranks.append(ids.index(row["id"]) + 1 if row["id"] in ids else 0)
                    except VectorError:
                        failures += 1
                        total_failures += 1
                        ranks.append(0)
                    latencies.append(time.monotonic() - tick)
                ordered = sorted(latencies)
                n = len(sample)
                emit(
                    "knowledge_hybrid_self_evaluation",
                    {
                        "kind": kind,
                        "cohort": cohort,
                        "mode": mode,
                        "queries": n,
                        "eligible": len(eligible),
                        "failures": failures,
                        "self_hit": {
                            str(k): sum(0 < r <= k for r in ranks) / max(n, 1) for k in (1, 5, 10)
                        },
                        "mrr_at_10": sum(1 / r for r in ranks if r) / max(n, 1),
                        "latency_seconds": {
                            str(p): round(ordered[max(0, math.ceil(n * p) - 1)], 3) if n else None
                            for p in (0.5, 0.95)
                        },
                        "label_scope": "self_item_only_not_human_relevance_or_real_ones_acceptance",
                    },
                )
        vectors.assert_current(index)
    if total_failures:
        raise ExportValidationError("knowledge_hybrid_evaluation_incomplete")


def main(argv: list[str] | None = None) -> int:  # noqa: C901, PLR0915
    database = embedding = qdrant = None
    try:
        parser = SafeParser(
            description="显式三知识库测试内容替换；不会删除原文件、修改凭据或启用调度"
        )
        parser.add_argument(
            "--mode",
            choices=("preflight", "stage", "chunks", "benchmark", "index", "activate", "evaluate"),
            default="preflight",
        )
        parser.add_argument("--input-dir", type=Path)
        parser.add_argument("--defects", type=int, default=2000)
        parser.add_argument("--tickets", type=int, default=2000)
        parser.add_argument("--stories", type=int, default=2000)
        parser.add_argument("--children", type=int, default=6654)
        parser.add_argument("--source-code", default="ones-offline-export")
        parser.add_argument("--binding-code", default="ones-keep-ids-test-snapshot")
        parser.add_argument("--resource-id", action="append", default=[])
        parser.add_argument("--run-id")
        parser.add_argument("--actor-id")
        parser.add_argument("--capacity-path", type=Path)
        parser.add_argument("--commit", action="store_true")
        args = parser.parse_args(argv)
        if args.mode in {"stage", "chunks", "index", "activate"} and not args.commit:
            raise ExportValidationError("knowledge_replacement_commit_required")
        exports = None
        if args.mode in {"preflight", "stage"}:
            if args.input_dir is None:
                raise ExportValidationError("knowledge_replacement_arguments_invalid")
            exports = prepare_keep_ids(
                args.input_dir,
                expected={
                    "缺陷": args.defects,
                    "工单": args.tickets,
                    "Story": args.stories,
                    "子任务": args.children,
                },
            )
            emit(
                "knowledge_replacement_preflight",
                {
                    "types": {
                        item.manifest["document_kind"]: {
                            "manifest": item.manifest,
                            "statistics": item.statistics,
                        }
                        for item in exports
                    }
                },
            )
            if args.mode == "preflight":
                return 0
        database = Database(load_settings().database_dsn)
        if database.engine != "postgres":
            raise ExportValidationError("knowledge_replacement_postgres_required")
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        repo = SyncRepository(database)
        if args.mode == "stage":
            assert exports is not None
            config = {"base_codes": DEFAULT_BASE_CODES, "resource_ids": sorted(args.resource_id)}
            binding_id = stable_id("sync-binding", args.binding_code)
            existing = database.execute_one(
                f"select id from {repo.t('sync_binding')} where id=?", (binding_id,)
            )
            if existing:
                binding = repo.binding(binding_id)
                if binding["configuration_json"] != config or binding["source_id"] != stable_id(
                    "source", args.source_code
                ):
                    raise ExportValidationError("knowledge_sync_configuration_changed")
            else:
                binding = repo.configure(
                    code=args.binding_code,
                    source_code=args.source_code,
                    configuration=config,
                    expected_revision=0,
                )
            result = KnowledgeSyncService(repo).stage_test_replacement(
                binding["id"],
                exports,
                progress=lambda value: emit("knowledge_replacement_staging", value),
            )
            emit("knowledge_replacement_staged", result)
            return 0
        if not args.run_id:
            raise ExportValidationError("knowledge_replacement_arguments_invalid")
        if args.mode == "activate":
            if not args.actor_id:
                raise ExportValidationError("knowledge_replacement_actor_required")
            # 只有 API 维护环境具备受管连接解密和真实管理员授权；不为离线 ops 增加密钥权限。
            from app.bootstrap import build_api_container
            from app.modules.knowledge.application.test_snapshot_activation import (
                TestSnapshotActivation,
            )
            from app.modules.knowledge.infrastructure.replacement_repository import (
                ReplacementRepository,
            )

            database.close()
            runtime = build_api_container(load_settings(), seed=False)
            database = runtime.database
            if runtime.knowledge_services is None:
                raise ExportValidationError("knowledge_replacement_verifier_unavailable")
            resources = runtime.knowledge_services.resources()
            embedding, qdrant = EmbeddingClient(), QdrantClient()
            resources.embedding, resources.qdrant = embedding, qdrant
            result = TestSnapshotActivation(
                ReplacementRepository(database),
                resources,
                CandidateVectorRepository(database, args.run_id),
            ).run(args.run_id, actor_id=args.actor_id)
            emit("knowledge_replacement_activated", result)
            return 0
        run = repo.run(args.run_id)
        if not replacement_manifest(run["manifest_json"]):
            raise ExportValidationError("knowledge_replacement_scope_invalid")
        binding = repo.assert_configuration(run)
        if args.mode == "evaluate":
            embedding, qdrant = EmbeddingClient(), QdrantClient()
            evaluate(database, run, binding, embedding, qdrant)
            return 0
        if args.mode == "chunks":
            if run["phase"] == "STAGED":
                repo.advance(run["id"], expected_phase="STAGED", phase="CHUNKING")
            chunks = CandidateChunkRepository(database, run["id"], profile=KEEP_IDS_PROFILE)
            for kind, manifest in run["manifest_json"].items():
                report = ChunkService(chunks).run(
                    knowledge_base_code=binding["configuration_json"]["base_codes"][kind],
                    expected_count=manifest["record_count"],
                    commit=True,
                    progress=lambda value: emit("knowledge_replacement_chunking", value),
                )
                emit("knowledge_replacement_chunks", {"kind": kind, **report})
            return 0
        vectors = CandidateVectorRepository(database, run["id"])
        embedding, qdrant = EmbeddingClient(), QdrantClient()
        service = VectorService(vectors, embedding, qdrant)
        if args.mode == "index" and run["phase"] == "CHUNKING":
            repo.advance(run["id"], expected_phase="CHUNKING", phase="INDEXING")
        for kind, manifest in run["manifest_json"].items():
            base_id = stable_id("base", binding["configuration_json"]["base_codes"][kind])
            count = sum(1 for _ in vectors.rows(base_id, KEEP_IDS_PROFILE.fingerprint))
            snapshot = vectors.snapshot(
                base_id, KEEP_IDS_PROFILE.fingerprint, manifest["record_count"], count
            )
            if args.mode == "benchmark":
                result = service.preflight(snapshot, benchmark=True)
            else:
                result = service.build(
                    vectors.index_code(base_id),
                    snapshot,
                    progress=lambda value: emit(
                        "knowledge_replacement_indexing", {"kind": kind, **value}
                    ),
                    capacity_check=VectorCapacity(args.capacity_path).check
                    if args.capacity_path
                    else None,
                )
            emit("knowledge_replacement_" + args.mode, {"kind": kind, **result})
        return 0
    except SchemaHeadError:
        code = "knowledge_schema_head_mismatch"
    except KnowledgeGovernanceError as exc:
        code = exc.error_code
    except (ExportValidationError, VectorError) as exc:
        code = exc.code
    except Exception:
        code = "knowledge_replacement_failed"
    finally:
        if embedding:
            embedding.http.close()
        if qdrant:
            qdrant.http.close()
        if database:
            database.close()
    emit("knowledge_replacement_failed", {"error_code": code})
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
