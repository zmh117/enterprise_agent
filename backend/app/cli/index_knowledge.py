"""本机知识索引：默认只读预检，显式 benchmark 或 commit。"""

from app.modules.knowledge.infrastructure.vector_repository import VectorRepository

import argparse
import json

from app.modules.knowledge.domain.chunking import DEFAULT_PROFILE
from app.modules.knowledge.domain.normalization import ExportValidationError, identifier
from app.modules.knowledge.infrastructure.vector_clients import EmbeddingClient, QdrantClient
from app.modules.knowledge.domain.vector_contract import VectorError
from app.modules.knowledge.application.vector_service import VectorService
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadError, SchemaHeadValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本机知识索引；不记录正文，不授予业务访问权")
    parser.add_argument("--knowledge-base-code", default="ones-defects-offline")
    parser.add_argument("--index-code", required=True, help="语料或配置变化必须使用新的明确版本")
    parser.add_argument("--chunk-profile-hash", default=DEFAULT_PROFILE.fingerprint)
    parser.add_argument("--expected-documents", type=int, default=5000)
    parser.add_argument("--expected-chunks", type=int, default=8309)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--benchmark", action="store_true")
    mode.add_argument("--commit", action="store_true")
    args = parser.parse_args(argv)
    database = None
    embedding, qdrant = EmbeddingClient(), QdrantClient()
    try:
        identifier(args.index_code)
        database = Database(load_settings().database_dsn)
        if database.engine != "postgres":
            raise VectorError("knowledge_postgres_required")
        validator = SchemaHeadValidator(database, default_migrations_dir())
        if args.commit:
            validator.require_current()
        else:
            validator.require_current_or_previous(allowed_previous_heads=frozenset({"133"}))
        service = VectorService(VectorRepository(database), embedding, qdrant)
        snapshot = service.repository.snapshot(
            service.repository.scope(args.knowledge_base_code),
            args.chunk_profile_hash,
            args.expected_documents,
            args.expected_chunks,
        )
        print(json.dumps({"event": "vector_scope_verified", **snapshot}), flush=True)
        # 每次提交亦先全量 token 预检，超限不部分编码。
        result = service.preflight(snapshot, benchmark=args.benchmark)
        print(json.dumps({"event": "vector_preflight_completed", **result}), flush=True)
        if args.commit:
            result = service.build(
                args.index_code,
                snapshot,
                progress=lambda counts: print(
                    json.dumps({"event": "vector_progress", **counts}), flush=True
                ),
            )
        print(json.dumps({"event": "vector_completed", **result}), flush=True)
        return 0
    except (VectorError, ExportValidationError) as exc:
        print(json.dumps({"event": "vector_failed", "error_code": exc.code}), flush=True)
        return 1
    except SchemaHeadError:
        print('{"event":"vector_failed","error_code":"knowledge_schema_head_mismatch"}', flush=True)
        return 1
    except Exception:
        print('{"event":"vector_failed","error_code":"knowledge_vector_unavailable"}', flush=True)
        return 1
    finally:
        embedding.http.close()
        qdrant.http.close()
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
