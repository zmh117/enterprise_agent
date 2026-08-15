from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Mapping


FILE_MCP_SERVER_CODE = "file-service"
FILE_MCP_PATH = "/mcp"
FILE_TRANSFER_PROTOCOL = "enterprise-agent.file-transfer/v1"
FILE_TRANSFER_META_KEY = "enterprise-agent/file-transfer"
ATTACHMENT_TASK_CONTRACT_VERSION = "attachment-task/v1"

_OPAQUE_ID = {
    "type": "string",
    "minLength": 1,
    "maxLength": 128,
    "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
}
_DISPLAY_NAME = {
    "type": "string",
    "minLength": 1,
    "maxLength": 255,
    "pattern": r"^[^/\\\x00]+\.txt$",
}


@dataclass(frozen=True, slots=True)
class FileToolDefinition:
    identifier: str
    description: str
    input_schema: Mapping[str, Any]
    schema_hash: str
    operation: str
    mutating: bool


def _schema_hash(schema: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _tool(
    identifier: str,
    description: str,
    schema: dict[str, Any],
    *,
    operation: str,
    mutating: bool,
) -> FileToolDefinition:
    return FileToolDefinition(
        identifier=identifier,
        description=description,
        input_schema=MappingProxyType(schema),
        schema_hash=_schema_hash(schema),
        operation=operation,
        mutating=mutating,
    )


_EMPTY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
}

_LIST_FILES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "cursor": {"type": "string", "minLength": 1, "maxLength": 256},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
    },
}

_FILE_VERSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["file_id", "version_id"],
    "properties": {
        "file_id": dict(_OPAQUE_ID),
        "version_id": dict(_OPAQUE_ID),
    },
}

_MATERIALIZE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["file_id", "version_id"],
    "properties": {
        "file_id": dict(_OPAQUE_ID),
        "version_id": dict(_OPAQUE_ID),
        "preferred_name": dict(_DISPLAY_NAME),
    },
}

_COMMIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "sandbox_entry_handle",
        "display_name",
        "user_intent",
        "delivery_mode",
    ],
    "properties": {
        "sandbox_entry_handle": dict(_OPAQUE_ID),
        "file_id": dict(_OPAQUE_ID),
        "base_version_id": dict(_OPAQUE_ID),
        "display_name": dict(_DISPLAY_NAME),
        "user_intent": {"type": "string", "enum": ["MODIFY", "GENERATE", "SAVE"]},
        "delivery_mode": {
            "type": "string",
            "enum": ["DEFAULT", "WORKSPACE_ONLY"],
        },
    },
    "oneOf": [
        {"required": ["file_id", "base_version_id"]},
        {
            "not": {
                "anyOf": [
                    {"required": ["file_id"]},
                    {"required": ["base_version_id"]},
                ]
            }
        },
    ],
}


FILE_TOOL_MANIFEST: Mapping[str, FileToolDefinition] = MappingProxyType(
    {
        "task_workspace_get": _tool(
            "task_workspace_get",
            "查询当前 Job 绑定的任务工作区安全摘要；工作区身份从 Principal 与 Job 解析。",
            dict(_EMPTY_SCHEMA),
            operation="task_workspace.read",
            mutating=False,
        ),
        "task_workspace_list_files": _tool(
            "task_workspace_list_files",
            "列出当前 Job 可见的工作区文件元数据，不返回正文或对象位置。",
            _LIST_FILES_SCHEMA,
            operation="task_workspace.files.list",
            mutating=False,
        ),
        "file_get_metadata": _tool(
            "file_get_metadata",
            "查询当前 Job File Manifest 中精确文件版本的安全元数据。",
            dict(_FILE_VERSION_SCHEMA),
            operation="file.metadata.read",
            mutating=False,
        ),
        "file_prepare_materialization": _tool(
            "file_prepare_materialization",
            "为 Manifest 中的精确版本创建一次受控物化意图，字节由 Runtime 文件桥传输。",
            _MATERIALIZE_SCHEMA,
            operation="file.materialization.prepare",
            mutating=False,
        ),
        "file_create_commit_intent": _tool(
            "file_create_commit_intent",
            "为显式选中的沙盒 TXT 创建提交意图，不在 MCP JSON 中传输文件正文。",
            _COMMIT_SCHEMA,
            operation="file.commit.prepare",
            mutating=True,
        ),
        "file_retain_version": _tool(
            "file_retain_version",
            "按当前保留策略提升一个已授权精确版本，重复调用不延长到期时间。",
            dict(_FILE_VERSION_SCHEMA),
            operation="file.version.retain",
            mutating=True,
        ),
        "file_deliver_version": _tool(
            "file_deliver_version",
            "把已授权精确版本交付到当前 Job 冻结的 reply route。",
            dict(_FILE_VERSION_SCHEMA),
            operation="file.version.deliver",
            mutating=True,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class InternalStreamingEndpoint:
    method: Literal["GET", "PUT", "POST"]
    path_template: str
    request_content_type: str
    response_content_type: str
    principal_kind: Literal["job", "service"]
    maximum_body_bytes: int


INTERNAL_STREAMING_API: tuple[InternalStreamingEndpoint, ...] = (
    InternalStreamingEndpoint(
        method="GET",
        path_template="/internal/v1/file-transfers/{transfer_id}/content",
        request_content_type="",
        response_content_type="application/octet-stream",
        principal_kind="job",
        maximum_body_bytes=0,
    ),
    InternalStreamingEndpoint(
        method="PUT",
        path_template="/internal/v1/file-commits/{commit_id}/content",
        request_content_type="application/octet-stream",
        response_content_type="application/json",
        principal_kind="job",
        maximum_body_bytes=15 * 1024 * 1024,
    ),
    InternalStreamingEndpoint(
        method="POST",
        path_template="/internal/v1/attachments/{attachment_id}/content",
        request_content_type="application/octet-stream",
        response_content_type="application/json",
        principal_kind="service",
        maximum_body_bytes=25 * 1024 * 1024,
    ),
)


ATTACHMENT_TASK_V0_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["attachment_id"],
        "properties": {
            "attachment_id": dict(_OPAQUE_ID),
            "correlation_id": {"type": "string", "maxLength": 128},
        },
    }
)

ATTACHMENT_TASK_V1_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "contract_version",
            "attachment_id",
            "correlation_id",
            "source_idempotency_key",
        ],
        "properties": {
            "contract_version": {
                "type": "string",
                "const": ATTACHMENT_TASK_CONTRACT_VERSION,
            },
            "attachment_id": dict(_OPAQUE_ID),
            "correlation_id": {"type": "string", "maxLength": 128},
            "source_idempotency_key": dict(_OPAQUE_ID),
            "requested_at": {"type": "string", "format": "date-time"},
        },
    }
)


