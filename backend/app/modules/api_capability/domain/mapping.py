from __future__ import annotations

import re
from typing import Any

from app.modules.api_capability.domain.contracts import (
    CompiledMappingPlanContract,
    MappingAstContract,
    content_hash,
)
from app.shared.exceptions import NonRetryableExecutionError


_PATH_PATTERN = re.compile(r"^\$(?:\.[A-Za-z][A-Za-z0-9_]*)*$")
_SCALAR_TYPES = frozenset({"string", "integer", "number", "boolean"})
_REQUEST_SOURCES = frozenset({"AGENT_INPUT", "SYSTEM_CONTEXT", "CONSTANT"})
_RESPONSE_SOURCES = frozenset({"RESPONSE", "CONSTANT"})


class MappingCompiler:
    def compile(self, payload: dict[str, Any]) -> dict[str, Any]:
        contract = MappingAstContract.parse(payload)
        normalized = contract.to_dict()
        state = _CompilationState()
        request_plan = self._node(
            normalized["request"],
            path="request",
            stage="request",
            depth=0,
            state=state,
        )
        response_plan = self._node(
            normalized["response"],
            path="response",
            stage="response",
            depth=0,
            state=state,
        )
        result = CompiledMappingPlanContract(
            ast_hash=content_hash(normalized),
            request_plan=request_plan,
            response_plan=response_plan,
        ).to_dict()
        return result

    def _node(
        self,
        node: Any,
        *,
        path: str,
        stage: str,
        depth: int,
        state: _CompilationState,
    ) -> dict[str, Any]:
        if not isinstance(node, dict):
            raise _mapping_error(path, "node must be an object")
        state.count += 1
        if state.count > 500 or depth > 12:
            raise _mapping_error(path, "Mapping exceeds complexity limits")
        operation = str(node.get("op") or "")
        if operation == "object":
            _exact(node, {"op", "fields"}, path)
            fields = node.get("fields")
            if not isinstance(fields, dict) or len(fields) > 100:
                raise _mapping_error(path, "fields must be an object")
            return {
                "op": "object",
                "fields": {
                    str(key): self._node(
                        value,
                        path=f"{path}.{key}",
                        stage=stage,
                        depth=depth + 1,
                        state=state,
                    )
                    for key, value in sorted(fields.items())
                    if _field(key, path)
                },
            }
        if operation == "source":
            source = str(node.get("source") or "")
            allowed_sources = _REQUEST_SOURCES if stage == "request" else _RESPONSE_SOURCES
            if source not in allowed_sources:
                raise _mapping_error(path, f"source {source!r} is not allowed")
            if source == "CONSTANT":
                _exact(node, {"op", "source", "value"}, path)
                value = node.get("value")
                if isinstance(value, (dict, list)) or value is None:
                    raise _mapping_error(
                        path,
                        "constant must be a non-null scalar",
                    )
                return {"op": "source", "source": source, "value": value}
            _exact(node, {"op", "source", "path"}, path)
            source_path = str(node.get("path") or "")
            if not _PATH_PATTERN.fullmatch(source_path):
                raise _mapping_error(path, "source path is invalid")
            return {"op": "source", "source": source, "path": source_path}
        if operation == "array_map":
            _exact(node, {"op", "source", "item"}, path)
            mapped_source = self._node(
                node["source"],
                path=f"{path}.source",
                stage=stage,
                depth=depth + 1,
                state=state,
            )
            if mapped_source["op"] != "source":
                raise _mapping_error(path, "array source must be a source node")
            return {
                "op": "array_map",
                "source": mapped_source,
                "item": self._node(
                    node["item"],
                    path=f"{path}.item",
                    stage=stage,
                    depth=depth + 1,
                    state=state,
                ),
            }
        if operation == "default":
            _exact(node, {"op", "value", "default"}, path)
            fallback = node.get("default")
            if isinstance(fallback, (dict, list)) or fallback is None:
                raise _mapping_error(path, "default must be a non-null scalar")
            return {
                "op": "default",
                "value": self._node(
                    node["value"],
                    path=f"{path}.value",
                    stage=stage,
                    depth=depth + 1,
                    state=state,
                ),
                "default": fallback,
            }
        if operation == "convert":
            _exact(node, {"op", "value", "to"}, path)
            target = str(node.get("to") or "")
            if target not in _SCALAR_TYPES:
                raise _mapping_error(path, "scalar conversion target is invalid")
            return {
                "op": "convert",
                "value": self._node(
                    node["value"],
                    path=f"{path}.value",
                    stage=stage,
                    depth=depth + 1,
                    state=state,
                ),
                "to": target,
            }
        raise _mapping_error(
            path,
            "operation is not in the declarative Mapping whitelist",
        )


