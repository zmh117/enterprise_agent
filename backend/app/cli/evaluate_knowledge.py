"""离线知识评测；输入路径不回显，stdout 只含脱敏汇总，绝不迁移或写索引。"""

from app.modules.knowledge.infrastructure.vector_repository import VectorRepository

import argparse
import json
from pathlib import Path
from typing import NoReturn

from app.modules.knowledge.application.evaluation import OfflineEvaluation
from app.modules.knowledge.domain.evaluation import EvaluationError
from app.modules.knowledge.infrastructure.evaluation_dataset import load_dataset
from app.modules.knowledge.infrastructure.vector_clients import EmbeddingClient, QdrantClient
from app.modules.knowledge.domain.vector_contract import VectorError
from app.modules.knowledge.application.vector_service import VectorService
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadError, SchemaHeadValidator


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse's default error includes arbitrary command-line input/paths.
        raise EvaluationError("knowledge_evaluation_arguments_invalid")


def main(argv: list[str] | None = None) -> int:
    database = None
    embedding = qdrant = None
    try:
        parser = SafeArgumentParser(
            description="本地离线知识评测；仅输出指标/摘要，不是业务授权验收"
        )
        parser.add_argument("--dataset", required=True, type=Path)
        parser.add_argument("--index-code")
        parser.add_argument(
            "--validate-only", action="store_true", help="仅校验标注集，不连接数据库或模型"
        )
        args = parser.parse_args(argv)
        if bool(args.index_code) == args.validate_only:
            raise EvaluationError("knowledge_evaluation_arguments_invalid")
        dataset = load_dataset(args.dataset)
        if args.validate_only:
            print(
                json.dumps(
                    {
                        "event": "knowledge_evaluation_dataset_valid",
                        "dataset_hash": dataset.digest,
                        "basis": dataset.basis,
                        "cases": len(dataset.cases),
                        "business_acceptance": False,
                    }
                ),
                flush=True,
            )
            return 0
        database = Database(load_settings().database_dsn)
        if database.engine != "postgres":
            raise EvaluationError("knowledge_evaluation_postgres_required")
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        embedding, qdrant = EmbeddingClient(), QdrantClient()
        report = OfflineEvaluation(
            VectorService(VectorRepository(database), embedding, qdrant)
        ).run(dataset, args.index_code)
        print(
            json.dumps({"event": "knowledge_evaluation_completed", **report}, ensure_ascii=False),
            flush=True,
        )
        return 1 if report["failed_cases"] else 0
    except SchemaHeadError:
        code = "knowledge_schema_head_mismatch"
    except EvaluationError as exc:
        code = exc.code
    except VectorError:
        code = "knowledge_evaluation_index_unavailable"
    except Exception:
        code = "knowledge_evaluation_unavailable"
    finally:
        if embedding is not None:
            embedding.http.close()
        if qdrant is not None:
            qdrant.http.close()
        if database is not None:
            database.close()
    print(json.dumps({"event": "knowledge_evaluation_failed", "error_code": code}), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
