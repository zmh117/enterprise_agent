"""Code-resource-scoped management operations; shares the SVN operation ledger."""

import os
from pathlib import Path
from datetime import timedelta
from typing import Any

from app.modules.agent.infrastructure.runtime_pool_store import database_now, timestamp
from app.modules.knowledge.application.source_service import KnowledgeAdministration
from app.modules.knowledge.domain.code_answers import svn_revision
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_checkout_client import (
    FOLDER,
    registered_url,
    registry,
)
from app.modules.knowledge.infrastructure.code_checkout_store import checkout_scope, json_value
from app.modules.knowledge.infrastructure.code_operation_store import CodeOperationStore
from app.modules.knowledge.infrastructure.storage import insert, source_lock
from app.shared.database import Database


class CodeCheckoutJobs(CodeOperationStore):
    def __init__(
        self, db: Database, admin: KnowledgeAdministration, registry_file: Path | None = None
    ):
        super().__init__(db)
        self.admin = admin
        self.registry_file = registry_file or Path(
            os.environ.get("CODE_CHECKOUT_REGISTRY_FILE", "/etc/code-svn/checkout.json")
        )

    def draft(self, resource_id: str, *, lock: bool = False) -> dict[str, Any]:
        suffix = " FOR UPDATE OF r" if lock and self.db.engine == "postgres" else ""
        row = self.db.execute_one(
            f"SELECT c.*,r.id AS resource_id,r.knowledge_base_id FROM {self.t('retrieval_resource')} r "
            f"JOIN {self.t('knowledge_base')} b ON b.id=r.knowledge_base_id "
            f"JOIN {self.t('code_resource_config')} c ON c.revision_id=r.draft_revision_id "
            "WHERE r.id=? AND b.kind='code' AND r.status<>'archived'" + suffix,
            (resource_id,),
        )
        if not row:
            raise CodeKnowledgeError("CODE_DRAFT_REQUIRED")
        return row

    def get(self, job_id: str) -> dict[str, Any]:
        row = self.row("code_svn_operation", job_id)
        # This route is only for resource administration, not another user's QA history.
        if row["analysis_id"] is not None or row["operation_kind"] not in {"browse", "checkout"}:
            raise CodeKnowledgeError("CODE_OBJECT_NOT_FOUND")
        row["request"] = json_value(row.pop("request_json"))
        row["result"] = json_value(row.pop("result_json"))
        return row

    def snapshot(self, resource_id: str) -> dict[str, Any]:
        rows = self.db.execute(
            f"SELECT o.id,o.operation_kind,o.state,o.error_code,o.created_at,o.result_json FROM {self.t('code_svn_operation')} o "
            f"JOIN {self.t('retrieval_revision')} v ON v.id=o.config_revision_id "
            "WHERE v.resource_id=? AND o.analysis_id IS NULL ORDER BY o.created_at DESC,o.id DESC LIMIT 30",
            (resource_id,),
        )
        for row in rows:
            row["result"] = json_value(row.pop("result_json"))
        checkouts = self.db.execute(
            f"SELECT id,source_id,relative_dir,state,verified_revision,generation,writer_operation_id,selected_paths_json FROM {self.t('code_checkout')} ORDER BY relative_dir LIMIT 1000"
        )
        for checkout in checkouts:
            checkout["selected_paths"] = json_value(checkout.pop("selected_paths_json"))
            readers = self.db.execute_one(
                f"SELECT count(*) AS n FROM {self.t('code_analysis')} WHERE checkout_id=? AND read_acquired_at IS NOT NULL AND read_released_at IS NULL",
                (checkout["id"],),
            )
            checkout["readers"] = readers["n"] if readers else 0
        enabled = os.environ.get("CODE_CHECKOUT_ENABLED") == "true"
        return {
            "enabled": enabled,
            "registrations": [
                {"id": key, "url": entry["public_url"]}
                for key, entry in registry(self.registry_file).items()
            ]
            if enabled
            else [],
            "jobs": rows,
            "checkouts": checkouts,
        }

    def submit_browse(
        self, *, actor_id: str, resource_id: str, url: str, revision: int | None, request_key: str
    ) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        key, entry = registered_url(self.registry_file, url)
        if revision is not None:
            svn_revision(revision)
        return self._submit(
            actor_id,
            resource_id,
            request_key,
            "browse",
            {
                "registration": key,
                "registration_hash": digest(entry),
                "revision": revision,
                "public_url": entry["public_url"],
            },
        )

    def submit_checkout(
        self,
        *,
        actor_id: str,
        resource_id: str,
        browse_job_id: str,
        paths: list[str],
        folder: str,
        request_key: str,
    ) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        browse = self.get(browse_job_id)
        draft = self.draft(resource_id)
        if (
            browse["actor_id"] != actor_id
            or browse["operation_kind"] != "browse"
            or browse["state"] != "succeeded"
            or not browse["source_id"]
            or browse["config_revision_id"] != draft["revision_id"]
        ):
            raise CodeKnowledgeError("CODE_CHECKOUT_BROWSE_REQUIRED")
        if not isinstance(folder, str) or not FOLDER.fullmatch(folder):
            raise CodeKnowledgeError("CODE_CHECKOUT_DESTINATION_INVALID")
        return self._submit(
            actor_id,
            resource_id,
            request_key,
            "checkout",
            {
                **browse["request"],
                "revision": browse["result"]["revision"],
                "paths": checkout_scope(paths),
                "folder": folder,
                "browse_job_id": browse_job_id,
            },
            source_id=browse["source_id"],
        )

    def _submit(
        self,
        actor: str,
        resource: str,
        key: str,
        kind: str,
        request: dict[str, Any],
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        if os.environ.get("CODE_CHECKOUT_ENABLED") != "true":
            raise CodeKnowledgeError("CODE_CHECKOUT_DISABLED")
        if not isinstance(key, str) or not FOLDER.fullmatch(key):
            raise CodeKnowledgeError("CODE_REQUEST_INVALID")
        with source_lock(self.db, "code-management-submit"), self.db.unit_of_work():
            self.admin.require_admin(actor)
            draft = self.draft(resource, lock=True)
            request_hash = digest([actor, resource, draft["revision_id"], kind, request])
            request_key = stable_id("code-management-request", actor, key)
            prior = self.db.execute_one(
                f"SELECT id,request_hash FROM {self.t('code_svn_operation')} WHERE request_key=?",
                (request_key,),
            )
            if prior:
                if prior["request_hash"] != request_hash:
                    raise CodeKnowledgeError("CODE_IDEMPOTENCY_CONFLICT")
                return self.get(prior["id"])
            count = self.db.execute_one(
                f"SELECT count(*) AS n FROM {self.t('code_svn_operation')} WHERE analysis_id IS NULL AND state IN ('queued','running')"
            )
            if count and count["n"] >= 20:
                raise CodeKnowledgeError("CODE_OPERATION_BUSY")
            checkout = None
            if kind == "checkout":
                assert source_id is not None
                checkout = self.reserve_checkout(
                    source_id=source_id,
                    relative_dir=request["folder"],
                    selected_paths=request["paths"],
                )
            identifier = stable_id("code-management-operation", request_key)
            current = database_now(self.db)
            stamp = timestamp(current)
            insert(
                self.db,
                "code_svn_operation",
                dict(
                    id=identifier,
                    source_id=source_id,
                    checkout_id=checkout["id"] if checkout else None,
                    actor_id=actor,
                    config_revision_id=draft["revision_id"],
                    operation_kind=kind,
                    request_key=request_key,
                    request_hash=request_hash,
                    state="queued",
                    request_json=request,
                    target_revision=request["revision"],
                    checkout_generation=1 if checkout else None,
                    deadline_at=timestamp(current + timedelta(seconds=1800 if checkout else 120)),
                    created_at=stamp,
                    updated_at=stamp,
                ),
            )
            if checkout:
                self.db.execute(
                    f"UPDATE {self.t('code_checkout')} SET writer_operation_id=?,generation=1 WHERE id=?",
                    (identifier, checkout["id"]),
                )
            self.admin.record(
                "code_checkout_queued",
                actor_id=actor,
                identifier=identifier,
                revision=request["revision"] or 0,
            )
            return self.get(identifier)

    def require_management(self, operation: dict[str, Any]) -> None:
        self.admin.require_admin(operation["actor_id"])
        row = self.db.execute_one(
            f"SELECT r.id FROM {self.t('retrieval_resource')} r JOIN {self.t('knowledge_base')} b ON b.id=r.knowledge_base_id WHERE r.draft_revision_id=? AND b.kind='code' AND r.status<>'archived'",
            (operation["config_revision_id"],),
        )
        if not row or operation["analysis_id"] is not None:
            raise CodeKnowledgeError("CODE_CONFIGURATION_CHANGED")

    def claim_management(self, identifier: str, *, owner: str) -> dict[str, Any]:
        observed = self.get(identifier)
        with self.db.unit_of_work():
            if observed["checkout_id"]:
                self.row("code_checkout", observed["checkout_id"], lock=True)
            row = self.row("code_svn_operation", identifier, lock=True)
            self.require_management(row)
            current = database_now(self.db)
            from app.modules.knowledge.domain.code_answers import utc_time

            if row["state"] != "queued" or utc_time(row["deadline_at"]) <= current:
                raise CodeKnowledgeError("CODE_OPERATION_NOT_CLAIMABLE")
            self.db.execute(
                f"UPDATE {self.t('code_svn_operation')} SET state='running',owner_instance_id=?,claim_version=claim_version+1,lease_until=?,started_at=?,updated_at=? WHERE id=?",
                (
                    owner,
                    timestamp(min(current + timedelta(seconds=30), utc_time(row["deadline_at"]))),
                    timestamp(current),
                    timestamp(current),
                    identifier,
                ),
            )
            return self.row("code_svn_operation", identifier)

    def heartbeat_management(self, identifier: str, *, owner: str, claim: int) -> None:
        from app.modules.knowledge.domain.code_answers import utc_time

        with self.db.unit_of_work():
            row = self.check_claim(identifier, owner=owner, claim=claim)
            self.require_management(row)
            if row["checkout_id"]:
                checkout = self.row("code_checkout", row["checkout_id"])
                if (
                    checkout["writer_operation_id"] != identifier
                    or checkout["generation"] != row["checkout_generation"]
                ):
                    raise CodeKnowledgeError("CODE_OPERATION_LEASE_LOST")
            current = database_now(self.db)
            self.db.execute(
                f"UPDATE {self.t('code_svn_operation')} SET lease_until=?,updated_at=? WHERE id=?",
                (
                    timestamp(min(current + timedelta(seconds=30), utc_time(row["deadline_at"]))),
                    timestamp(current),
                    identifier,
                ),
            )

    def fail_management(self, identifier: str, *, owner: str, claim: int, error: str) -> None:
        # Called only by this claim after every child process has been waited on.
        observed = self.get(identifier)
        with self.db.unit_of_work():
            if observed["checkout_id"]:
                self.row("code_checkout", observed["checkout_id"], lock=True)
            row = self.row("code_svn_operation", identifier, lock=True)
            if (
                row["state"] != "running"
                or row["owner_instance_id"] != owner
                or row["claim_version"] != claim
            ):
                raise CodeKnowledgeError("CODE_OPERATION_LEASE_LOST")
            stamp = timestamp(database_now(self.db))
            self.db.execute(
                f"UPDATE {self.t('code_svn_operation')} SET state='failed',quiesced_at=?,finished_at=?,updated_at=?,error_code=? WHERE id=?",
                (stamp, stamp, stamp, error, identifier),
            )
            if row["checkout_id"]:
                self.db.execute(
                    f"UPDATE {self.t('code_checkout')} SET state='invalid',writer_operation_id=NULL,invalid_reason=?,updated_at=? WHERE id=? AND writer_operation_id=?",
                    (error, stamp, row["checkout_id"], identifier),
                )

    def finish_management(
        self,
        identifier: str,
        *,
        owner: str,
        claim: int,
        source_id: str,
        metadata: dict[str, Any],
        result_hash: str,
    ) -> None:
        from app.modules.knowledge.domain.normalization import canonical_json

        row = self.check_claim(identifier, owner=owner, claim=claim)
        self.require_management(row)
        stamp = timestamp(database_now(self.db))
        self.db.execute(
            f"UPDATE {self.t('code_svn_operation')} SET state='succeeded',source_id=?,result_json=?,result_hash=?,quiesced_at=?,finished_at=?,updated_at=? WHERE id=?",
            (source_id, canonical_json(metadata), result_hash, stamp, stamp, stamp, identifier),
        )

    def expire_management(self, identifier: str) -> bool:
        from app.modules.knowledge.domain.code_answers import utc_time

        observed = self.get(identifier)
        with self.db.unit_of_work():
            if observed["checkout_id"]:
                self.row("code_checkout", observed["checkout_id"], lock=True)
            row = self.row("code_svn_operation", identifier, lock=True)
            if row["state"] != "queued" or utc_time(row["deadline_at"]) > database_now(self.db):
                return False
            if row["started_at"] is not None or row["owner_instance_id"] is not None:
                raise CodeKnowledgeError("CODE_EXECUTION_NOT_QUIESCED")
            stamp = timestamp(database_now(self.db))
            self.db.execute(
                f"UPDATE {self.t('code_svn_operation')} SET state='cancelled',quiesced_at=?,finished_at=?,updated_at=?,error_code='CODE_OPERATION_EXPIRED' WHERE id=?",
                (stamp, stamp, stamp, identifier),
            )
            if row["checkout_id"]:
                self.db.execute(
                    f"UPDATE {self.t('code_checkout')} SET state='invalid',writer_operation_id=NULL,invalid_reason='CODE_OPERATION_EXPIRED',updated_at=? WHERE id=? AND writer_operation_id=?",
                    (stamp, row["checkout_id"], identifier),
                )
            return True
