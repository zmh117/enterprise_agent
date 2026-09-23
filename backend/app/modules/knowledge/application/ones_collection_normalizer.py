"""将受管 ONES 详情投影到 keep_ids_v1；不保留评论或附件正文。"""

from __future__ import annotations

from typing import Any

from app.modules.knowledge.domain.keep_ids import normalize_keep_ids
from app.modules.knowledge.domain.normalization import (
    ExportValidationError,
    PreparedRecord,
    Sanitizer,
    identifier,
)


_SCALAR_NAMES = {
    "owner": "owner_name",
    "assign": "assign_name",
    "status_uuid": "status_name",
    "issue_type_uuid": "issue_type_name",
    "sub_issue_type_uuid": "sub_issue_type_name",
    "project_uuid": "project_name",
    "sprint_uuid": "sprint_name",
    "priority": "priority_name",
    "issue_type_scope_uuid": "issue_type_scope_name",
}
_DETAIL_FIELDS = {
    "uuid",
    "number",
    "summary",
    "create_time",
    "server_update_stamp",
    "project_uuid",
    "status_uuid",
    "issue_type_uuid",
    "sub_issue_type_uuid",
    "sprint_uuid",
    "parent_uuid",
    "owner",
    "assign",
    "priority",
    "issue_type_scope_uuid",
    "desc",
    "desc_rich",
    "field_values",
    "product_uuids",
    "links",
    "discussion_count",
    "attachment_count",
}


class OnesCollectionNormalizer:
    """字段字典固定于一次运行；名称缓存仅用于显示，绝不代替 UUID。"""

    def __init__(
        self,
        *,
        fields: dict[str, dict[str, Any]],
        names: dict[str, str],
    ) -> None:
        self.fields = fields
        self.names = dict(names)
        self.clean = Sanitizer()
        for fid, field in fields.items():
            if (
                identifier(fid) != fid
                or not isinstance(field, dict)
                or field.get("uuid") != fid
                or not isinstance(field.get("name"), str)
                or not isinstance(field.get("options", []), list)
            ):
                raise ExportValidationError("knowledge_field_dictionary_invalid")

    def absorb_listing(self, listing: dict[str, Any]) -> None:
        for key in ("project", "status", "sprint", "issueType", "subIssueType"):
            block = listing.get(key) or {}
            if not isinstance(block, dict):
                raise ExportValidationError("knowledge_collection_page_invalid")
            uid, name = block.get("uuid"), block.get("name")
            if uid and isinstance(name, str) and name:
                key = identifier(uid)
                if key in self.names and self.names[key] != name:
                    raise ExportValidationError("knowledge_display_name_conflict")
                self.names[key] = name

    def normalize(
        self, listing: dict[str, Any] | None, detail: dict[str, Any], *, kind: str
    ) -> PreparedRecord:
        row = {key: detail.get(key) for key in _DETAIL_FIELDS if key in detail}
        row["_export_format"] = "keep_ids_v1"
        row["comments_presence"] = "not_collected"
        row["desc_presence"] = (
            "not_returned"
            if detail.get("desc") is None
            else "source_empty"
            if detail.get("desc") == ""
            else "present"
        )
        for source, target in _SCALAR_NAMES.items():
            uid = row.get(source)
            name = self.names.get(uid) if isinstance(uid, str) else None
            if name:
                row[target] = name
        if listing is not None:
            self.absorb_listing(listing)
            for source, target in (
                ("project", "project_name"),
                ("status", "status_name"),
                ("issueType", "issue_type_name"),
            ):
                block = listing.get(source) or {}
                if isinstance(block, dict) and isinstance(block.get("name"), str):
                    row[target] = block["name"]
        values = row.get("field_values")
        if not isinstance(values, list):
            raise ExportValidationError("knowledge_fields_invalid")
        projected = []
        for value in values:
            if not isinstance(value, dict):
                raise ExportValidationError("knowledge_field_invalid")
            fid = identifier(value.get("field_uuid"))
            definition = self.fields.get(fid)
            if definition is None:
                raise ExportValidationError("knowledge_field_dictionary_invalid")
            entry = {
                key: value[key]
                for key in ("field_uuid", "type", "value", "value_type", "date_value")
                if key in value
            }
            entry["field_name"] = definition["name"]
            options = {option["uuid"]: option["value"] for option in definition.get("options", [])}
            raw = value.get("value")
            if isinstance(raw, str):
                shown = options.get(raw, self.names.get(raw))
            elif isinstance(raw, list):
                translated = [
                    options.get(part, self.names.get(part)) if isinstance(part, str) else None
                    for part in raw
                ]
                shown = translated if any(part is not None for part in translated) else None
            else:
                shown = None
            if shown is not None:
                entry["value_display"] = shown
            projected.append(entry)
        row["field_values"] = projected
        return normalize_keep_ids(
            row,
            listing,
            kind=kind,
            fields=self.fields,
            clean=self.clean,
            source_type_checked=True,
        )
