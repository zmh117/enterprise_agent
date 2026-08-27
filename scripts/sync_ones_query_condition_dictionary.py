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
_FIELD_COMMENT = re.compile(
    r"^  (?P<uuid>[A-Za-z0-9_-]+):\s+#\s+(?P<name>.+?)\s+type=(?P<type>1|16)\s*$"
)
_STATUS_COMMENT = re.compile(
    r"^  (?P<uuid>[A-Za-z0-9_-]+):.*?#\s*(?P<category>完成|进行中|待办)\s*$"
)
_CATEGORY = {"完成": "done", "进行中": "in_progress", "待办": "to_do"}
_FORBIDDEN_OUTPUT_KEYS = {
    "assign_in",
    "project_in",
    "sprint_in",
    "issueType_in",
    "headers",
    "token",
    "cookie",
    "email",
    "phone",
    "department_uuids",
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


def _text(value: object, name: str, *, maximum: int = 300) -> str:
    text = str(value).strip()
    if not text or len(text) > maximum or "@" in text:
        raise ValueError(f"{name} must be bounded non-sensitive text")
    return text


def _section_lines(source: str, start: str, end: str | None) -> list[str]:
    lines = source.splitlines()
    try:
        begin = next(index for index, line in enumerate(lines) if line == start)
    except StopIteration:
        raise ValueError(f"missing source section: {start}") from None
    finish = len(lines)
    if end is not None:
        try:
            finish = next(
                index for index, line in enumerate(lines[begin + 1 :], begin + 1) if line == end
            )
        except StopIteration:
            raise ValueError(f"missing source section: {end}") from None
    return lines[begin + 1 : finish]


def build_snapshot(source_bytes: bytes) -> dict[str, Any]:
    if len(source_bytes) > 512_000:
        raise ValueError("source dictionary is too large")
    source = source_bytes.decode("utf-8")
    metadata = _SOURCE_METADATA.search(source)
    if metadata is None:
        raise ValueError("source dictionary is missing Team metadata")
    team_uuid = _identifier(metadata.group("team"), "source_team_uuid")
    captured_at = metadata.group("date")
    try:
        date.fromisoformat(captured_at)
    except ValueError:
        raise ValueError("source dictionary has an invalid capture date") from None

    raw = yaml.safe_load(source)
    root = _mapping(raw, "dictionary")
    statuses = _mapping(root.get("status_in"), "status_in")
    option_fields = _mapping(root.get("all_option_fields"), "all_option_fields")

    status_categories: dict[str, str] = {}
    for line in _section_lines(source, "status_in:", "issueType_in:"):
        match = _STATUS_COMMENT.match(line)
        if match is not None:
            status_categories[match.group("uuid")] = _CATEGORY[match.group("category")]
    if set(statuses) != set(status_categories):
        raise ValueError("every status must have a stable category comment")

    field_metadata: dict[str, tuple[str, int]] = {}
    for line in _section_lines(source, "all_option_fields:", "sprint_in:"):
        match = _FIELD_COMMENT.match(line)
        if match is not None:
            field_metadata[match.group("uuid")] = (
                _text(match.group("name"), "field name"),
                int(match.group("type")),
            )
    if set(option_fields) != set(field_metadata):
        raise ValueError("every option field must have a name and supported type comment")

    normalized_statuses = [
        {
            "uuid": _identifier(uuid, "status uuid"),
            "name": _text(name, "status name"),
            "category": status_categories[uuid],
        }
        for uuid, name in sorted(statuses.items())
    ]
    normalized_fields: list[dict[str, Any]] = []
    for field_uuid, raw_options in sorted(option_fields.items()):
        uuid = _identifier(field_uuid, "field uuid")
        field_name, field_type = field_metadata[uuid]
        options = _mapping(raw_options, f"field {uuid}")
        if not options:
            raise ValueError("option fields must not be empty")
        normalized_fields.append(
            {
                "uuid": uuid,
                "name": field_name,
                "type": "multi_select" if field_type == 16 else "single_select",
                "filter_key": f"_{uuid}_in",
                "options": [
                    {
                        "uuid": _identifier(option_uuid, "option uuid"),
                        "name": _text(option_name, "option name"),
                    }
                    for option_uuid, option_name in sorted(options.items())
                ],
            }
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_team_uuid": team_uuid,
        "captured_at": captured_at,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "statuses": normalized_statuses,
        "custom_option_fields": normalized_fields,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        **payload,
        "dictionary_version": f"{captured_at}-{hashlib.sha256(canonical).hexdigest()[:16]}",
        "content_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def render_snapshot(snapshot: dict[str, Any]) -> bytes:
    rendered = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    lowered = rendered.casefold()
    for forbidden in _FORBIDDEN_OUTPUT_KEYS:
        if f'"{forbidden.casefold()}"' in lowered:
            raise ValueError(f"generated snapshot contains forbidden key: {forbidden}")
    return rendered.encode("utf-8")


def sync(source: Path, output: Path) -> None:
    rendered = render_snapshot(build_snapshot(source.read_bytes()))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_bytes(rendered)
    temporary.replace(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the scoped ONES query-condition snapshot")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sync(args.source, args.output)


if __name__ == "__main__":
    main()
