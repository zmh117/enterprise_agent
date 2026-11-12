"""Eligibility for explicitly verifying a failed managed checkout without downloading."""

from typing import TYPE_CHECKING, Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.modules.knowledge.infrastructure.code_svn_access import (
    CodeSvnAccess,
    connection_fingerprint,
)

if TYPE_CHECKING:
    from app.modules.knowledge.infrastructure.code_checkout_jobs import CodeCheckoutJobs


def revalidation_target(
    store: "CodeCheckoutJobs", operation_id: str, resource_id: str, *, lock: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    original = store.row("code_svn_operation", operation_id)
    resource = store.db.execute_one(
        f"SELECT resource_id FROM {store.t('retrieval_revision')} WHERE id=?",
        (original["config_revision_id"],),
    )
    if (
        not resource
        or resource["resource_id"] != resource_id
        or original["analysis_id"] is not None
        or original["operation_kind"] != "checkout"
        or original["error_code"] == "code_checkout_destination_exists"
        or original["state"] != "failed"
        or not original["quiesced_at"]
        or not original["checkout_id"]
    ):
        raise CodeKnowledgeError("CODE_CHECKOUT_REVALIDATION_UNAVAILABLE")
    checkout = store.row("code_checkout", original["checkout_id"], lock=lock)
    latest = store.db.execute_one(
        f"SELECT id FROM {store.t('code_svn_operation')} WHERE checkout_id=? "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (checkout["id"],),
    )
    readers = store.db.execute_one(
        f"SELECT count(*) AS n FROM {store.t('code_analysis')} WHERE checkout_id=? "
        "AND read_acquired_at IS NOT NULL AND read_released_at IS NULL",
        (checkout["id"],),
    )
    if (
        not latest
        or latest["id"] != operation_id
        or checkout["state"] != "invalid"
        or checkout["writer_operation_id"]
        or (readers and readers["n"])
    ):
        raise CodeKnowledgeError("CODE_CHECKOUT_REVALIDATION_UNAVAILABLE")
    request = json_value(original["request_json"])
    entry = CodeSvnAccess(store.db, store.registry_file).entry(request["registration"], resource_id)
    repository = store.db.execute_one(
        f"SELECT repository_uuid,branch_path FROM {store.t('code_repository')} WHERE source_id=?",
        (checkout["source_id"],),
    )
    if not repository:
        raise CodeKnowledgeError("CODE_CHECKOUT_REVALIDATION_UNAVAILABLE")
    if (
        connection_fingerprint(entry) != request["registration_hash"]
        or str(repository["repository_uuid"]) != entry["repository_uuid"]
        or repository["branch_path"] != entry["branch_path"].strip("/")
        or checkout["source_id"] != original["source_id"]
        or checkout["relative_dir"] != request["folder"]
        or json_value(checkout["selected_paths_json"]) != request["paths"]
        or original["target_revision"] != request["revision"]
    ):
        raise CodeKnowledgeError("CODE_REGISTRATION_CHANGED")
    return original, checkout
