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
    code_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if type(version) is not int or version not in {0, 2, 3, 4, 5}:
        raise KnowledgeGovernanceError("knowledge_resource_config_unsupported")
    effective = (3 if storage is not None else 2) if version == 0 else version
    if effective not in {4, 5} and effective != (3 if storage is not None else 2):
        raise KnowledgeGovernanceError("knowledge_resource_config_unsupported")
    incremental = index.get("incremental") == 1
    if effective == 5:
        from app.modules.knowledge.domain.code_configuration import (
            code_storage,
            source_configuration,
        )

        if not incremental or code_config is None:
            raise KnowledgeGovernanceError("knowledge_resource_config_unsupported")
        code_storage(storage)
        code_config = source_configuration(code_config)
        if code_config["source_id"] != source_id:
            raise KnowledgeGovernanceError("knowledge_source_changed")
    elif code_config is not None:
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
        **({"code_configuration": code_config} if effective == 5 else {}),
        **(
            {"content_contract": "incremental/v1"}
            if incremental
            else {
                "source_hash": source_hash,
                "member_ids": sorted(row["id"] for row in members),
            }
        ),
        **values,
        "chunk_profile_hash": index["chunk_profile_hash"],
        "collection_name": index["collection_name"],
        **(
            {}
            if incremental
            else {
                "expected_document_count": index["expected_document_count"],
                "expected_chunk_count": index["expected_chunk_count"],
            }
        ),
        **({"storage": storage} if storage is not None else {}),
    }
    if effective == 4 and not incremental:
        hashed["member_kinds"] = sorted((row["id"], row["document_kind"]) for row in members)
    values.update(config_hash=fingerprint(hashed), configuration_version=version)
    if storage is not None:
        values["storage_config_json"] = json.dumps(storage, sort_keys=True, separators=(",", ":"))
    return values
