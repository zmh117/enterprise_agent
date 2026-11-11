"""Execute admitted fixed SVN requests; source payloads live only in the response buffer."""

from collections.abc import Callable
from pathlib import Path
import re
from typing import Any
from contextlib import ExitStack
from app.modules.knowledge.infrastructure.code_svn_access import CodeSvnAccess

from app.modules.agent.infrastructure.runtime_pool_store import database_now
from app.modules.knowledge.domain.code_answers import utc_time
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import canonical_json
from app.modules.knowledge.infrastructure.code_checkout_client import WorkingCopyClient
from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.modules.knowledge.infrastructure.code_operation_store import CodeOperationStore
from app.modules.knowledge.infrastructure.code_result_buffer import CodeResultBuffer
from app.modules.knowledge.infrastructure.code_svn_history import SvnCodeHistory
from app.modules.knowledge.infrastructure.code_working_copy import SvnWorkingCopy
from app.modules.knowledge.infrastructure.code_operation_heartbeat import CodeOperationHeartbeat
from app.modules.knowledge.infrastructure.code_executor_lock import ExecutorLock


class CodeOperationExecutor:
    def __init__(
        self,
        store: CodeOperationStore,
        buffer: CodeResultBuffer,
        *,
        owner: str,
        registry_file: Path,
        auth_root: Path,
        checkout_root: Path,
        stopped: Callable[[], bool],
    ):
        self.store, self.buffer, self.owner = store, buffer, owner
        self.registry_file, self.auth_root, self.checkout_root = (
            registry_file,
            auth_root,
            checkout_root,
        )
        self.stopping = stopped

    def execute(self, operation_id: str) -> None:
        from app.modules.knowledge.infrastructure.code_executor_lock import execution_lock

        with execution_lock(self.checkout_root, "svn", operation_id) as proof:
            operation = self.store.claim(operation_id, owner=self.owner)
            self._execute_claimed(operation, proof)

    def _execute_claimed(self, operation: dict[str, Any], proof: ExecutorLock) -> None:
        store = self.store
        operation_id = operation["id"]
        claim = operation["claim_version"]
        context = store.context_for(operation)
        heartbeat = CodeOperationHeartbeat(
            operation_id=operation_id,
            renew=lambda: store.heartbeat(context, operation_id, owner=self.owner, claim=claim),
            stopped=self.stopping,
            permission_error="CODE_AUTHORIZATION_CHANGED",
        )

        cleanup = ExitStack()
        try:
            cleanup.enter_context(heartbeat)
            proof.bind(operation)
            heartbeat.check()
            client = cleanup.enter_context(self._client(operation, heartbeat.check))
            source = client.source
            source.preflight(context.revision)
            arguments = json_value(operation["request_json"])
            if operation["operation_kind"] in {"info", "update"} and not arguments.get("target"):
                checkout = store.row("code_checkout", operation["checkout_id"])
                working = SvnWorkingCopy(
                    source,
                    self.checkout_root / checkout["relative_dir"],
                    json_value(checkout["selected_paths_json"]),
                    physical_key=checkout["physical_key"],
                )
                result = (
                    working.update(
                        context.revision,
                        timeout=min(
                            1800.0,
                            (
                                utc_time(operation["deadline_at"]) - database_now(store.db)
                            ).total_seconds(),
                        ),
                    )
                    if operation["operation_kind"] == "update"
                    else working.inspect(context.revision)
                )
                heartbeat.finish()
                store.confirm_reading(
                    context, operation_id, owner=self.owner, claim=claim, metadata=result
                )
                return
            result = self._history(operation, source, arguments, context)
            heartbeat.check()
            result_hash = self.buffer.put(
                operation_id, claim, result, deadline_at=operation["deadline_at"]
            )
            metadata = dict(
                bytes=len(canonical_json(result).encode()),
                partial=bool(result.get("partial")),
                has_more=bool(result.get("has_more")),
                count=len(result.get("entries", result.get("paths", result.get("lines", [])))),
            )
            heartbeat.finish()
            store.complete_history(
                context,
                operation_id,
                owner=self.owner,
                claim=claim,
                result_hash=result_hash,
                metadata=metadata,
            )
        except Exception as exc:
            heartbeat.close()
            self.buffer.discard(operation_id)
            error = (
                exc.code
                if isinstance(exc, CodeKnowledgeError)
                and re.fullmatch(r"[A-Za-z0-9_]{1,96}", exc.code)
                else "CODE_OPERATION_FAILED"
            )
            # Every CLI helper waits for its child before raising. If DB ownership
            # was lost, retain the durable claim rather than clearing another owner.
            store.stopped(operation_id, owner=self.owner, claim=claim, error_code=error)
        finally:
            cleanup.close()

    def _client(self, operation: dict[str, Any], cancelled: Callable[[], bool]) -> Any:
        store = self.store
        row = store.db.execute_one(
            f"SELECT c.svn_access_ref,r.repository_uuid,r.branch_path FROM {store.t('code_resource_config')} c JOIN {store.t('code_repository')} r ON r.source_id=c.source_id WHERE c.revision_id=? AND c.source_id=?",
            (operation["config_revision_id"], operation["source_id"]),
        )
        if not row:
            raise CodeKnowledgeError("CODE_CONFIGURATION_CHANGED")
        revision = store.db.execute_one(
            f"SELECT resource_id FROM {store.t('retrieval_revision')} WHERE id=?",
            (operation["config_revision_id"],),
        )
        if not revision:
            raise CodeKnowledgeError("CODE_CONFIGURATION_CHANGED")
        resource = revision["resource_id"]
        access = CodeSvnAccess(store.db, self.registry_file)
        entry = access.entry(row["svn_access_ref"], resource)
        if (
            not entry
            or str(row["repository_uuid"]) != entry["repository_uuid"]
            or row["branch_path"] != entry["branch_path"].strip("/")
        ):
            raise CodeKnowledgeError("CODE_REPOSITORY_CHANGED")
        return access.client(entry, self.auth_root, cancelled, factory=WorkingCopyClient)

    def _history(
        self, operation: dict[str, Any], source: Any, arguments: dict[str, Any], context: Any
    ) -> dict[str, Any]:
        store = self.store
        config = store.db.execute_one(
            f"SELECT allowed_paths_json FROM {store.t('code_resource_config')} WHERE revision_id=?",
            (operation["config_revision_id"],),
        )
        assert config is not None
        history = SvnCodeHistory(
            source,
            paths=json_value(config["allowed_paths_json"]),
            lower=0,
            upper=context.revision,
        )
        for field in ("start_time", "end_time"):
            if field in arguments:
                arguments[field] = utc_time(arguments[field])
        handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "log": history.log,
            "diff": history.diff,
            "blame": history.blame,
        }
        if operation["operation_kind"] == "info":
            target = arguments.pop("target")
            if target == "repository":
                result = history.info(**arguments)
            else:
                checkout = store.row("code_checkout", operation["checkout_id"])
                result = SvnWorkingCopy(
                    source,
                    self.checkout_root / checkout["relative_dir"],
                    json_value(checkout["selected_paths_json"]),
                    physical_key=checkout["physical_key"],
                ).inspect(context.revision)
        else:
            if operation["operation_kind"] not in handlers:
                raise CodeKnowledgeError("CODE_OPERATION_UNSUPPORTED")
            result = handlers[operation["operation_kind"]](**arguments)
        return result
