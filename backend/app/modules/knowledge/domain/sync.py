"""同步候选的纯规则：显式分类、语义内容与来源观察水位分离。"""

from copy import deepcopy
from typing import Any

from app.modules.knowledge.domain.normalization import ExportValidationError, digest, identifier
from app.modules.knowledge.domain.work_items import DOCUMENT_KINDS


PHASES = ("COLLECTING", "STAGED", "CHUNKING", "INDEXING", "VERIFIED", "ACTIVATED")
VALUE_FIELDS = (
    "title",
    "body_text",
    "source_project_id",
    "source_project_name",
    "source_status_id",
    "source_status_name",
    "source_created_at",
    "source_snapshot",
    "attributes",
    "completeness",
    "normalizer_version",
)
REPLACE_TEST_SNAPSHOT = "replace-three-kb-test-snapshot/v1"


def replacement_manifest(manifests: dict[str, Any]) -> bool:
    markers = {m.get("operation") for m in manifests.values()}
    if markers == {None}:
        return False
    if (
        markers != {REPLACE_TEST_SNAPSHOT}
        or set(manifests) != DOCUMENT_KINDS
        or any(m.get("export_format") != "keep_ids_v1" for m in manifests.values())
        or len({m.get("source_identity_hash") for m in manifests.values()}) != 1
        or any(not m.get("source_identity_hash") for m in manifests.values())
    ):
        raise ExportValidationError("knowledge_replacement_scope_invalid")
    return True


def semantic_hash(values: dict[str, Any]) -> str:
    # 仅排除明确的来源更新时间，不递归忽略其他业务时间字段。
    semantic = deepcopy({key: values[key] for key in VALUE_FIELDS})
    semantic["source_snapshot"]["detail"].pop("server_update_stamp", None)
    return digest(semantic)


def checked_configuration(configuration: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(configuration, dict) or set(configuration) != {"base_codes", "resource_ids"}:
        raise ExportValidationError("knowledge_sync_configuration_invalid")
    bases, resources = configuration["base_codes"], configuration["resource_ids"]
    if (
        not isinstance(bases, dict)
        or set(bases) != DOCUMENT_KINDS
        or not isinstance(resources, list)
        or len(resources) > 100
    ):
        raise ExportValidationError("knowledge_sync_configuration_invalid")
    for code in (*bases.values(), *resources):
        identifier(code)
    if len(set(bases.values())) != 3 or len(set(resources)) != len(resources):
        raise ExportValidationError("knowledge_sync_configuration_invalid")
    return {"base_codes": dict(sorted(bases.items())), "resource_ids": sorted(resources)}


def candidate_members(
    baseline: dict[str, str],
    *,
    kind: str,
    old_kind: str,
    base_ids: dict[str, str],
) -> dict[str, str]:
    result = dict(baseline)
    if old_kind != kind and base_ids[old_kind] in result:
        result[base_ids[old_kind]] = "removed"
    result[base_ids[kind]] = "included"
    return result


def next_phase(current: str, requested: str) -> None:
    if (
        current not in PHASES
        or requested not in PHASES
        or PHASES.index(requested) != PHASES.index(current) + 1
    ):
        raise ExportValidationError("knowledge_sync_phase_invalid")
