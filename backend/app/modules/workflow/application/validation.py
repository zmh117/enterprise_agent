from __future__ import annotations

from typing import Any

from app.modules.platform_config.application.validation import (
    PlatformConfigValidationError,
    assert_no_secret_payload,
    assert_readonly_workflow_node,
    normalize_json_object,
    validate_code,
)

from ..domain import WorkflowNodeType, WorkflowStatus


def validate_workflow_status(value: str) -> WorkflowStatus:
    try:
        return WorkflowStatus(str(value or WorkflowStatus.DRAFT.value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid workflow status: {value}",
            safe_message="工作流状态无效",
        ) from exc


def validate_node_type(value: str) -> WorkflowNodeType:
    try:
        return WorkflowNodeType(str(value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid workflow node type: {value}",
            safe_message="工作流节点类型无效",
        ) from exc


def normalize_node_payload(payload: dict[str, Any]) -> dict[str, Any]:
    node_type = validate_node_type(str(payload.get("node_type") or ""))
    config = normalize_json_object(payload.get("config"), field="config")
    assert_no_secret_payload(config)
    assert_readonly_workflow_node(node_type.value, config)
    return {
        "node_key": validate_code(str(payload.get("node_key") or ""), field="node_key"),
        "node_type": node_type.value,
        "title": str(payload.get("title") or ""),
        "position": normalize_json_object(payload.get("position"), field="position"),
        "config": config,
        "ui": normalize_json_object(payload.get("ui"), field="ui"),
    }


def validate_graph(
    *,
    entry_node_key: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    node_keys = [str(node["node_key"]) for node in nodes]
    if len(node_keys) != len(set(node_keys)):
        raise PlatformConfigValidationError(
            "Workflow node keys must be unique",
            safe_message="工作流节点标识不能重复",
        )
    if entry_node_key and entry_node_key not in set(node_keys):
        raise PlatformConfigValidationError(
            "Workflow entry node does not exist",
            safe_message="工作流入口节点不存在",
        )
    edge_keys = [str(edge["edge_key"]) for edge in edges]
    if len(edge_keys) != len(set(edge_keys)):
        raise PlatformConfigValidationError(
            "Workflow edge keys must be unique",
            safe_message="工作流连线标识不能重复",
        )
    for edge in edges:
        if edge["source_node_key"] not in set(node_keys) or edge["target_node_key"] not in set(
            node_keys
        ):
            raise PlatformConfigValidationError(
                "Workflow edge references a missing node",
                safe_message="工作流连线引用了不存在的节点",
            )
