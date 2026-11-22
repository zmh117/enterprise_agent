"""Removal of idle managed working copies by the volume-owning worker."""

from pathlib import Path
import shutil
from typing import TYPE_CHECKING, Any

from app.modules.agent.infrastructure.runtime_pool_store import database_now, timestamp
from app.modules.knowledge.domain.code_answers import code_path
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_checkout_identity import (
    CheckoutIdentity,
    local_identity,
)
from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.modules.knowledge.infrastructure.code_operation_heartbeat import CodeOperationHeartbeat

if TYPE_CHECKING:
    from app.modules.knowledge.infrastructure.code_checkout_jobs import CodeCheckoutJobs


def checkout_inventory(
    store: "CodeCheckoutJobs", checkout_id: str | None = None, *, writer: str = ""
) -> list[dict[str, Any]]:
    """Same binding and occupancy rules for the inventory, submission and execution."""
    t = store.t
    scope = " AND c.id=?" if checkout_id is not None else ""
    return store.db.execute(
        "SELECT c.id,c.source_id,c.relative_dir,c.state,c.verified_revision,c.generation,"
        "c.writer_operation_id,c.selected_paths_json,"
        f"(SELECT count(*) FROM {t('code_analysis')} a WHERE a.checkout_id=c.id "
        "AND a.read_acquired_at IS NOT NULL AND a.read_released_at IS NULL) AS readers,"
        f"CASE WHEN EXISTS (SELECT 1 FROM {t('code_resource_config')} b JOIN {t('retrieval_resource')} r "
        "ON b.revision_id IN (r.draft_revision_id,r.published_revision_id) "
        "WHERE r.status<>'archived' AND b.checkout_id=c.id) "
        "THEN 'CODE_CHECKOUT_BOUND' "
        "WHEN (c.writer_operation_id IS NOT NULL AND c.writer_operation_id<>?) "
        f"OR EXISTS (SELECT 1 FROM {t('code_analysis')} a WHERE a.checkout_id=c.id AND "
        "(a.closed_at IS NULL OR (a.read_acquired_at IS NOT NULL AND a.read_released_at IS NULL))) "
        f"OR EXISTS (SELECT 1 FROM {t('code_svn_operation')} o WHERE o.checkout_id=c.id AND o.id<>? AND "
        "(o.state IN ('queued','running') OR (o.started_at IS NOT NULL AND o.quiesced_at IS NULL))) "
        "THEN 'WORKSPACE_BUSY' WHEN c.physical_key IS NULL THEN 'CODE_CHECKOUT_IDENTITY_CHANGED' "
        f"ELSE NULL END AS removal_blocker FROM {t('code_checkout')} c "
        "WHERE c.root_key='code-svn-checkout' AND c.state<>'retired'"
        + scope
        + " ORDER BY c.relative_dir LIMIT 1000",
        (writer, writer, checkout_id) if checkout_id is not None else (writer, writer),
    )


def removable_checkout(
    store: "CodeCheckoutJobs", identifier: str, *, writer: str = "", missing_only: bool = False
) -> dict[str, Any]:
    checkout = store.row("code_checkout", identifier, lock=True)
    rows = checkout_inventory(store, identifier, writer=writer)
    if not rows:
        raise CodeKnowledgeError("CODE_OBJECT_NOT_FOUND")
    blocker = rows[0]["removal_blocker"]
    if blocker and not (missing_only and blocker == "CODE_CHECKOUT_IDENTITY_CHANGED"):
        raise CodeKnowledgeError(blocker)
    return checkout


def _entry_exists(path: Path) -> bool:
    # A dangling link is present. Permission and storage errors must propagate.
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _both_absent(source: Path, staged: Path) -> bool:
    local_identity(staged.parent)
    if _entry_exists(staged):
        return False
    local_identity(source.parent)
    return not _entry_exists(source)


