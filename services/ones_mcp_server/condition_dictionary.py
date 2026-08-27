from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from services.ones_mcp_server.errors import OnesMcpError


DEFAULT_DICTIONARY_PATH: Final = (
    Path(__file__).resolve().parent / "resources" / "query_condition_dictionary.json"
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_RESOURCE_BYTES = 512_000


def _invalid_resource() -> OnesMcpError:
    return OnesMcpError(
        "ONES query-condition resource is invalid",
        safe_message="ONES 查询条件字典不可用",
        error_code="ones_query_condition_resource_invalid",
    )


def _scope_mismatch() -> OnesMcpError:
    return OnesMcpError(
        "ONES query-condition resource is outside the current Team",
        safe_message="当前 ONES Team 没有可用的查询条件字典",
        error_code="ones_query_condition_scope_mismatch",
    )


def _unknown_condition() -> OnesMcpError:
    return OnesMcpError(
        "ONES custom query condition is not present in the managed dictionary",
        safe_message="ONES 自定义查询条件不存在或已过期",
        error_code="ones_query_condition_invalid",
    )


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid_resource()
    return {str(key): item for key, item in value.items()}


def _bounded_text(value: object, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise _invalid_resource()
    return value


def _identifier(value: object) -> str:
    text = _bounded_text(value, maximum=128)
    if _IDENTIFIER.fullmatch(text) is None:
        raise _invalid_resource()
    return text


def _normalize_search(value: str) -> str:
    return "".join(value.casefold().split())


@dataclass(frozen=True, slots=True)
class QueryConditionDictionary:
    source_team_uuid: str
    captured_at: str
    dictionary_version: str
    statuses: tuple[dict[str, str], ...]
    fields: tuple[dict[str, Any], ...]

    @classmethod
    def load(cls, path: Path = DEFAULT_DICTIONARY_PATH) -> QueryConditionDictionary:
        try:
            raw_bytes = path.read_bytes()
            if not raw_bytes or len(raw_bytes) > _MAX_RESOURCE_BYTES:
                raise _invalid_resource()
            payload = _mapping(json.loads(raw_bytes))
            if payload.get("schema_version") != 1:
                raise _invalid_resource()
            content_sha256 = _bounded_text(payload.pop("content_sha256"), maximum=64)
            dictionary_version = _bounded_text(payload.pop("dictionary_version"), maximum=80)
            canonical = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if hashlib.sha256(canonical).hexdigest() != content_sha256:
                raise _invalid_resource()
            source_sha256 = _bounded_text(payload.get("source_sha256"), maximum=64)
            if re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None:
                raise _invalid_resource()
            source_team_uuid = _identifier(payload.get("source_team_uuid"))
            captured_at = _bounded_text(payload.get("captured_at"), maximum=10)
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", captured_at) is None:
                raise _invalid_resource()
            date.fromisoformat(captured_at)
            if dictionary_version != f"{captured_at}-{content_sha256[:16]}":
                raise _invalid_resource()
            statuses_raw = payload.get("statuses")
            fields_raw = payload.get("custom_option_fields")
            if (
                not isinstance(statuses_raw, list)
                or not statuses_raw
                or not isinstance(fields_raw, list)
                or not fields_raw
            ):
                raise _invalid_resource()
            statuses = cls._statuses(statuses_raw)
            fields = cls._fields(fields_raw)
            return cls(
                source_team_uuid=source_team_uuid,
                captured_at=captured_at,
                dictionary_version=dictionary_version,
                statuses=statuses,
                fields=fields,
            )
        except OnesMcpError:
            raise
        except Exception:
            raise _invalid_resource() from None

    @staticmethod
    def _statuses(values: list[object]) -> tuple[dict[str, str], ...]:
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw in values:
            item = _mapping(raw)
            uuid = _identifier(item.get("uuid"))
            category = _bounded_text(item.get("category"), maximum=20)
            if uuid in seen or category not in {"to_do", "in_progress", "done"}:
                raise _invalid_resource()
            seen.add(uuid)
            result.append(
                {"uuid": uuid, "name": _bounded_text(item.get("name")), "category": category}
            )
        return tuple(result)

    @staticmethod
    def _fields(values: list[object]) -> tuple[dict[str, Any], ...]:
        result: list[dict[str, Any]] = []
        seen_fields: set[str] = set()
        for raw in values:
            item = _mapping(raw)
            uuid = _identifier(item.get("uuid"))
            field_type = _bounded_text(item.get("type"), maximum=20)
            filter_key = _bounded_text(item.get("filter_key"), maximum=132)
            options_raw = item.get("options")
            if (
                uuid in seen_fields
                or field_type not in {"single_select", "multi_select"}
                or filter_key != f"_{uuid}_in"
                or not isinstance(options_raw, list)
                or not options_raw
            ):
                raise _invalid_resource()
            seen_fields.add(uuid)
            options: list[dict[str, str]] = []
            seen_options: set[str] = set()
            for raw_option in options_raw:
                option = _mapping(raw_option)
                option_uuid = _identifier(option.get("uuid"))
                if option_uuid in seen_options:
                    raise _invalid_resource()
                seen_options.add(option_uuid)
                options.append({"uuid": option_uuid, "name": _bounded_text(option.get("name"))})
            result.append(
                {
                    "uuid": uuid,
                    "name": _bounded_text(item.get("name")),
                    "type": field_type,
                    "filter_key": filter_key,
                    "options": tuple(options),
                }
            )
        return tuple(result)

    def require_team(self, team_uuid: str) -> None:
        if team_uuid != self.source_team_uuid:
            raise _scope_mismatch()

    def resolve(
        self,
        *,
        team_uuid: str,
        condition_type: str,
        keyword: str,
        field_keyword: str,
        limit: int,
    ) -> dict[str, Any]:
        self.require_team(team_uuid)
        normalized_keyword = _normalize_search(keyword)
        normalized_field = _normalize_search(field_keyword)
        matches: list[dict[str, str]] = []
        if condition_type == "status":
            matches = [
                {"condition_type": "status", **status}
                for status in self.statuses
                if normalized_keyword in _normalize_search(status["name"])
            ]
        elif condition_type == "custom_option":
            for field in self.fields:
                if normalized_field not in _normalize_search(str(field["name"])):
                    continue
                for option in field["options"]:
                    if normalized_keyword not in _normalize_search(option["name"]):
                        continue
                    matches.append(
                        {
                            "condition_type": "custom_option",
                            "field_uuid": str(field["uuid"]),
                            "field_name": str(field["name"]),
                            "option_uuid": option["uuid"],
                            "option_name": option["name"],
                        }
                    )
        else:
            raise _unknown_condition()

        def rank(value: dict[str, str]) -> tuple[int, str, str]:
            name = value.get("option_name") or value.get("name") or ""
            exact = 0 if _normalize_search(name) == normalized_keyword else 1
            return (exact, value.get("field_name", ""), name)

        matches.sort(key=rank)
        total = len(matches)
        return {
            "matches": matches[:limit],
            "total": total,
            "returned": min(total, limit),
            "truncated": total > limit,
            "dictionary_version": self.dictionary_version,
            "captured_at": self.captured_at,
            "untrusted_data": True,
        }

    def validated_custom_filters(
        self,
        *,
        team_uuid: str,
        filters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.require_team(team_uuid)
        fields = {str(item["uuid"]): item for item in self.fields}
        result: list[dict[str, Any]] = []
        for value in filters:
            field = fields.get(str(value["field_uuid"]))
            if field is None:
                raise _unknown_condition()
            allowed = {option["uuid"] for option in field["options"]}
            option_uuids = list(value["option_uuids"])
            if any(option_uuid not in allowed for option_uuid in option_uuids):
                raise _unknown_condition()
            result.append(
                {
                    "field_uuid": field["uuid"],
                    "filter_key": field["filter_key"],
                    "option_uuids": option_uuids,
                }
            )
        return result
