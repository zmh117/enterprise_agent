"""本机受信运维 CLI；与 Web 使用相同队列，绝不直接启停或采集。"""

import argparse
import json
import os
from uuid import uuid4

from app.modules.knowledge.infrastructure.operations_repository import OperationsRepository
from app.modules.knowledge.infrastructure.operations_store import OperationsStore
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="知识库运维任务入口")
    parser.add_argument(
        "command",
        choices=("build", "up", "stop", "status", "logs", "sync", "backfill", "retry", "health"),
    )
    parser.add_argument("first_day", nargs="?")
    parser.add_argument("last_day", nargs="?")
    parser.add_argument("--binding-code")
    parser.add_argument("--operation-id")
    parser.add_argument("--request-key")
    parser.add_argument("--after")
    parser.add_argument("--service")
    parser.add_argument("--role", choices=("controller", "sync"), default="controller")
    args = parser.parse_args(argv)
    database = None
    try:
        database = Database(os.environ["DATABASE_DSN"])
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        ops = OperationsRepository(database)
        if args.command == "health":
            runtime = ops.runtime(args.role)
            ready = runtime["online"] and (
                args.role != "controller" or not runtime["snapshot"].get("error_code")
            )
            return 0 if ready else 1
        if args.command == "status":
            value = OperationsStore(database).snapshot()
        elif args.command == "logs":
            value = ops.events(
                operation_id=args.operation_id, service=args.service, after=args.after
            )
        elif args.command == "retry":
            value = ops.retry(args.operation_id or "")
        else:
            binding_id = None
            if args.command in {"sync", "backfill"}:
                sql = f"select id from {ops.t('sync_binding')} where enabled=1"
                parameters: tuple[str, ...] = ()
                if args.binding_code:
                    sql += " and code=?"
                    parameters = (args.binding_code,)
                plans = database.execute(sql, parameters)
                if len(plans) != 1:
                    print(json.dumps({"error_code": "knowledge_ops_select_plan"}))
                    return 2
                binding_id = plans[0]["id"]
            value = ops.submit(
                kind=args.command,
                request_key=args.request_key or uuid4().hex,
                actor_id="local:knowledge-operator",
                binding_id=binding_id,
                first_day=args.first_day,
                last_day=args.last_day,
            )
        print(json.dumps(value, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        # 不输出 argparse 之外的异常原文或数据库参数。
        code = (
            getattr(exc, "error_code", None)
            or getattr(exc, "code", None)
            or "knowledge_ops_unavailable"
        )
        print(json.dumps({"error_code": code}))
        return 1
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
