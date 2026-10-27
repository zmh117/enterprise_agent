"""在线内容语义摘要；采集元数据不构成本地内容修订。"""

from copy import deepcopy
from typing import Any

from app.modules.knowledge.domain.normalization import PreparedRecord, digest


def content_hash(values: dict[str, Any], relations: tuple[dict[str, str], ...]) -> str:
    attributes = deepcopy(values["attributes"])
    for key in ("export_id_mapping", "source_issue_type_identity"):
        attributes.pop(key, None)
    if isinstance(attributes.get("product_ids"), list):
        attributes["product_ids"] = sorted(set(attributes["product_ids"]))
    # 只对明确无序的集合排序；正文、步骤和未知数组的顺序继续有意义。
    return digest(
        {
            **{
                key: values[key]
                for key in (
                    "title",
                    "body_text",
                    "source_project_id",
                    "source_project_name",
                    "source_status_id",
                    "source_status_name",
                    "source_created_at",
                )
            },
            "number": values["source_snapshot"]["detail"].get("number"),
            "attributes": attributes,
            "relations": sorted({digest(item) for item in relations}),
        }
    )


def record_hash(record: PreparedRecord) -> str:
    return content_hash(record.values, record.relations)
