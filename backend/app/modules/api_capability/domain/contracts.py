from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, ClassVar, Self


CONTRACT_SCHEMA_VERSION = 1


class ContractValidationError(ValueError):
    pass


def canonical_json(value: dict[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ContractValidationError("Contract must contain JSON values") from exc


def content_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _parse_object(
    payload: dict[str, Any],
    *,
    contract_name: str,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ContractValidationError(f"{contract_name} must be an object")
    unknown = set(payload).difference(required | optional)
    missing = required.difference(payload)
    if unknown:
        raise ContractValidationError(f"{contract_name} contains unknown fields: {sorted(unknown)}")
    if missing:
        raise ContractValidationError(f"{contract_name} is missing fields: {sorted(missing)}")
    if payload.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        raise ContractValidationError(f"Unsupported {contract_name} schema version")
    canonical_json(payload)
    return payload


def _require_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{field_name} must be an object")
    return value


@dataclass(frozen=True, slots=True)
class PublicSchemaContract:
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    schema_version: int = CONTRACT_SCHEMA_VERSION
    NAME: ClassVar[str] = "public schema contract"

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> Self:
        value = _parse_object(
            payload,
            contract_name=cls.NAME,
            required=frozenset({"schema_version", "input_schema", "output_schema"}),
        )
        return cls(
            input_schema=_require_dict(value["input_schema"], "input_schema"),
            output_schema=_require_dict(value["output_schema"], "output_schema"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }


@dataclass(frozen=True, slots=True)
class MappingAstContract:
    request: dict[str, Any]
    response: dict[str, Any]
    schema_version: int = CONTRACT_SCHEMA_VERSION
    NAME: ClassVar[str] = "Mapping AST contract"

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> Self:
        value = _parse_object(
            payload,
            contract_name=cls.NAME,
            required=frozenset({"schema_version", "request", "response"}),
        )
        return cls(
            request=_require_dict(value["request"], "request"),
            response=_require_dict(value["response"], "response"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request": self.request,
            "response": self.response,
        }


@dataclass(frozen=True, slots=True)
class CompiledMappingPlanContract:
    ast_hash: str
    request_plan: dict[str, Any]
    response_plan: dict[str, Any]
    schema_version: int = CONTRACT_SCHEMA_VERSION
    NAME: ClassVar[str] = "compiled Mapping Plan contract"

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> Self:
        value = _parse_object(
            payload,
            contract_name=cls.NAME,
            required=frozenset(
                {
                    "schema_version",
                    "ast_hash",
                    "request_plan",
                    "response_plan",
                }
            ),
        )
        ast_hash = str(value["ast_hash"])
        if len(ast_hash) != 64:
            raise ContractValidationError("ast_hash must be SHA-256")
        return cls(
            ast_hash=ast_hash,
            request_plan=_require_dict(value["request_plan"], "request_plan"),
            response_plan=_require_dict(value["response_plan"], "response_plan"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ast_hash": self.ast_hash,
            "request_plan": self.request_plan,
            "response_plan": self.response_plan,
        }


@dataclass(frozen=True, slots=True)
class ReleaseSnapshotContract:
    capability: dict[str, Any]
    handler: dict[str, Any]
    connection: dict[str, Any]
    authentication_profile: dict[str, Any]
    mapping_plan: dict[str, Any]
    schema_version: int = CONTRACT_SCHEMA_VERSION
    NAME: ClassVar[str] = "Capability Release snapshot"

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> Self:
        value = _parse_object(
            payload,
            contract_name=cls.NAME,
            required=frozenset(
                {
                    "schema_version",
                    "capability",
                    "handler",
                    "connection",
                    "authentication_profile",
                    "mapping_plan",
                }
            ),
        )
        return cls(
            capability=_require_dict(value["capability"], "capability"),
            handler=_require_dict(value["handler"], "handler"),
            connection=_require_dict(value["connection"], "connection"),
            authentication_profile=_require_dict(
                value["authentication_profile"],
                "authentication_profile",
            ),
            mapping_plan=_require_dict(value["mapping_plan"], "mapping_plan"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "capability": self.capability,
            "handler": self.handler,
            "connection": self.connection,
            "authentication_profile": self.authentication_profile,
            "mapping_plan": self.mapping_plan,
        }


@dataclass(frozen=True, slots=True)
class RuntimeErrorContract:
    error_code: str
    safe_message: str
    retryable: bool
    diagnostics: dict[str, Any]
    schema_version: int = CONTRACT_SCHEMA_VERSION
    NAME: ClassVar[str] = "Capability runtime error"

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> Self:
        value = _parse_object(
            payload,
            contract_name=cls.NAME,
            required=frozenset(
                {
                    "schema_version",
                    "error_code",
                    "safe_message",
                    "retryable",
                    "diagnostics",
                }
            ),
        )
        if not isinstance(value["retryable"], bool):
            raise ContractValidationError("retryable must be a boolean")
        if not str(value["error_code"]) or not str(value["safe_message"]):
            raise ContractValidationError("Runtime error code and safe message are required")
        safe_message_value = str(value["safe_message"])
        return cls(
            error_code=str(value["error_code"]),
            safe_message=safe_message_value,
            retryable=bool(value["retryable"]),
            diagnostics=_require_dict(value["diagnostics"], "diagnostics"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "error_code": self.error_code,
            "safe_message": self.safe_message,
            "retryable": self.retryable,
            "diagnostics": self.diagnostics,
        }
