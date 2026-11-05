"""知识运维的固定操作与安全事件边界。"""

from datetime import UTC, datetime
import re
from typing import Any

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError

DEPLOY_ACTIONS = frozenset({"build", "up", "stop"})
SYNC_ACTIONS = frozenset({"sync", "backfill"})
ACTIVE_STATES = frozenset({"QUEUED", "RUNNING", "RETRY_WAIT"})
RETRYABLE = frozenset(
    {
        "knowledge_collection_provider_unavailable",
        "knowledge_collection_rate_limited",
        "knowledge_embedding_busy",
        "knowledge_embedding_unavailable",
        "knowledge_embedding_read_timeout",
        "knowledge_vector_unavailable",
        "knowledge_vector_timeout",
    }
)
SERVICES = (
    "knowledge-qdrant",
    "knowledge-embedding",
    "knowledge-embedding-online",
    "knowledge-reranker",
    "knowledge-mcp",
    "knowledge-sync",
)
EVENT_CODES = frozenset(
    {
        "queued",
        "started",
        "completed",
        "failed",
        "interrupted",
        "retry_pending",
        "preflight",
        "building",
        "build_step",
        "models",
        "starting",
        "ready",
        "stopping_sync",
        "stopping_services",
        "stopped",
        "sync_progress",
        "sync_event",
        "schedule_changed",
        "configuration_saved",
        "reconciled",
        "service_state",
    }
)
COUNT_FIELDS = frozenset(
    {
        "processed",
        "total",
        "encoded",
        "reused",
        "verified",
        "completed",
        "failed",
        "step",
        "stage_step",
        "stage_total",
        "attempt",
    }
)
ID_FIELDS = frozenset(
    {
        "run_id",
        "document_id",
        "binding_id",
        "version",
        "error_code",
        "phase",
        "event_id",
        "source_id",
        "external_id",
        "old_revision_id",
        "new_revision_id",
        "old_semantic_hash",
        "new_semantic_hash",
        "old_kind",
        "new_kind",
        "outcome",
        "reason",
    }
)
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
BUILD_ACTIONS = frozenset(
    {
        "load_build_definition",
        "load_build_context",
        "load_ignore_rules",
        "load_image_metadata",
        "registry_auth",
        "prepare_base_image",
        "copy_dependency_manifests",
        "copy_model_configuration",
        "copy_application_code",
        "copy_files",
        "install_python_dependencies",
        "install_system_packages",
        "configure_runtime_user",
        "configure_permissions",
        "run_python_script",
        "run_build_command",
        "configure_workdir",
        "configure_environment",
        "configure_entrypoint",
        "configure_image",
        "export_image",
        "resolve_provenance",
        "other_build_step",
    }
)


def invalid(code: str = "knowledge_ops_input_invalid") -> KnowledgeGovernanceError:
    return KnowledgeGovernanceError(code)


def safe_details(value: dict[str, Any]) -> dict[str, Any]:
    """丢弃未声明字段；原始业务内容、异常和终端输出不进入事件存储。"""
    return {
        key: item
        for key, item in value.items()
        if (key in COUNT_FIELDS and type(item) is int and 0 <= item <= 10**12)
        or (key in {"old_stamp", "new_stamp"} and type(item) is int and 0 <= item <= 10**20)
        or (key in ID_FIELDS and isinstance(item, str) and SAFE_ID.fullmatch(item))
        or (key == "build_action" and isinstance(item, str) and item in BUILD_ACTIONS)
    }


def fresh(stamp: str | None, seconds: int = 60) -> bool:
    if not stamp:
        return False
    try:
        elapsed = (datetime.now(UTC) - datetime.fromisoformat(stamp)).total_seconds()
        return 0 <= elapsed < seconds
    except (ValueError, TypeError):
        return False
