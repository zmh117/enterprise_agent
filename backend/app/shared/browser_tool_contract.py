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

    return {
        "search_recording": {
            "description": "在本轮绑定的录制中按时间、操作和接口筛选证据，返回来源标识及采集缺口。",
            "schema": resolve(definitions["SearchRecording"]),
        },
        "get_recording_evidence": {
            "description": "读取当前录制中指定证据的请求、响应或操作明细和省略说明。",
            "schema": resolve(definitions["GetRecordingEvidence"]),
        },
    }
