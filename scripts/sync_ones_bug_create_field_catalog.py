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
FIXED_ISSUE_TYPE_UUID = "B4TV9bu5"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SOURCE_METADATA = re.compile(
    r"数据来源：ONES 团队 (?P<team>[A-Za-z0-9_-]+)，接口拉取日期 (?P<date>\d{4}-\d{2}-\d{2})"
)

# semantic_name: Chinese label, Provider field UUID, Provider type, value kind
FIELD_SPECS: dict[str, tuple[str, str, int, str]] = {
    "title": ("标题", "field001", 2, "text"),
    "description": ("描述", "field016", 20, "rich_text"),
    "environment": ("环境", "5BiPnrfy", 15, "text"),
    "assignee_uuid": ("负责人", "field004", 8, "user"),
    "defect_type_uuid": ("缺陷类型", "field041", 1, "option"),
    "urgency_uuid": ("紧急程度", "FnkEKd4Y", 1, "option"),
    "severity_uuid": ("严重程度", "field038", 1, "option"),
    "discovery_difficulty_uuid": ("发现难易程度", "4v1yHkX9", 1, "option"),
    "reproduction_probability_uuid": ("重现概率", "679m6U93", 1, "option"),
    "product_uuids": ("所属产品", "field029", 44, "entities"),
    "product_module_uuids": ("所属功能模块", "field030", 46, "entities"),
    "discovery_stage_uuid": ("缺陷发现阶段", "79WCF8hL", 1, "option"),
    "online_defect_uuid": ("是否线上缺陷", "field031", 1, "option"),
    "historical_defect_uuid": ("是否历史缺陷", "6FimuZwX", 1, "option"),
    "affected_version_uuids": ("影响版本", "4ipdiS95", 16, "options"),
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


def _name(value: object, name: str) -> str:
    text = str(value).strip()
    if not text or len(text) > 300 or any(ord(char) < 32 for char in text):
        raise ValueError(f"{name} must be bounded display text")
    return text


def _index(values: dict[str, Any], name: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    counts: dict[str, int] = {}
    for raw_uuid, raw_name in sorted(values.items()):
        uuid = _identifier(raw_uuid, f"{name} uuid")
        display_name = _name(raw_name, f"{name} name")
        normalized = "".join(display_name.casefold().split())
        counts[normalized] = counts.get(normalized, 0) + 1
        candidates.append({"uuid": uuid, "name": display_name})
    # Ambiguous names must never be silently included as a unique document
    # lookup. Every duplicate remains available only through live read tools.
    return [
        item
        for item in candidates
        if counts["".join(item["name"].casefold().split())] == 1
    ]


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
    options = _mapping(raw.get("all_option_fields"), "all_option_fields")

    fields: list[dict[str, Any]] = []
    seen_provider_fields: set[str] = set()
    seen_option_uuids: set[str] = set()
    for semantic_name, (label, provider_field_uuid, provider_type, value_kind) in FIELD_SPECS.items():
        if provider_field_uuid in seen_provider_fields:
            raise ValueError("duplicate Provider field UUID")
        seen_provider_fields.add(provider_field_uuid)
        field_options: list[dict[str, str]] = []
        if value_kind in {"option", "options"}:
            raw_options = _mapping(options.get(provider_field_uuid), provider_field_uuid)
            for raw_uuid, raw_name in sorted(raw_options.items()):
                option_uuid = _identifier(raw_uuid, "option uuid")
                if option_uuid in seen_option_uuids:
                    raise ValueError("duplicate option UUID")
                seen_option_uuids.add(option_uuid)
                field_options.append(
                    {"uuid": option_uuid, "name": _name(raw_name, "option name")}
                )
        fields.append(
            {
                "semantic_name": semantic_name,
                "label": label,
                "provider_field_uuid": provider_field_uuid,
                "provider_type": provider_type,
                "value_kind": value_kind,
                "options": field_options,
            }
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_team_uuid": _identifier(metadata.group("team"), "source Team"),
        "captured_at": captured_at,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "interface_contract": "ones-bug-add3-v1",
        "fixed_issue_type": {"uuid": FIXED_ISSUE_TYPE_UUID, "name": "缺陷"},
        "fields": fields,
        "reference_indexes": {
            "projects": _index(_mapping(raw.get("project_in"), "project_in"), "project"),
            "users": _index(_mapping(raw.get("assign_in"), "assign_in"), "user"),
            # These two observed values are non-secret interface-contract facts.
            # Module documentation currently conflicts on the sample module name,
            # so no module is treated as a unique document hit.
            "products": [{"uuid": "NfvccPP5M3vRzNMY", "name": "MES"}],
            "product_modules": [],
            "affected_versions": _index(
                {
                    str(option["uuid"]): str(option["name"])
                    for field in fields
                    if field["semantic_name"] == "affected_version_uuids"
                    for option in field["options"]
                },
                "affected version",
            ),
        },
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
    return (json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def sync(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(render_catalog(build_catalog(source.read_bytes())))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sync(args.source, args.output)


if __name__ == "__main__":
    main()
