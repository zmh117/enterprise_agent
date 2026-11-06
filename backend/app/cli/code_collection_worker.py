"""Optional independent lane owned by the existing knowledge operations process."""

import logging
import os
from pathlib import Path
from threading import Event, Thread

from app.modules.knowledge.infrastructure.code_collection_controller import CodeCollectionController
from app.modules.knowledge.infrastructure.code_source_registry import CodeSourceRegistry
from app.modules.knowledge.infrastructure.operations_process import exclusive_process
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator

logger = logging.getLogger(__name__)


def start_code_collection(stop: Event) -> Thread | None:
    if os.environ.get("CODE_COLLECTION_ENABLED") != "true":
        return None
    registry = CodeSourceRegistry(
        Path(os.environ["CODE_SVN_REGISTRY_FILE"]),
        Path(os.environ["CODE_SVN_AUTH_ROOT"]),
        cancelled=stop.is_set,
    )
    root = Path(os.environ["CODE_SOURCE_SNAPSHOT_ROOT"])
    lock = Path(os.environ.get("KNOWLEDGE_STATE_DIR", "/state")) / "code-collection.lock"
    worker = Thread(
        target=_loop, args=(stop, registry, root, lock), name="code-collection", daemon=True
    )
    worker.start()
    return worker


def _loop(stop: Event, registry: CodeSourceRegistry, root: Path, lock: Path) -> None:
    with exclusive_process(lock):
        while not stop.is_set():
            database = None
            try:
                database = Database(os.environ["DATABASE_DSN"], pool_min_size=0, pool_max_size=2)
                SchemaHeadValidator(database, default_migrations_dir()).require_current()
                controller = CodeCollectionController(database, registry, root)
                while not stop.is_set():
                    controller.tick()
                    stop.wait(5)
            except Exception:
                logger.warning("Code source collection unavailable")
                stop.wait(10)
            finally:
                if database is not None:
                    database.close()
