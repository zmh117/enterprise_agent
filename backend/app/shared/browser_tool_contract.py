"""The two model-facing schemas are the same closed schemas as the wire contract."""

import json
from pathlib import Path
from typing import Any


def recording_tool_definitions() -> dict[str, dict[str, Any]]:
    source = (
        Path(__file__).resolve().parents[3] / "contracts/browser-extension/v1/protocol.schema.json"
    )
    definitions = json.loads(source.read_text())["$defs"]

    def resolve(value: Any) -> Any:
        if isinstance(value, dict):
            if "$ref" in value:
                return resolve(definitions[value["$ref"].split("/")[-1]])
            return {key: resolve(child) for key, child in value.items()}
        if isinstance(value, list):
            return [resolve(child) for child in value]
        return value

    def with_live(legacy: str, live: str) -> dict[str, Any]:
        existing = resolve(definitions[legacy])
        schema = {
            **existing,
            "properties": {**existing["properties"], "live": resolve(definitions[live])},
        }
        schema.pop("required", None)
        return schema

    return {
        "search_recording": {
            "description": "按本轮绑定检索浏览器证据。持续录制使用 live 对象，默认查询发送页，可按接口路径、状态和请求键筛选。封存录制使用顶层筛选字段。",
            "schema": with_live("SearchRecording", "LiveSearch"),
        },
        "get_recording_evidence": {
            "description": "用持续证据的 live.reference 分页读取操作、rrweb 或接口详情，或用封存录制的 evidence_id 读取原有明细。",
            "schema": with_live("GetRecordingEvidence", "LiveDetail"),
        },
    }
