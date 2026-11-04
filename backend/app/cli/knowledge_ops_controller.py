"""主程序侧常驻知识运维执行器；知识项目停止不会停止本服务。"""

import os
from pathlib import Path
from threading import Event

from app.cli.knowledge_database_recovery import stop_signals
from app.modules.knowledge.infrastructure.operations_compose import KnowledgeCompose
from app.modules.knowledge.infrastructure.operations_process import exclusive_process
from app.modules.knowledge.infrastructure.operations_repository import OperationsRepository
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def main() -> int:
    stop = Event()
    with (
        stop_signals(stop),
        exclusive_process(
            Path(os.environ.get("KNOWLEDGE_STATE_DIR", "/state")) / "controller.lock"
        ),
    ):
        while not stop.is_set():
            database = None
            try:
                database = Database(os.environ["DATABASE_DSN"])
                SchemaHeadValidator(database, default_migrations_dir()).require_current()
                ops = OperationsRepository(database)
                compose = KnowledgeCompose(ops, stop)
                while not stop.is_set():
                    compose.observe()
                    waiting = ops.waiting(sync=False)
                    if not waiting:
                        stop.wait(5)
                        continue
                    operation = waiting[0]
                    if operation["state"] == "RUNNING":
                        compose.reconcile(operation)
                        continue
                    operation = ops.start(operation["id"])
                    try:
                        compose.execute(operation)
                        ops.update(operation["id"], state="SUCCEEDED", stage="completed")
                        ops.event(operation["id"], "controller", "completed")
                    except Exception as exc:
                        code = getattr(exc, "error_code", None) or "knowledge_ops_failed"
                        ops.update(
                            operation["id"],
                            state="INTERRUPTED" if stop.is_set() else "FAILED",
                            stage="failed",
                            error_code=code,
                        )
                        ops.event(operation["id"], "controller", "failed", {"error_code": code})
            except Exception:
                stop.wait(10)
            finally:
                if database is not None:
                    database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
