"""不可变发布配置摘要；历史摘要字节不改写，新版只覆盖所选 KB。"""

import json
from typing import Any

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.vector_contract import fingerprint


def configuration_values(
    *,
    resource_id: str,
    base_id: str,
    index: dict[str, Any],
    source_id: str,
    source_hash: str,
    members: list[dict[str, Any]],
    storage: dict[str, Any] | None,
    version: int,
) -> dict[str, Any]:
    if type(version) is not int or version not in {0, 2, 3, 4}:
        raise KnowledgeGovernanceError("knowledge_resource_config_unsupported")
    effective = (3 if storage is not None else 2) if version == 0 else version
    if effective != 4 and effective != (3 if storage is not None else 2):
        raise KnowledgeGovernanceError("knowledge_resource_config_unsupported")
    values = {
        "binding_id": None,
        "index_id": index["id"],
        "profile_hash": index["profile_hash"],
        "corpus_hash": index["corpus_hash"],
    }
    hashed = {
        "resource_id": resource_id,
        "knowledge_base_id": base_id,
        "configuration_version": effective,
        "source_id": source_id,
        "source_hash": source_hash,
        "member_ids": sorted(row["id"] for row in members),
        **values,
        "chunk_profile_hash": index["chunk_profile_hash"],
        "collection_name": index["collection_name"],
        "expected_document_count": index["expected_document_count"],
        "expected_chunk_count": index["expected_chunk_count"],
        **({"storage": storage} if storage is not None else {}),
    }
    if effective == 4:
        hashed["member_kinds"] = sorted((row["id"], row["document_kind"]) for row in members)
    values.update(config_hash=fingerprint(hashed), configuration_version=version)
    if storage is not None:
        values["storage_config_json"] = json.dumps(storage, sort_keys=True, separators=(",", ":"))
    return values
