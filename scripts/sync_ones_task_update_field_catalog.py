from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = 1
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SOURCE_METADATA = re.compile(
    r"数据来源：ONES 团队 (?P<team>[A-Za-z0-9_-]+)，接口拉取日期 (?P<date>\d{4}-\d{2}-\d{2})"
)
_OPTION_FIELD_COMMENT = re.compile(
    r"^  (?P<uuid>[A-Za-z0-9_-]+):\s+#\s+(?P<label>.+?)\s*\|?\s*type=(?P<type>\d+)"
)

# semantic_name: label, provider field, Provider type, value kind, clear, response key
FIELD_SPECS: dict[str, tuple[str, str, int, str, bool, str]] = {
    "title": ("标题", "", 0, "text", False, "name"),
    "description": ("描述", "", 0, "text", True, "descriptionText"),
    "assignee_uuid": ("负责人", "", 0, "user", False, "assign"),
    "environment": ("环境", "5BiPnrfy", 15, "text", True, "_5BiPnrfy"),
    "labels_text": ("标签", "F9eyqM3a", 2, "text", True, "_F9eyqM3a"),
    "resolver_uuid": ("解决者", "field040", 8, "user", False, "solver"),
    "owner_uuids": ("所属人", "VRS2LsBn", 13, "users", True, "_VRS2LsBn"),
    "watcher_uuids": ("关注者", "field008", 13, "users", True, "watchers"),
    "defect_type_uuid": ("缺陷类型", "field041", 1, "option", False, "defectType"),
    "urgency_uuid": ("紧急程度", "FnkEKd4Y", 1, "option", False, "_FnkEKd4Y"),
    "severity_uuid": ("严重程度", "field038", 1, "option", False, "severityLevel"),
    "discovery_difficulty_uuid": (
        "发现难易程度",
        "4v1yHkX9",
        1,
        "option",
        False,
        "_4v1yHkX9",
    ),
    "reproduction_probability_uuid": (
        "重现概率",
        "679m6U93",
        1,
        "option",
        False,
        "_679m6U93",
    ),
    "sprint_uuid": ("所属迭代", "field011", 7, "sprint", False, "sprint"),
    "product_uuids": ("所属产品", "field029", 44, "entities", True, "products"),
    "product_module_uuids": (
        "所属功能模块",
        "field030",
        46,
        "entities",
        True,
        "productModules",
    ),
    "discovery_stage_uuid": (
        "缺陷发现阶段",
        "79WCF8hL",
        1,
        "option",
        False,
        "_79WCF8hL",
    ),
    "online_defect_uuid": (
        "是否线上缺陷",
        "field031",
        1,
        "option",
        False,
        "isOnlineDefect",
    ),
    "historical_defect_uuid": (
        "是否历史缺陷",
        "6FimuZwX",
        1,
        "option",
        False,
        "_6FimuZwX",
    ),
    "affected_version_mes_uuids": (
        "影响版本-MES",
        "4ipdiS95",
        16,
        "options",
        True,
        "_4ipdiS95",
    ),
    "fixed_version_mes_uuids": (
        "修复版本-MES",
        "MysgAE3y",
        16,
        "options",
        True,
        "_MysgAE3y",
    ),
    "verified_version_mes_uuids": (
        "验证版本-MES",
        "LfbLTzsp",
        16,
        "options",
        True,
        "_LfbLTzsp",
    ),
    "solution_text": ("解决方案", "LMb5XC7P", 15, "text", True, "_LMb5XC7P"),
    "cause_uuid": ("缺陷产生原因", "PxHXwe6T", 1, "option", False, "_PxHXwe6T"),
    "svn_version_number": ("Svn版本号", "DmGDdhkv", 4, "number", False, "_DmGDdhkv"),
    "handling_result_uuid": ("处理结果", "field039", 1, "option", False, "solution"),
    "impact_analysis": ("影响面分析", "41TN9bsG", 15, "text", True, "_41TN9bsG"),
    "multi_version_duplicate_bug_uuid": (
        "多版本重复bug",
        "2adoeHHw",
        1,
        "option",
        False,
        "_2adoeHHw",
    ),
    "priority_uuid": ("优先级", "field012", 1, "option", False, "priority"),
}


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _identifier(value: object, name: str) -> str:
    text = str(value)
    if _IDENTIFIER.fullmatch(text) is None:
        raise ValueError(f"{name} must be an ONES identifier")
    return text


