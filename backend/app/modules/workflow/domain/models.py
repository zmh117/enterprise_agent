from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkflowStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DISABLED = "disabled"


class WorkflowNodeType(str, Enum):
    TRIGGER = "trigger"
    CONTEXT_SEARCH = "context_search"
    TOOL_CALL = "tool_call"
    AGENT_PROMPT = "agent_prompt"
    CONDITION = "condition"
    REPORT = "report"
    CALLBACK = "callback"


@dataclass(frozen=True)
class AgentWorkflowTemplate:
    id: str
    code: str
    name: str
    description: str = ""
    project_code: str = "default"
    status: WorkflowStatus = WorkflowStatus.DRAFT
    version: int = 1
    entry_node_key: str = ""
    graph_schema_version: int = 1
    graph: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""


@dataclass(frozen=True)
class WorkflowNode:
    id: str
    template_id: str
    node_key: str
    node_type: WorkflowNodeType
    title: str = ""
    position: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    ui: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentWorkflowEdge:
    id: str
    template_id: str
    edge_key: str
    source_node_key: str
    target_node_key: str
    source_port: str = ""
    target_port: str = ""
    condition: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentWorkflowPublication:
    id: str
    template_id: str
    version: int
    graph_snapshot: dict[str, Any]
    config_hash: str
    published_by: str = ""
