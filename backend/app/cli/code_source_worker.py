"""Bounded SVN execution and transient result server inside existing knowledge-sync."""

from concurrent.futures import Future, ThreadPoolExecutor
import logging
import os
import re
from pathlib import Path
from threading import Event, Thread
import uuid
import time
from collections.abc import Callable

import uvicorn

from app.modules.identity.application.principal_jwt import PrincipalJwks
from app.modules.identity.application.service_principal import CodeControlServicePrincipalVerifier
from app.modules.knowledge.api.code_result_endpoint import code_result_app
from app.modules.knowledge.infrastructure.code_operation_executor import CodeOperationExecutor
from app.modules.knowledge.infrastructure.code_operation_store import CodeOperationStore
from app.modules.knowledge.infrastructure.code_checkout_jobs import CodeCheckoutJobs
from app.modules.knowledge.infrastructure.code_management_executor import CodeManagementExecutor
from app.cli.code_checkout_worker import administration
from app.modules.knowledge.infrastructure.code_result_authorizer import CodeResultAuthorizer
from app.modules.knowledge.infrastructure.code_result_buffer import CodeResultBuffer
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError

logger = logging.getLogger(__name__)


def start_code_source(stop: Event) -> Thread | None:
    if os.environ.get("CODE_CHECKOUT_ENABLED") != "true":
        return None
    worker = Thread(target=_loop, args=(stop,), name="code-source", daemon=True)
    worker.start()
    return worker


def _serve(
    database: Database, buffer: CodeResultBuffer, management: CodeCheckoutJobs
) -> tuple[uvicorn.Server, Thread]:
    verifier = CodeControlServicePrincipalVerifier(
        PrincipalJwks.from_file(os.environ["PRINCIPAL_JWKS_FILE"])
    )
    app = code_result_app(
        verifier=verifier,
        buffer=buffer,
        authorize=CodeResultAuthorizer(database, management).authorize,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8096,
            access_log=False,
            log_level="critical",
            server_header=False,
            limit_concurrency=8,
            backlog=8,
            timeout_keep_alive=1,
            timeout_graceful_shutdown=10,
        )
    )
    thread = Thread(target=server.run, name="code-source-results", daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=2)
        raise RuntimeError("Code result endpoint unavailable")
    return server, thread


def _cycle(
    executor: CodeOperationExecutor,
    management: CodeManagementExecutor,
    stop: Event,
    generation_stop: Event,
    healthy: Callable[[], bool],
) -> None:
    store = executor.store
    active: dict[str, Future[None]] = {}
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="code-svn") as pool:
        try:
            while not stop.is_set():
                if not healthy():
                    raise CodeKnowledgeError("CODE_RESULT_ENDPOINT_STOPPED")
                for identifier, future in list(active.items()):
                    if future.done():
                        try:
                            future.result()
                        except Exception:
                            # No exception text: SVN/DB failures may contain private source context.
                            logger.warning("Code SVN execution requires recovery")
                        del active[identifier]
                _release_stopped_readers(store)
                _recover_stopped_operations(store, management.store, executor.checkout_root)
                if len(active) < 4:
                    rows = store.db.execute(
                        f"SELECT id,analysis_id FROM {store.t('code_svn_operation')} WHERE state='queued' ORDER BY created_at,id LIMIT 8"
                    )
                    for row in rows:
                        if row["id"] not in active and len(active) < 4:
                            expire = (
                                store.expire_queued
                                if row["analysis_id"]
                                else management.store.expire_management
                            )
                            execute = executor.execute if row["analysis_id"] else management.execute
                            if expire(row["id"]):
                                continue
                            active[row["id"]] = pool.submit(execute, row["id"])
                stop.wait(0.5 if active else 2)
            # Executor cancellation checks terminate and wait for each child. Never
            # mark other owners stopped or recycle a running lease after mere timeout.
        finally:
            generation_stop.set()