@dataclass(frozen=True, slots=True)
class FileErrorDefinition:
    retry_class: Literal["NEVER", "TRANSIENT", "CONFIGURATION"]
    safe_message: str


FILE_ERROR_CATALOG: Mapping[str, FileErrorDefinition] = MappingProxyType(
    {
        "file_principal_invalid": FileErrorDefinition("NEVER", "文件访问身份无效"),
        "file_job_not_running": FileErrorDefinition("NEVER", "当前任务已不能访问文件"),
        "file_tool_not_frozen": FileErrorDefinition("NEVER", "当前任务未授权该文件工具"),
        "file_schema_drift": FileErrorDefinition("CONFIGURATION", "文件工具版本不匹配"),
        "file_workspace_not_found": FileErrorDefinition("NEVER", "当前任务没有可用工作区"),
        "file_access_denied": FileErrorDefinition("NEVER", "无权访问该文件"),
        "file_manifest_version_not_found": FileErrorDefinition(
            "NEVER", "文件版本不在当前任务清单中"
        ),
        "file_content_unavailable": FileErrorDefinition(
            "NEVER", "文件内容已不可用，请重新发送文件"
        ),
        "file_type_unsupported": FileErrorDefinition("NEVER", "第一阶段只支持 UTF-8 TXT"),
        "file_encoding_invalid": FileErrorDefinition("NEVER", "TXT 必须使用 UTF-8 编码"),
        "file_size_exceeded": FileErrorDefinition("NEVER", "TXT 文件超过 15 MiB"),
        "file_count_quota_exceeded": FileErrorDefinition("NEVER", "工作区文件数量已达上限"),
        "file_workspace_quota_exceeded": FileErrorDefinition("NEVER", "工作区临时容量已达上限"),
        "file_transfer_control_invalid": FileErrorDefinition("NEVER", "文件传输控制信息无效"),
        "file_transfer_protocol_unsupported": FileErrorDefinition(
            "CONFIGURATION", "文件传输协议不受支持"
        ),
        "file_transfer_action_unsupported": FileErrorDefinition(
            "NEVER", "文件传输动作不受支持"
        ),
        "file_transfer_path_invalid": FileErrorDefinition("NEVER", "沙盒文件路径无效"),
        "file_transfer_handle_conflict": FileErrorDefinition("NEVER", "沙盒文件句柄冲突"),
        "file_transfer_handle_unknown": FileErrorDefinition("NEVER", "沙盒文件句柄不存在"),
        "file_transfer_size_mismatch": FileErrorDefinition("TRANSIENT", "文件传输大小不匹配"),
        "file_transfer_integrity_mismatch": FileErrorDefinition("TRANSIENT", "文件完整性校验失败"),
        "file_transfer_receipt_mismatch": FileErrorDefinition("TRANSIENT", "文件提交回执不匹配"),
        "file_commit_conflict": FileErrorDefinition("NEVER", "文件已经产生新版本，需要显式合并"),
        "file_commit_idempotency_conflict": FileErrorDefinition("NEVER", "提交标识已绑定不同内容"),
        "file_commit_expired": FileErrorDefinition("NEVER", "文件提交意图已过期"),
        "file_service_unavailable": FileErrorDefinition("TRANSIENT", "文件服务暂时不可用"),
    }
)
