from __future__ import annotations

import hashlib
import json
from typing import Any


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def canonical_node(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_key": str(value.get("node_key") or ""),
        "node_type": str(value.get("node_type") or ""),
        "title": str(value.get("title") or ""),
        "position": _object(value.get("position")),
        "config": _object(value.get("config")),
        "ui": _object(value.get("ui")),
    }


def canonical_edge(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "edge_key": str(value.get("edge_key") or ""),
        "source_node_key": str(value.get("source_node_key") or ""),
        "target_node_key": str(value.get("target_node_key") or ""),
        "source_port": str(value.get("source_port") or ""),
        "target_port": str(value.get("target_port") or ""),
        "condition": _object(value.get("condition")),
    }


def canonical_draft_graph(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "nodes": sorted(
            (canonical_node(node) for node in nodes),
            key=lambda node: node["node_key"],
        ),
        "edges": sorted(
            (canonical_edge(edge) for edge in edges),
            key=lambda edge: edge["edge_key"],
        ),
    }


def parse_legacy_graph(value: Any) -> dict[str, list[dict[str, Any]]] | None:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    nodes = parsed.get("nodes", [])
    edges = parsed.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return None
    if not all(isinstance(item, dict) for item in (*nodes, *edges)):
        return None
    return canonical_draft_graph(nodes=list(nodes), edges=list(edges))


def publication_snapshot(
    *,
    template: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    graph = canonical_draft_graph(nodes=nodes, edges=edges)
    return {
        "schema_version": int(template.get("graph_schema_version") or 1),
        "template": {
            "id": str(template["id"]),
            "code": str(template["code"]),
            "name": str(template.get("name") or ""),
            "description": str(template.get("description") or ""),
            "project_code": str(template.get("project_code") or "default"),
            "entry_node_key": str(template.get("entry_node_key") or ""),
            "graph_schema_version": int(template.get("graph_schema_version") or 1),
            "settings": _object(template.get("settings")),
        },
        **graph,
    }


def graph_config_hash(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