class MappingInterpreter:
    def execute(
        self,
        plan: dict[str, Any],
        *,
        agent_input: dict[str, Any],
        system_context: dict[str, Any],
        response: Any = None,
    ) -> Any:
        try:
            return self._node(
                plan,
                roots={
                    "AGENT_INPUT": agent_input,
                    "SYSTEM_CONTEXT": system_context,
                    "RESPONSE": response,
                },
                path="$",
            )
        except _MissingMappingValue as exc:
            raise _execution_error("$", str(exc)) from None

    def _node(
        self,
        node: dict[str, Any],
        *,
        roots: dict[str, Any],
        path: str,
    ) -> Any:
        operation = node["op"]
        if operation == "object":
            return {
                key: self._node(
                    value,
                    roots=roots,
                    path=f"{path}.{key}",
                )
                for key, value in node["fields"].items()
            }
        if operation == "source":
            if node["source"] == "CONSTANT":
                return node["value"]
            return _read_path(
                roots.get(str(node["source"])),
                str(node["path"]),
                path,
            )
        if operation == "default":
            try:
                return self._node(node["value"], roots=roots, path=path)
            except _MissingMappingValue:
                return node["default"]
        if operation == "convert":
            value = self._node(node["value"], roots=roots, path=path)
            return _convert(value, str(node["to"]), path)
        if operation == "array_map":
            source_node = node["source"]
            values = self._node(source_node, roots=roots, path=path)
            if not isinstance(values, list):
                raise _execution_error(path, "array_map source is not an array")
            source_name = str(source_node["source"])
            result: list[Any] = []
            for index, item in enumerate(values):
                item_roots = {**roots, source_name: item}
                result.append(
                    self._node(
                        node["item"],
                        roots=item_roots,
                        path=f"{path}[{index}]",
                    )
                )
            return result
        raise _execution_error(path, "compiled Mapping operation is unknown")


class _CompilationState:
    def __init__(self) -> None:
        self.count = 0


class _MissingMappingValue(Exception):
    pass


def _read_path(root: Any, source_path: str, output_path: str) -> Any:
    current = root
    if source_path == "$":
        return current
    for segment in source_path.removeprefix("$.").split("."):
        if not isinstance(current, dict) or segment not in current:
            raise _MissingMappingValue(f"Missing source {source_path} for {output_path}")
        current = current[segment]
    return current


def _convert(value: Any, target: str, path: str) -> Any:
    try:
        if target == "string":
            if isinstance(value, (dict, list)) or value is None:
                raise ValueError
            return str(value).lower() if isinstance(value, bool) else str(value)
        if target == "integer":
            if isinstance(value, bool):
                raise ValueError
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, str) and re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value):
                return int(value)
            raise ValueError
        if target == "number":
            if isinstance(value, bool):
                raise ValueError
            if isinstance(value, (int, float)):
                return value
            if isinstance(value, str) and re.fullmatch(
                r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?",
                value,
            ):
                return float(value)
            raise ValueError
        if target == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.lower() in {"true", "false"}:
                return value.lower() == "true"
            raise ValueError
    except (TypeError, ValueError):
        raise _execution_error(path, f"cannot convert value to {target}") from None
    raise _execution_error(path, "scalar conversion target is unknown")


def _exact(value: dict[str, Any], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise _mapping_error(
            path,
            f"fields must be exactly {sorted(expected)}",
        )


def _field(value: Any, path: str) -> bool:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]{0,63}",
        value,
    ):
        raise _mapping_error(path, "output field name is invalid")
    return True


def _mapping_error(path: str, reason: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"Invalid Mapping AST at {path}: {reason}",
        safe_message="Handler Mapping 配置无效",
        error_code="mapping_ast_invalid",
        field_errors=[{"field": path, "message": f"{path} Mapping 配置无效"}],
    )


def _execution_error(path: str, reason: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"Mapping execution failed at {path}: {reason}",
        safe_message="外部 API 数据映射失败",
        error_code="mapping_execution_failed",
    )
