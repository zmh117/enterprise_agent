"""受限 ONES 离线导入入口；显式 --commit 才写入，永不自动建表。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.modules.knowledge.import_service import KnowledgeImportService
from app.modules.knowledge.ones_export import ExportValidationError, prepare_export
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadError, SchemaHeadValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="预检或导入 ONES 缺陷离线文本，不调用外部服务")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--detail-file", default="缺陷完整_5000.jsonl")
    parser.add_argument("--list-file", default="缺陷list_5000.jsonl")
    parser.add_argument("--expected-count", type=int, default=5000)
    parser.add_argument("--source-code", default="ones-offline-export")
    parser.add_argument("--knowledge-base-code", default="ones-defects-offline")
    parser.add_argument("--commit", action="store_true", help="显式提交到当前配置数据库；不执行 DDL")
    args = parser.parse_args(argv)
    database: Database | None = None
    try:
        if args.input_dir.is_symlink() or not args.input_dir.is_dir():
            raise ExportValidationError("knowledge_input_directory_invalid")
        if any(Path(name).name != name for name in (args.detail_file, args.list_file)):
            raise ExportValidationError("knowledge_input_filename_invalid")
        prepared = prepare_export(
            args.input_dir / args.detail_file, args.input_dir / args.list_file, expected_count=args.expected_count,
        )
        print(json.dumps({"event": "preflight_passed", **prepared.statistics}, ensure_ascii=False), flush=True)
        if not args.commit:
            return 0
        settings = load_settings()
        database = Database(settings.database_dsn)
        if database.engine != "postgres":
            raise ExportValidationError("knowledge_postgres_required")
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        result = KnowledgeImportService(database).import_export(
            prepared, source_code=args.source_code, knowledge_base_code=args.knowledge_base_code,
            progress=lambda counts: print(json.dumps({"event": "import_progress", **counts}), flush=True),
        )
        print(json.dumps({"event": "import_completed", **result}, ensure_ascii=False), flush=True)
        return 0
    except ExportValidationError as exc:
        print(json.dumps({"event": "import_failed", "error_code": exc.code, "line": exc.line}), flush=True)
        return 1
    except SchemaHeadError:
        print('{"event":"import_failed","error_code":"knowledge_schema_head_mismatch"}', flush=True)
        return 1
    except Exception:
        # 不输出原始数据库/JSON/IO 异常，以免驱动参数或正文进入终端和日志。
        print('{"event":"import_failed","error_code":"knowledge_import_unavailable"}', flush=True)
        return 1
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
