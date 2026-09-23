"""keep_ids_v1 纯规范化：来源身份与显示文本独立，不反推 UUID。"""

from typing import Any
import re

from app.modules.knowledge.domain.normalization import (
    ExportValidationError,
    FIELD_MAPPING,
    PreparedRecord,
    RichText,
    Sanitizer,
    _DUPLICATE_FIELDS,
    _SENSITIVE_KEY,
    _timestamp,
    digest,
    identifier,
)
from app.modules.knowledge.domain.work_items import check_offline_type


KEEP_IDS_NORMALIZER = "ones-keep-ids-text/v1"


def text_body(value: Any, clean: Sanitizer) -> tuple[str, list[dict[str, Any]]]:
    if value is None:
        return "", []
    if not isinstance(value, str):
        raise ExportValidationError("knowledge_body_invalid")
    if re.search(
        r"</?(?:p|div|br|ul|ol|li|pre|h[1-6]|img|span|script|style)(?:\s|/?>)", value, re.I
    ):
        parser = RichText()
        parser.feed(value)
        return clean.text("".join(parser.parts)).strip(), parser.images
    return clean.text(value).strip(), []


def normalize_keep_ids(  # noqa: C901, PLR0915
    row: dict[str, Any],
    listing: dict[str, Any] | None,
    *,
    kind: str,
    fields: dict[str, dict[str, Any]],
    clean: Sanitizer,
) -> PreparedRecord:
    if row.get("_export_format") != "keep_ids_v1":
        raise ExportValidationError("knowledge_export_format_invalid")
    check_offline_type(kind, row.get("issue_type_name"))
    external_id = identifier(row.get("uuid"))
    for key in ("project_uuid", "status_uuid", "issue_type_uuid"):
        identifier(row.get(key))
    for key in ("project_name", "status_name", "issue_type_name", "summary"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ExportValidationError("knowledge_display_name_missing")
    if type(row.get("number")) is not int or row["number"] < 1:
        raise ExportValidationError("knowledge_record_invalid")
    if listing is not None:
        for detail_key, list_key in (
            ("uuid", "uuid"),
            ("summary", "name"),
            ("number", "number"),
            ("create_time", "createTime"),
        ):
            if row.get(detail_key) != listing.get(list_key):
                raise ExportValidationError("knowledge_list_detail_mismatch")
        for detail_key, list_key in (
            ("project_uuid", "project"),
            ("status_uuid", "status"),
            ("issue_type_uuid", "issueType"),
            ("sprint_uuid", "sprint"),
            ("parent_uuid", "parent"),
            ("sub_issue_type_uuid", "subIssueType"),
        ):
            item = listing.get(list_key) or {}
            if not isinstance(item, dict) or (item.get("uuid") or None) != (
                row.get(detail_key) or None
            ):
                raise ExportValidationError("knowledge_list_scope_invalid")
            name_key = {
                "project": "project_name",
                "status": "status_name",
                "issueType": "issue_type_name",
            }.get(list_key)
            if name_key and item.get("name") is not None and item["name"] != row[name_key]:
                raise ExportValidationError("knowledge_display_name_conflict")
    body, body_images = text_body(row.get("desc"), clean)
    rich, rich_images = text_body(row.get("desc_rich"), clean)
    attrs: dict[str, Any] = {
        "document_kind": kind,
        "source_issue_type_id": row["issue_type_uuid"],
        "source_issue_type_display": clean.text(row["issue_type_name"]),
        "source_issue_type_identity": "collected",
        "export_id_mapping": "keep_ids_v1",
        "source_fields": {},
        "unmapped_fields": {},
        "image_references": rich_images or body_images,
    }
    for id_key, name_key, target in (
        ("sprint_uuid", "sprint_name", "sprint"),
        ("assign", "assign_name", "assignee"),
        ("owner", "owner_name", "owner"),
        ("issue_type_scope_uuid", "issue_type_scope_name", "issue_type_scope"),
        ("sub_issue_type_uuid", "sub_issue_type_name", "sub_issue_type"),
    ):
        attrs[target + "_id"] = identifier(row[id_key]) if row.get(id_key) else None
        name = row.get(name_key)
        if name is not None and not isinstance(name, str):
            raise ExportValidationError("knowledge_display_name_invalid")
        attrs[target + "_name"] = clean.text(name) if name else None
    source_fields = row.get("field_values")
    if not isinstance(source_fields, list):
        raise ExportValidationError("knowledge_fields_invalid")
    seen, mapped = set(), set()
    for field in source_fields:
        if not isinstance(field, dict):
            raise ExportValidationError("knowledge_field_invalid")
        fid = identifier(field.get("field_uuid"))
        definition = fields.get(fid)
        if fid in seen or not definition:
            raise ExportValidationError("knowledge_field_dictionary_invalid")
        seen.add(fid)
        name = definition["name"]
        if (
            field.get("field_name") != name
            or field.get("type") != definition.get("type")
            or "value" not in field
        ):
            raise ExportValidationError("knowledge_field_dictionary_invalid")
        if _SENSITIVE_KEY.search(name):
            clean.counts["sensitive_field"] += 1
            continue
        raw = field["value"]
        display = field.get("value_display", raw)
        options = {opt["uuid"]: opt["value"] for opt in definition.get("options", [])}
        if options and raw not in (None, "", []):
            option_values = raw if isinstance(raw, list) else [raw]
            if any(not isinstance(v, str) or v not in options for v in option_values):
                raise ExportValidationError("knowledge_field_option_invalid")
            resolved = [options[v] for v in option_values]
            display = resolved if isinstance(raw, list) else resolved[0]
            if "value_display" in field and field["value_display"] != display:
                raise ExportValidationError("knowledge_field_option_invalid")
        if name in _DUPLICATE_FIELDS:
            continue
        attrs["source_fields"][fid] = clean.value(
            {
                "name": name,
                "type": field["type"],
                "value_type": field.get("value_type"),
                "value": raw,
                "display": display,
                "date_value": field.get("date_value"),
            }
        )
        mapped_field = FIELD_MAPPING.get(name)
        if mapped_field:
            if mapped_field in mapped:
                raise ExportValidationError("knowledge_field_mapping_ambiguous")
            mapped.add(mapped_field)
            if mapped_field == "solution_text":
                attrs[mapped_field] = text_body(display, clean)[0]
            else:
                attrs[mapped_field] = clean.value(display)
        else:
            attrs["unmapped_fields"][fid] = clean.value(display)
    if row.get("product_names") and not attrs.get("product_names"):
        attrs["product_names"] = clean.value(row["product_names"])
    if row.get("product_uuids"):
        if not isinstance(row["product_uuids"], list):
            raise ExportValidationError("knowledge_field_invalid")
        attrs["product_ids"] = [identifier(v) for v in row["product_uuids"]]
    relations: dict[str, dict[str, str]] = {}
    links = row.get("links") or []
    if not isinstance(links, list):
        raise ExportValidationError("knowledge_relations_invalid")
    for link in links:
        if not isinstance(link, dict):
            raise ExportValidationError("knowledge_relations_invalid")
        relation = {
            "target_external_id": identifier(link.get("task_uuid")),
            "source_relation_type": identifier(link.get("task_link_type_uuid")),
            "source_direction": identifier(link.get("link_desc_type")),
        }
        relations[digest(relation)] = relation
    parent = identifier(row["parent_uuid"]) if row.get("parent_uuid") else None
    attrs["parent_id"] = parent
    if parent:
        relation = {
            "target_external_id": parent,
            "source_relation_type": "parent_uuid",
            "source_direction": "child_to_parent",
        }
        relations[digest(relation)] = relation
    counts = {key: row.get(key, 0) for key in ("discussion_count", "attachment_count")}
    if any(type(v) is not int or v < 0 for v in counts.values()):
        raise ExportValidationError("knowledge_content_counts_invalid")
    created, updated = (
        _timestamp(row.get("create_time")),
        _timestamp(row.get("server_update_stamp")),
    )
    if not created or not updated or row["server_update_stamp"] < row["create_time"]:
        raise ExportValidationError("knowledge_timestamp_invalid")
    values = {
        "title": clean.text(row["summary"]),
        "body_text": body or rich,
        "source_project_id": row["project_uuid"],
        "source_project_name": clean.text(row["project_name"]),
        "source_status_id": row["status_uuid"],
        "source_status_name": clean.text(row["status_name"]),
        "source_created_at": created,
        "source_updated_at": updated,
        "source_update_stamp_raw": row["server_update_stamp"],
        "source_snapshot": {
            "detail": clean.value(
                {
                    key: row.get(key)
                    for key in (
                        "uuid",
                        "number",
                        "_export_format",
                        "create_time",
                        "server_update_stamp",
                        "parent_uuid",
                        "project_uuid",
                        "project_name",
                        "status_uuid",
                        "status_name",
                        "issue_type_uuid",
                        "issue_type_name",
                        "desc_presence",
                        "comments_presence",
                        "discussion_count",
                        "attachment_count",
                    )
                }
            ),
            "list": {"collected": listing is not None},
        },
        "attributes": attrs,
        "completeness": {
            "detail": "collected",
            "description": "collected" if body or rich else "missing",
            "source_issue_type_id": "collected",
            "discussion": "not_indexed",
            "attachments": "not_collected",
            "ocr": "not_requested",
            "relation_set": "unverified",
            **counts,
            "inline_image_count": len(attrs["image_references"]),
        },
        "normalizer_version": KEEP_IDS_NORMALIZER,
    }
    return PreparedRecord(
        external_id, str(row["number"]), values, tuple(relations.values()), digest(values), kind
    )