def _bounded_label(value: object, name: str) -> str:
    text = str(value).strip()
    if not text or len(text) > 100 or "@" in text:
        raise ValueError(f"{name} must be bounded non-sensitive text")
    return text


def _option_metadata(source: str) -> dict[str, tuple[str, int]]:
    lines = source.splitlines()
    try:
        start = lines.index("all_option_fields:") + 1
        end = lines.index("sprint_in:")
    except ValueError:
        raise ValueError("source dictionary option section is incomplete") from None
    result: dict[str, tuple[str, int]] = {}
    for line in lines[start:end]:
        match = _OPTION_FIELD_COMMENT.match(line)
        if match is None:
            continue
        uuid = _identifier(match.group("uuid"), "field uuid")
        if uuid in result:
            raise ValueError("duplicate option field uuid")
        result[uuid] = (
            _bounded_label(match.group("label"), "field label"),
            int(match.group("type")),
        )
    return result


def build_catalog(source_bytes: bytes) -> dict[str, Any]:
    if not source_bytes or len(source_bytes) > 512_000:
        raise ValueError("source dictionary is too large")
    source = source_bytes.decode("utf-8")
    metadata = _SOURCE_METADATA.search(source)
    if metadata is None:
        raise ValueError("source dictionary is missing Team metadata")
    captured_at = metadata.group("date")
    date.fromisoformat(captured_at)
    raw = _mapping(yaml.safe_load(source), "dictionary")
    non_options = _mapping(raw.get("update_fields_non_option"), "update_fields_non_option")
    all_options = _mapping(raw.get("all_option_fields"), "all_option_fields")
    option_metadata = _option_metadata(source)

    fields: list[dict[str, Any]] = []
    seen_option_uuids: set[str] = set()
    for semantic_name, spec in FIELD_SPECS.items():
        label, provider_field_uuid, provider_type, value_kind, allow_clear, source_key = spec
        options: list[dict[str, str]] = []
        if value_kind in {"option", "options"}:
            raw_options = _mapping(all_options.get(provider_field_uuid), provider_field_uuid)
            source_label, source_type = option_metadata.get(provider_field_uuid, ("", -1))
            if source_type != provider_type or not source_label.startswith(label):
                raise ValueError(f"option field metadata drifted: {provider_field_uuid}")
            for option_uuid, option_name in sorted(raw_options.items()):
                normalized_uuid = _identifier(option_uuid, "option uuid")
                if normalized_uuid in seen_option_uuids:
                    raise ValueError("duplicate option uuid")
                seen_option_uuids.add(normalized_uuid)
                options.append(
                    {
                        "uuid": normalized_uuid,
                        "name": _bounded_label(option_name, "option name"),
                    }
                )
        elif provider_field_uuid:
            non_option_label = non_options.get(provider_field_uuid)
            if _bounded_label(non_option_label, provider_field_uuid) != label:
                raise ValueError(f"non-option field metadata drifted: {provider_field_uuid}")
        else:
            source_name = {
                "title": "name",
                "description": "descriptionText",
                "assignee_uuid": "assign",
            }[semantic_name]
            if _bounded_label(non_options.get(source_name), source_name) != label:
                raise ValueError(f"top-level field metadata drifted: {source_name}")
        fields.append(
            {
                "semantic_name": semantic_name,
                "label": label,
                "provider_field_uuid": provider_field_uuid,
                "provider_type": provider_type,
                "value_kind": value_kind,
                "allow_clear": allow_clear,
                "source_key": source_key,
                "options": options,
            }
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_team_uuid": _identifier(metadata.group("team"), "source team"),
        "captured_at": captured_at,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "fields": fields,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    content_sha256 = hashlib.sha256(canonical).hexdigest()
    return {
        **payload,
        "catalog_version": f"{captured_at}-{content_sha256[:16]}",
        "content_sha256": content_sha256,
    }


def render_catalog(catalog: dict[str, Any]) -> bytes:
    return (json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def sync(source: Path, output: Path) -> None:
    rendered = render_catalog(build_catalog(source.read_bytes()))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_bytes(rendered)
    temporary.replace(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the scoped ONES defect-update catalog")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sync(args.source, args.output)


if __name__ == "__main__":
    main()
