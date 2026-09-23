"""同步候选的纯规则：显式分类、语义内容与来源观察水位分离。"""

from copy import deepcopy
from datetime import date
import re
from typing import Any
from urllib.parse import urlsplit

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
_PLATFORM_SECRET_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


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
    if not isinstance(configuration, dict) or set(configuration) not in (
        {"base_codes", "resource_ids"},
        {"base_codes", "resource_ids", "collector"},
    ):
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
    result: dict[str, Any] = {
        "base_codes": dict(sorted(bases.items())),
        "resource_ids": sorted(resources),
    }
    if "collector" in configuration:
        result["collector"] = checked_collector(configuration["collector"])
    return result


def checked_collector(value: Any) -> dict[str, Any]:
    """仅持久化目标、范围与凭据引用；绝不接收 Token 或密码。"""
    keys = {
        "provider_origin",
        "team_id",
        "project_ids",
        "issue_types",
        "child_type_ids",
        "first_date",
        "credential_ref",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise ExportValidationError("knowledge_collection_configuration_invalid")
    origin = value["provider_origin"]
    if not isinstance(origin, str):
        raise ExportValidationError("knowledge_collection_configuration_invalid")
    try:
        parsed = urlsplit(origin)
        parsed_port = parsed.port
    except ValueError:
        raise ExportValidationError("knowledge_collection_configuration_invalid") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed_port is not None
        and parsed_port < 1
    ):
        raise ExportValidationError("knowledge_collection_configuration_invalid")
    projects, types, children = (
        value["project_ids"],
        value["issue_types"],
        value["child_type_ids"],
    )
    if (
        not isinstance(projects, list)
        or not projects
        or len(projects) > 100
        or not isinstance(types, dict)
        or set(types) != DOCUMENT_KINDS
        or not isinstance(children, list)
        or not children
    ):
        raise ExportValidationError("knowledge_collection_configuration_invalid")
    for values in (*types.values(), children):
        if not isinstance(values, list) or not values or len(values) > 20:
            raise ExportValidationError("knowledge_collection_configuration_invalid")
    all_types = [item for values in (*types.values(), children) for item in values]
    if len(set(all_types)) != len(all_types) or len(set(projects)) != len(projects):
        raise ExportValidationError("knowledge_collection_configuration_invalid")
    for item in (value["team_id"], *projects, *all_types):
        identifier(item)
    credential_ref = value["credential_ref"]
    if (
        not isinstance(credential_ref, str)
        or not credential_ref.startswith("secret://platform/")
        or _PLATFORM_SECRET_CODE.fullmatch(credential_ref.removeprefix("secret://platform/"))
        is None
    ):
        raise ExportValidationError("knowledge_collection_configuration_invalid")
    try:
        first_date = date.fromisoformat(value["first_date"])
    except (TypeError, ValueError):
        raise ExportValidationError("knowledge_collection_configuration_invalid") from None
    if first_date > date.today():
        raise ExportValidationError("knowledge_collection_configuration_invalid")
    return {
        "provider_origin": origin.rstrip("/"),
        "team_id": value["team_id"],
        "project_ids": sorted(projects),
        "issue_types": {kind: sorted(types[kind]) for kind in sorted(types)},
        "child_type_ids": sorted(children),
        "first_date": first_date.isoformat(),
        "credential_ref": credential_ref,
    }


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
