"""常驻知识计划调度；每轮使用既有 once 流程，数据与日志均有界。"""

import os
from pathlib import Path
import sys
from threading import Event

from app.cli.knowledge_database_recovery import stop_signals
from app.modules.knowledge.infrastructure.operations_scheduler import KnowledgeSyncScheduler
from app.modules.knowledge.infrastructure.operations_process import exclusive_process, run_process
from app.modules.knowledge.infrastructure.operations_repository import OperationsRepository
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def cycle(ops: OperationsRepository, stop: Event) -> None:
    scheduler = KnowledgeSyncScheduler(ops)
    operation = scheduler.select()
    ops.heartbeat("sync", {"operation_id": operation["id"] if operation else None})
    if operation is None:
        stop.wait(5)
        return
    if operation["run_id"] and scheduler.sync.run(operation["run_id"])["phase"] == "ACTIVATED":
        scheduler.finish(operation, 0, None)
        return
    operation = ops.start(operation["id"])
    error: str | None = None

    def observe(line: str) -> None:
        nonlocal error
        error = scheduler.observe(operation["id"], line) or error

    def heartbeat() -> None:
        ops.heartbeat("sync", {"operation_id": operation["id"]})

    result = run_process(
        scheduler.command(
            operation, sys.executable, os.environ.get("KNOWLEDGE_CAPACITY_PATH", "/qdrant/storage")
        ),
        stop=stop,
        heartbeat=heartbeat,
        line=observe,
        timeout=30 * 86400,
    )
    if stop.is_set():
        ops.update(operation["id"], state="QUEUED", stage="queued")
        ops.event(operation["id"], "sync", "interrupted")
    else:
        scheduler.finish(operation, result, error)


def main() -> int:
    stop = Event()
    if os.environ.get("KNOWLEDGE_SYNC_ENABLED") != "true":
        return 2
    with (
        stop_signals(stop),
        exclusive_process(Path(os.environ.get("KNOWLEDGE_STATE_DIR", "/state")) / "sync.lock"),
    ):
        while not stop.is_set():
            database = None
            try:
                database = Database(os.environ["DATABASE_DSN"])
                SchemaHeadValidator(database, default_migrations_dir()).require_current()
                ops = OperationsRepository(database)
                while not stop.is_set():
                    cycle(ops, stop)
            except Exception:
                # 子进程由 run_process finally 收束；不输出异常或连接串。
                stop.wait(10)
            finally:
                if database is not None:
                    database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
