"""Code answer indexing inside knowledge-sync, independent of ONES collection schedules."""

from contextlib import ExitStack
import logging
import os
from pathlib import Path
from threading import Event, Thread
import uuid

from app.modules.agent.infrastructure.runtime_pool_store import database_now, timestamp
from app.modules.knowledge.infrastructure.code_index_store import CodeIndexStore
from app.modules.knowledge.infrastructure.code_index_executor import CodeIndexExecutor
from app.modules.knowledge.infrastructure.vector_clients import EmbeddingClient, QdrantClient
from app.modules.knowledge.infrastructure.code_executor_lock import execution_lock
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator

logger = logging.getLogger(__name__)


def recover_stopped_indexing(store: CodeIndexStore, root: Path) -> None:
    rows = store.db.execute(
        f"SELECT * FROM {store.t('code_index_task')} WHERE state='running' AND lease_until<? "
        "ORDER BY updated_at,id LIMIT 8",
        (timestamp(database_now(store.db)),),
    )
    for row in rows:
        try:
            with execution_lock(root, "index", row["id"]) as proof:
                if proof.proves_stopped(row):
                    store.stopped(row, "CODE_INDEX_WORKER_STOPPED")
        except CodeKnowledgeError as exc:
            if exc.code != "CODE_EXECUTOR_STILL_RUNNING":
                raise


def start_code_indexing(stop: Event) -> Thread:
    worker = Thread(target=_loop, args=(stop,), name="code-answer-index", daemon=True)
    worker.start()
    return worker


def _loop(stop: Event) -> None:
    owner = "code-index-" + uuid.uuid4().hex
    while not stop.is_set():
        try:
            with ExitStack() as cleanup:
                database = Database(os.environ["DATABASE_DSN"], pool_min_size=0, pool_max_size=2)
                cleanup.callback(database.close)
                SchemaHeadValidator(database, default_migrations_dir()).require_current()
                embedding, qdrant = EmbeddingClient(), QdrantClient()
                cleanup.callback(embedding.http.close)
                cleanup.callback(qdrant.http.close)
                store = CodeIndexStore(database)
                root = Path(
                    os.environ.get("CODE_CHECKOUT_ROOT", "/var/lib/code-svn/checkout")
                ).resolve(strict=True)
                executor = CodeIndexExecutor(
                    store,
                    embedding,
                    qdrant,
                    owner=owner,
                    execution_root=root,
                    cancelled=stop.is_set,
                )
                while not stop.is_set():
                    recover_stopped_indexing(store, root)
                    rows = database.execute(
                        f"SELECT t.id FROM {store.t('code_index_task')} t "
                        f"JOIN {store.t('vector_index')} i ON i.id=t.index_id "
                        f"JOIN {store.t('knowledge_base')} k ON k.id=i.knowledge_base_id "
                        "WHERE k.code_indexing_paused=false AND (t.state='queued' OR "
                        "(t.state='failed' AND t.next_attempt_at IS NOT NULL AND t.next_attempt_at<=?)) "
                        "ORDER BY t.created_at,t.id LIMIT 16",
                        (timestamp(database_now(database)),),
                    )
                    progressed = False
                    for row in rows:
                        if stop.is_set():
                            break
                        progressed = executor.execute(row["id"]) or progressed
                    stop.wait(0.1 if progressed else 2)
        except Exception:
            # Do not log database URLs, answer text, or raw model/vector responses.
            logger.warning("Code answer indexing requires recovery")
            stop.wait(10)
