"""完整 SVN 工程检出线程；独立于代码知识采集和模型执行开关。"""

import logging
import os
import shutil
from pathlib import Path
from threading import Event, Thread

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.job.infrastructure.repositories import AuditRepository, ConfigurationRepository
from app.modules.permission.application.permission_service import PermissionService
from app.modules.knowledge.application.source_service import KnowledgeAdministration
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_checkout_client import WorkingCopyClient, registry
from app.modules.knowledge.infrastructure.code_checkout_jobs import CodeCheckoutJobs
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.storage import source_lock
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import PermissionDenied
from app.shared.migrations import SchemaHeadValidator

logger = logging.getLogger(__name__)


def administration(db: Database) -> KnowledgeAdministration:
    audit = AuditService(AuditRepository(db))
    permissions = PermissionService(
        ConfigurationRepository(db),
        authorization_evaluator=AuthorizationEvaluator(IdentityRepository(db), audit),
    )
    return KnowledgeAdministration(GovernanceStore(db), permissions, audit)


def tick(jobs: CodeCheckoutJobs, auth_root: Path, checkout_root: Path, stop: Event) -> bool:
    # A session advisory lock is held through the subprocess, including final publication.
    with source_lock(jobs.db, "code-checkout-executor"):
        for row in jobs.db.execute(f"select id from {jobs.t} where state='RUNNING'"):
            temporary = checkout_root / (".partial-" + row["id"])
            if (
                checkout_root.resolve() == checkout_root
                and temporary.is_dir()
                and not temporary.is_symlink()
            ):
                shutil.rmtree(temporary)
            jobs.update(row["id"], "INTERRUPTED", error="code_checkout_interrupted")
        pending = jobs.db.execute_one(
            f"select id from {jobs.t} where state='QUEUED' order by created_at,id limit 1"
        )
        if not pending or stop.is_set():
            return False
        job = jobs.get(pending["id"])
        jobs.update(job["id"], "RUNNING")
        try:
            jobs.admin.require_admin(job["actor_id"])
            request = job["request"]
            entry = registry(jobs.registry_file).get(request["registration"])
            if not entry or digest(entry) != request["registration_hash"]:
                raise CodeKnowledgeError("code_checkout_registration_changed")
            client = WorkingCopyClient(entry, auth_root, stop.is_set)
            if job["kind"] == "browse":
                result = client.browse(request["revision"])
            else:
                result = client.checkout(
                    root=checkout_root,
                    folder=request["folder"],
                    job_id=job["id"],
                    revision=request["revision"],
                    paths=request["paths"],
                )
            jobs.update(job["id"], "SUCCEEDED", result=result)
            jobs.admin.record(
                "code_checkout_completed",
                actor_id=job["actor_id"],
                identifier=job["id"],
                revision=result["revision"],
            )
        except Exception as exc:
            code = (
                exc.code
                if isinstance(exc, CodeKnowledgeError)
                else "code_checkout_access_denied"
                if isinstance(exc, PermissionDenied)
                else "code_checkout_failed"
            )
            jobs.update(job["id"], "INTERRUPTED" if stop.is_set() else "FAILED", error=code)
        return True


def start_code_checkout(stop: Event) -> Thread | None:
    if os.environ.get("CODE_CHECKOUT_ENABLED") != "true":
        return None
    worker = Thread(target=_loop, args=(stop,), name="code-checkout", daemon=True)
    worker.start()
    return worker


def _loop(stop: Event) -> None:
    while not stop.is_set():
        database = None
        try:
            database = Database(os.environ["DATABASE_DSN"], pool_min_size=0, pool_max_size=2)
            SchemaHeadValidator(database, default_migrations_dir()).require_current()
            jobs = CodeCheckoutJobs(database, administration(database))
            while not stop.is_set():
                if not tick(
                    jobs,
                    Path(os.environ["CODE_SVN_AUTH_ROOT"]),
                    Path(os.environ["CODE_CHECKOUT_ROOT"]),
                    stop,
                ):
                    stop.wait(2)
        except Exception:
            logger.warning("SVN checkout worker unavailable")
            stop.wait(10)
        finally:
            if database is not None:
                database.close()
