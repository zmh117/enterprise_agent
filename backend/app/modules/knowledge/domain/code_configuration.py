"""Code-library configuration: one existing managed store and immutable source binding."""

from typing import Any

from app.modules.knowledge.domain.chunking import ChunkProfile
from app.modules.knowledge.domain.code_answers import code_path
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.storage_connection import DEFAULT_QDRANT, storage_config

CODE_CHUNK_PROFILE = ChunkProfile(
    version="code-business-answer-chunks/v1", template_version="code-business-answer-context/v1"
)
MANAGED_CODE_STORAGE = {
    "postgres": {"mode": "platform"},
    "qdrant": {"url": DEFAULT_QDRANT, "api_key_ref": ""},
}


def code_storage(value: Any = None) -> dict[str, Any]:
    selected = storage_config(MANAGED_CODE_STORAGE if value is None else value)
    if selected != MANAGED_CODE_STORAGE:
        raise CodeKnowledgeError("CODE_MANAGED_STORAGE_REQUIRED")
    return selected


def source_configuration(value: dict[str, Any]) -> dict[str, Any]:
    fields = ("source_id", "checkout_id", "svn_access_ref", "allowed_paths_json")
    if any(not value.get(key) for key in fields):
        raise CodeKnowledgeError("CODE_CONFIGURATION_INCOMPLETE")
    paths = value["allowed_paths_json"]
    if not isinstance(paths, list) or not 1 <= len(paths) <= 100:
        raise CodeKnowledgeError("CODE_SCOPE_INVALID")
    canonical = sorted({code_path(p, root=True) for p in paths})
    if len(canonical) != len(paths):
        raise CodeKnowledgeError("CODE_SCOPE_INVALID")
    return {key: canonical if key == "allowed_paths_json" else value[key] for key in fields}
