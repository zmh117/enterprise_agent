"""受限运维查询；stdin 输入，输出引用而非业务正文。"""

from app.modules.knowledge.infrastructure.vector_repository import VectorRepository

import argparse
import json
import sys

from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.infrastructure.vector_clients import EmbeddingClient, QdrantClient
from app.modules.knowledge.domain.vector_contract import VectorError
from app.modules.knowledge.application.vector_service import VectorService
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadError, SchemaHeadValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地知识检索；从 stdin 读取最多 2000 字查询")
    parser.add_argument("--knowledge-base-code", required=True)
    parser.add_argument("--index-code", required=True)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args(argv)
    database = None
    embedding, qdrant = EmbeddingClient(), QdrantClient()
    try:
        query = sys.stdin.read(2002)
        if query.endswith("\n"):
            query = query[:-1]
        if len(query) > 2000:
            raise VectorError("knowledge_vector_query_invalid")
        database = Database(load_settings().database_dsn)
        if database.engine != "postgres":
            raise VectorError("knowledge_postgres_required")
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        result = VectorService(VectorRepository(database), embedding, qdrant).query(
            args.index_code, args.knowledge_base_code, query, top_k=args.top_k
        )
        print(
            json.dumps({"event": "knowledge_query_completed", **result}, ensure_ascii=False),
            flush=True,
        )
        return 0
    except (VectorError, ExportValidationError) as exc:
        print(json.dumps({"event": "knowledge_query_failed", "error_code": exc.code}), flush=True)
        return 1
    except SchemaHeadError:
        print(
            '{"event":"knowledge_query_failed","error_code":"knowledge_schema_head_mismatch"}',
            flush=True,
        )
        return 1
    except Exception:
        print(
            '{"event":"knowledge_query_failed","error_code":"knowledge_vector_unavailable"}',
            flush=True,
        )
        return 1
    finally:
        embedding.http.close()
        qdrant.http.close()
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