def _stage_checkout(source: Path, staged: Path, physical_key: str) -> str:
    if not _entry_exists(staged):
        identity = CheckoutIdentity(source, physical_key)
        source.rename(staged)
        if local_identity(staged) != identity.local:
            raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED")
    # A previous attempt may have renamed the directory before its receipt committed.
    return digest(list(CheckoutIdentity(staged, physical_key).local))


def remove_checkout(
    store: "CodeCheckoutJobs",
    root: Path,
    operation: dict[str, Any],
    heartbeat: CodeOperationHeartbeat,
) -> None:
    identifier = operation["id"]
    checkout_id = operation["checkout_id"]
    claim = dict(owner=operation["owner_instance_id"], claim=operation["claim_version"])
    # The executor's private directory is on the same volume. A receipt survives
    # interruption even if recursive removal has already unlinked the SVN marker.
    staged = root / ".executor-locks" / ("retire-" + digest(checkout_id))
    missing_only = json_value(operation["request_json"]).get("missing_only", False)
    with store.db.unit_of_work():
        checkout = removable_checkout(
            store, checkout_id, writer=identifier, missing_only=missing_only
        )
        store.check_claim(identifier, **claim)
        store.require_management(operation)
        if (
            checkout["writer_operation_id"] != identifier
            or checkout["generation"] != operation["checkout_generation"]
        ):
            raise CodeKnowledgeError("CODE_OPERATION_LEASE_LOST")
        folder = code_path(checkout["relative_dir"])
        if (
            folder.split("/")[0] == ".executor-locks"
            or staged.parent.resolve(strict=True) != staged.parent
        ):
            raise CodeKnowledgeError("CODE_CHECKOUT_PATH_INVALID")
        receipt = store.db.execute_one(
            f"SELECT result_json ->> 'detached_identity' AS detached_identity FROM {store.t('code_svn_operation')} WHERE checkout_id=? "
            "AND operation_kind='retire' AND (result_json ->> 'detached_identity') IS NOT NULL ORDER BY created_at DESC LIMIT 1",
            (checkout_id,),
        )
        source = root / folder
        already_absent = (missing_only or receipt is None) and _both_absent(source, staged)
        if missing_only and not already_absent:
            raise CodeKnowledgeError("CODE_CHECKOUT_DIRECTORY_PRESENT")
        if not already_absent:
            key = (
                receipt["detached_identity"]
                if receipt
                else _stage_checkout(source, staged, checkout["physical_key"])
            )
            if _entry_exists(staged) and digest(list(local_identity(staged))) != key:
                raise CodeKnowledgeError("CODE_CHECKOUT_IDENTITY_CHANGED")
            store.db.execute(
                f"UPDATE {store.t('code_svn_operation')} SET result_json=? WHERE id=?",
                (
                    canonical_json(
                        {
                            "stage": "remove_checkout",
                            "relative_dir": folder,
                            "detached_identity": key,
                        }
                    ),
                    identifier,
                ),
            )
    heartbeat.check()
    if not already_absent and _entry_exists(staged):
        shutil.rmtree(staged)
    heartbeat.finish()
    with store.db.unit_of_work():
        store.row("code_checkout", checkout_id, lock=True)
        result: dict[str, Any] = {"relative_dir": folder}
        if already_absent:
            if not _both_absent(source, staged):
                raise CodeKnowledgeError("CODE_CHECKOUT_DIRECTORY_PRESENT")
            result["directory_already_absent"] = True
        store.finish_management(
            identifier,
            source_id=checkout["source_id"],
            metadata=result,
            result_hash=digest(result),
            **claim,
        )
        store.db.execute(
            f"UPDATE {store.t('code_checkout')} SET state='retired',root_key=?,physical_key=NULL,"
            "writer_operation_id=NULL,invalid_reason=NULL,updated_at=? WHERE id=?",
            ("retired/" + checkout_id, timestamp(database_now(store.db)), checkout_id),
        )
