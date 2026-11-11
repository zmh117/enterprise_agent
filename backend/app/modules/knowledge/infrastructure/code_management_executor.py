"""Resource administration inside knowledge-sync; no Agent or external command strings."""

from pathlib import Path
from collections.abc import Callable
from typing import Any
import re
import time

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_checkout_identity import persistent_identity
from app.modules.knowledge.infrastructure.code_svn_access import (
    CodeSvnAccess,
    connection_fingerprint,
)
from app.modules.knowledge.infrastructure.code_checkout_client import WorkingCopyClient
from app.modules.knowledge.infrastructure.code_checkout_jobs import CodeCheckoutJobs
from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.modules.knowledge.infrastructure.code_result_buffer import CodeResultBuffer
from app.modules.knowledge.infrastructure.code_working_copy import SvnWorkingCopy
from app.modules.knowledge.infrastructure.code_svn import SvnCommandFailure
from app.modules.agent.infrastructure.runtime_pool_store import database_now, timestamp


class CodeManagementExecutor:
    def __init__(
        self,
        store: CodeCheckoutJobs,
        buffer: CodeResultBuffer,
        *,
        owner: str,
        auth_root: Path,
        checkout_root: Path,
        stopped: Callable[[], bool],
    ):
        self.store, self.buffer, self.owner = store, buffer, owner
        self.auth_root, self.checkout_root, self.stopping = auth_root, checkout_root, stopped

    def execute(self, identifier: str) -> None:
        from app.modules.knowledge.infrastructure.code_executor_lock import execution_lock

        with execution_lock(self.checkout_root, "svn", identifier) as proof:
            row = self.store.claim_management(identifier, owner=self.owner)
            proof.bind(row)
            self._execute_claimed(row)

    def _execute_claimed(self, row: dict[str, Any]) -> None:
        identifier = row["id"]
        claim = row["claim_version"]
        last = 0.0

        def cancelled() -> bool:
            nonlocal last
            if self.stopping():
                return True
            if time.monotonic() - last >= 3:
                try:
                    self.store.heartbeat_management(identifier, owner=self.owner, claim=claim)
                except Exception:
                    return True
                last = time.monotonic()
            return False

        try:
            request = json_value(row["request_json"])
            revision = self.store.db.execute_one(
                f"SELECT resource_id FROM {self.store.t('retrieval_revision')} WHERE id=?",
                (row["config_revision_id"],),
            )
            if not revision:
                raise CodeKnowledgeError("CODE_CONFIGURATION_CHANGED")
            resource = revision["resource_id"]
            access = CodeSvnAccess(self.store.db, self.store.registry_file)
            entry = access.entry(request["registration"], resource)
            if connection_fingerprint(entry) != request["registration_hash"]:
                raise CodeKnowledgeError("CODE_REGISTRATION_CHANGED")
            with access.client(
                entry, self.auth_root, cancelled, factory=WorkingCopyClient
            ) as client:
                if row["operation_kind"] == "browse":
                    if entry.get("resource_id"):
                        access.pin(
                            request["registration"],
                            resource,
                            repository_uuid=client.source.expected_uuid,
                            branch_path=client.source.branch_path or "/",
                        )
                    self._browse(row, request, client)
                else:
                    self._checkout(row, request, client)
        except Exception as exc:
            self.buffer.discard(identifier)
            error = (
                exc.code
                if isinstance(exc, CodeKnowledgeError)
                and re.fullmatch(r"[A-Za-z0-9_]{1,96}", exc.code)
                else "CODE_CHECKOUT_FAILED"
            )
            self.store.fail_management(
                identifier,
                owner=self.owner,
                claim=claim,
                error=error,
                diagnostic=exc.diagnostic if isinstance(exc, SvnCommandFailure) else None,
            )

    def _browse(
        self, row: dict[str, Any], request: dict[str, Any], client: WorkingCopyClient
    ) -> None:
        result = client.browse(request["revision"], path=request.get("path", ""))
        verified = client.source.preflight(result["revision"])
        result_hash = self.buffer.put(
            row["id"],
            row["claim_version"],
            result,
            deadline_at=row["deadline_at"],
            is_directory_preview=True,
        )
        with self.store.db.unit_of_work():
            self.store.require_management(row)
            source = self.store.register_repository(
                verified["repository_uuid"],
                verified["branch_path"],
                verified["repository_root_url"],
            )
            self.store.finish_management(
                row["id"],
                owner=self.owner,
                claim=row["claim_version"],
                source_id=source,
                metadata={
                    "revision": result["revision"],
                    "source_id": source,
                    "directory_count": len(result["directories"]),
                    "file_count": len(result["files"]),
                    "directory_path": request.get("path", ""),
                    "depth": "immediates",
                },
                result_hash=result_hash,
            )

    def _checkout(
        self, row: dict[str, Any], request: dict[str, Any], client: WorkingCopyClient
    ) -> None:
        checkout = self.store.row("code_checkout", row["checkout_id"])
        if checkout["writer_operation_id"] != row["id"]:
            raise CodeKnowledgeError("CODE_OPERATION_LEASE_LOST")
        client.checkout(
            root=self.checkout_root,
            folder=checkout["relative_dir"],
            job_id=row["id"],
            revision=row["target_revision"],
            paths=request["paths"],
        )
        # The directory remains preparing and exclusively owned while it is checked.
        path = self.checkout_root / checkout["relative_dir"]
        physical = persistent_identity(path, create=True)
        verified = SvnWorkingCopy(
            client.source, path, request["paths"], physical_key=physical
        ).inspect(row["target_revision"])
        metadata = {
            **verified,
            "checkout_id": checkout["id"],
            "relative_dir": checkout["relative_dir"],
        }
        with self.store.db.unit_of_work():
            self.store.row("code_checkout", checkout["id"], lock=True)
            self.store.check_claim(row["id"], owner=self.owner, claim=row["claim_version"])
            identity = self.store.identify_reserved_checkout(
                checkout["id"], root=self.checkout_root, operation_id=row["id"]
            )
            if identity != physical:
                raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED")
            self.store.finish_management(
                row["id"],
                owner=self.owner,
                claim=row["claim_version"],
                source_id=row["source_id"],
                metadata=metadata,
                result_hash=digest(metadata),
            )
            stamp = timestamp(database_now(self.store.db))
            self.store.db.execute(
                f"UPDATE {self.store.t('code_checkout')} SET state='ready',verified_revision=?,verified_at=?,writer_operation_id=NULL,updated_at=? WHERE id=?",
                (row["target_revision"], stamp, stamp, checkout["id"]),
            )
