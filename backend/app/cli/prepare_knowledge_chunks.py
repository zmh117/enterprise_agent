"""知识清洗分块 CLI：默认只读，显式提交；演示仅使用合成内容。"""

from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository

import argparse
from dataclasses import asdict
import json

from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.domain.chunking import prepare_chunks
from app.modules.knowledge.domain.normalization import NORMALIZER_VERSION, ExportValidationError
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadError, SchemaHeadValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清洗分块并保存待向量化文本，不调用模型")
    parser.add_argument("--knowledge-base-code", default="ones-defects-offline")
    parser.add_argument("--expected-count", type=int, default=5000)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--demo", action="store_true", help="仅输出内置合成示例，不访问数据库")
    args = parser.parse_args(argv)
    database = None
    try:
        if args.demo:
            if args.commit:
                raise ExportValidationError("knowledge_chunk_demo_cannot_commit")
            demo = prepare_chunks(
                {
                    "normalizer_version": NORMALIZER_VERSION,
                    "title": "合成示例：订单提交时报错",
                    "source_project_name": "合成项目",
                    "body_text": "操作步骤：提交测试订单。\n实际结果：返回 E_DEMO_01。\n预期结果：保存成功。",
                    "attributes": {
                        "module_names": ["合成订单模块"],
                        "solution_text": "修正合成参数校验，增加空值判断并通过回归测试。",
                    },
                    "completeness": {},
                }
            )
            print(
                json.dumps(
                    {"event": "synthetic_demo", **asdict(demo)}, ensure_ascii=False, indent=2
                )
            )
            return 0
        database = Database(load_settings().database_dsn)
        if database.engine != "postgres":
            raise ExportValidationError("knowledge_postgres_required")
        validator = SchemaHeadValidator(database, default_migrations_dir())
        if args.commit:
            validator.require_current()
        else:
            validator.require_current_or_previous(allowed_previous_heads=frozenset({"132", "133"}))
        result = ChunkService(ChunkRepository(database)).run(
            knowledge_base_code=args.knowledge_base_code,
            expected_count=args.expected_count,
            commit=args.commit,
            progress=lambda counts: print(
                json.dumps({"event": "chunk_progress", **counts}), flush=True
            ),
        )
        print(json.dumps({"event": "chunks_completed", **result}, ensure_ascii=False), flush=True)
        return 0
    except ExportValidationError as exc:
        print(json.dumps({"event": "chunks_failed", "error_code": exc.code}), flush=True)
        return 1
    except SchemaHeadError:
        print('{"event":"chunks_failed","error_code":"knowledge_schema_head_mismatch"}', flush=True)
        return 1
    except Exception:
        print('{"event":"chunks_failed","error_code":"knowledge_chunk_unavailable"}', flush=True)
        return 1
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