def _release_stopped_readers(store: CodeOperationStore) -> None:
    # Job status/lease expiry alone never frees a reader. The Runtime pool must
    # first record actual SDK process/call quiescence for this exact invocation.
    from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError

    rows = store.db.execute(
        f"SELECT o.id FROM {store.t('code_analysis')} a "
        "JOIN agent_runtime_invocation i ON i.invocation_id=a.invocation_id AND i.job_id=a.job_id "
        f"JOIN {store.t('code_svn_operation')} o ON o.analysis_id=a.id AND o.request_key=a.request_key "
        "WHERE a.closed_at IS NULL AND i.execution_quiesced_at IS NOT NULL ORDER BY a.created_at LIMIT 8"
    )
    for row in rows:
        operation = store.row("code_svn_operation", row["id"])
        try:
            store.release_stopped(store.context_for(operation), operation["analysis_id"])
        except CodeKnowledgeError as exc:
            if exc.code != "CODE_EXECUTION_NOT_QUIESCED":
                raise


def _recover_stopped_operations(
    store: CodeOperationStore, management: CodeCheckoutJobs, root: Path
) -> None:
    from app.modules.agent.infrastructure.runtime_pool_store import database_now, timestamp
    from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
    from app.modules.knowledge.infrastructure.code_executor_lock import execution_lock

    rows = store.db.execute(
        f"SELECT * FROM {store.t('code_svn_operation')} WHERE state='running' AND lease_until<=? "
        "ORDER BY updated_at,id LIMIT 8",
        (timestamp(database_now(store.db)),),
    )
    for row in rows:
        try:
            with execution_lock(root, "svn", row["id"]) as proof:
                if not proof.proves_stopped(row):
                    continue
                # The inherited descriptor is closed by every local child before
                # this exclusive lock can be acquired. Never replay a mutation.
                if row["analysis_id"] is None:
                    management.fail_management(
                        row["id"],
                        owner=row["owner_instance_id"],
                        claim=row["claim_version"],
                        error="CODE_EXECUTOR_STOPPED",
                    )
                else:
                    store.stopped(
                        row["id"],
                        owner=row["owner_instance_id"],
                        claim=row["claim_version"],
                        error_code="CODE_EXECUTOR_STOPPED",
                    )
        except CodeKnowledgeError as exc:
            if exc.code not in {"CODE_EXECUTOR_STILL_RUNNING", "CODE_OPERATION_LEASE_LOST"}:
                raise


def _loop(stop: Event) -> None:
    while not stop.is_set():
        database = None
        server = None
        server_thread = None
        buffer = CodeResultBuffer()
        generation_stop = Event()
        try:
            database = Database(os.environ["DATABASE_DSN"], pool_min_size=0, pool_max_size=8)
            SchemaHeadValidator(database, default_migrations_dir()).require_current()
            executor = CodeOperationExecutor(
                CodeOperationStore(database),
                buffer,
                owner="code-svn-" + uuid.uuid4().hex,
                registry_file=Path(os.environ["CODE_CHECKOUT_REGISTRY_FILE"]),
                auth_root=Path(os.environ["CODE_SVN_AUTH_ROOT"]),
                checkout_root=Path(os.environ["CODE_CHECKOUT_ROOT"]),
                stopped=lambda: stop.is_set() or generation_stop.is_set(),
            )
            management = CodeManagementExecutor(
                CodeCheckoutJobs(database, administration(database)),
                buffer,
                owner=executor.owner,
                auth_root=executor.auth_root,
                checkout_root=executor.checkout_root,
                stopped=executor.stopping,
            )
            server, server_thread = _serve(database, buffer, management.store)
            _cycle(executor, management, stop, generation_stop, server_thread.is_alive)
        except Exception as exc:
            # A worker generation can stop without a container restart. Keep a
            # bounded category for diagnosis; never log DB/SVN exception text.
            code = (
                exc.code
                if isinstance(exc, CodeKnowledgeError)
                and re.fullmatch(r"[A-Za-z0-9_]{1,96}", exc.code)
                else "CODE_WORKER_CYCLE_FAILED"
            )
            logger.warning("Code source worker unavailable: %s (%s)", code, type(exc).__name__)
            stop.wait(10)
        finally:
            if server is not None:
                server.should_exit = True
            if server_thread is not None:
                server_thread.join(timeout=15)
            buffer.clear()
            if database is not None:
                database.close()
