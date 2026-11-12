"""Resource administration inside knowledge-sync; no Agent or external command strings."""

from pathlib import Path
from collections.abc import Callable
from typing import Any
import re

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
from app.modules.knowledge.infrastructure.code_svn import SVN_OPERATIONS
from app.modules.agent.infrastructure.runtime_pool_store import database_now, timestamp
from app.modules.knowledge.infrastructure.code_operation_heartbeat import CodeOperationHeartbeat
from app.modules.knowledge.infrastructure.code_executor_lock import ExecutorLock


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
            self._execute_claimed(row, proof)

    def _execute_claimed(self, row: dict[str, Any], proof: ExecutorLock) -> None:
        identifier = row["id"]
        claim = row["claim_version"]
        heartbeat = CodeOperationHeartbeat(
            operation_id=identifier,
            renew=lambda: self.store.heartbeat_management(
                identifier, owner=self.owner, claim=claim
            ),
            stopped=self.stopping,
            permission_error="code_checkout_access_denied",
        )

        phase = "connection"
        client: Any = None

        def progress(value: str) -> None:
            nonlocal phase
            phase = value
            heartbeat.check()
            self.store.progress_management(identifier, owner=self.owner, claim=claim, stage=value)

        try:
            with heartbeat:
                progress("connection")
                proof.bind(row)
                heartbeat.check()
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
                    entry, self.auth_root, heartbeat.check, factory=WorkingCopyClient
                ) as client:
                    client.stage = progress
                    if row["operation_kind"] == "browse":
                        progress("browse")
                        if entry.get("resource_id"):
                            access.pin(
                                request["registration"],
                                resource,
                                repository_uuid=client.source.expected_uuid,
                                branch_path=client.source.branch_path or "/",
                            )
                        self._browse(row, request, client, heartbeat)
                    else:
                        self._checkout(row, request, client, heartbeat, progress)
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
                diagnostic=_diagnostic(
                    exc,
                    phase,
                    getattr(getattr(client, "source", None), "last_operation", "unknown"),
                ),
                directory_retained=self._retained(row, client),
            )

    def _retained(self, row: dict[str, Any], client: Any) -> bool:
        if not row["checkout_id"]:
            return False
        request = json_value(row["request_json"])
        if not (request.get("verification_only") or getattr(client, "directory_created", False)):
            return False
        path = self.checkout_root / request["folder"]
        try:
            return bool(path.resolve(strict=True) == path and path.is_dir())
        except OSError:
            return False

    def _browse(
        self,
        row: dict[str, Any],
        request: dict[str, Any],
        client: WorkingCopyClient,
        heartbeat: CodeOperationHeartbeat,
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
        heartbeat.finish()
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
        self,
        row: dict[str, Any],
        request: dict[str, Any],
        client: WorkingCopyClient,
        heartbeat: CodeOperationHeartbeat,
        progress: Callable[[str], None],
    ) -> None:
        checkout = self.store.row("code_checkout", row["checkout_id"])
        if checkout["writer_operation_id"] != row["id"]:
            raise CodeKnowledgeError("CODE_OPERATION_LEASE_LOST")
        path = self.checkout_root / checkout["relative_dir"]

        def prepared() -> None:
            heartbeat.check()
            persistent_identity(path, create=True)
            with self.store.db.unit_of_work():
                self.store.check_claim(row["id"], owner=self.owner, claim=row["claim_version"])
                self.store.identify_reserved_checkout(
                    checkout["id"], root=self.checkout_root, operation_id=row["id"]
                )

        if not request.get("verification_only"):
            client.checkout(
                root=self.checkout_root,
                folder=checkout["relative_dir"],
                job_id=row["id"],
                revision=row["target_revision"],
                paths=request["paths"],
                on_prepared=prepared,
            )
        # Legacy failed rows may lack a marker; only this explicit, exclusive revalidation
        # can establish one. Existing identities must match and may never be replaced.
        progress("verify_status")
        checkout = self.store.row("code_checkout", checkout["id"])
        physical = persistent_identity(path, create=not bool(checkout["physical_key"]))
        if checkout["physical_key"] and checkout["physical_key"] != physical:
            raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED")
        verified = SvnWorkingCopy(
            client.source, path, request["paths"], physical_key=physical, stage=progress
        ).inspect(row["target_revision"])
        metadata = {
            **verified,
            "verification_only": bool(request.get("verification_only")),
            "stage": "register",
            "checkout_id": checkout["id"],
            "relative_dir": checkout["relative_dir"],
        }
        progress("register")
        heartbeat.finish()
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


def _diagnostic(exc: Exception, stage: str, operation: str) -> dict[str, Any]:
    """Persist only enumerated labels and numeric facts, never raw output or exception text."""
    raw = exc.diagnostic if isinstance(exc, CodeKnowledgeError) and exc.diagnostic else {}
    command = raw.get("operation", operation)
    code = raw.get("exit_code")
    result: dict[str, Any] = {
        "stage": stage,
        "operation": command if command in SVN_OPERATIONS else "unknown",
        "exit_code": code if type(code) is int and -255 <= code <= 255 else None,
        "svn_error_codes": [
            v
            for v in raw.get("svn_error_codes", [])
            if isinstance(v, str) and re.fullmatch(r"E[0-9]{6}", v)
        ][:8],
    }
    if raw.get("output_stream") in {"stdout", "stderr"}:
        result["stream"] = raw["output_stream"]
    for key in ("observed_bytes", "limit_bytes"):
        if type(raw.get(key)) is int and raw[key] >= 0:
            result[key] = raw[key]
    return result
