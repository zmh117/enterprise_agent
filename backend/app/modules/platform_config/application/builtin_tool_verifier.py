from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.modules.internal_tools.domain import HandlerDefinition


@dataclass(frozen=True)
class BuiltinToolVerificationResult:
    status: str
    summary: dict[str, Any]
    safe_error_summary: str = ""


class BuiltinToolVerifier:
    """Execute only verifier checks compiled into the code Manifest."""

    _SUPPORTED_CHECKS = frozenset(
        {
            "manifest.contract",
            "implementation.binding",
            "readonly.boundary",
            "resource_slot.contract",
        }
    )

    def verify(
        self,
        definition: HandlerDefinition,
    ) -> BuiltinToolVerificationResult:
        checks: list[dict[str, str]] = []
        failed = False
        for code in definition.verifier_plan.checks:
            passed = self._run_check(code, definition)
            checks.append(
                {
                    "code": code,
                    "status": "PASSED" if passed else "FAILED",
                }
            )
            failed = failed or not passed
        summary: dict[str, Any] = {
            "check_count": len(checks),
            "checks": checks,
            "truncated": False,
        }
        encoded = json.dumps(
            summary,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(encoded) > definition.verifier_plan.max_result_bytes:
            summary = {
                "check_count": len(checks),
                "checks": [],
                "truncated": True,
            }
        return BuiltinToolVerificationResult(
            status="FAILED" if failed else "PASSED",
            summary=summary,
            safe_error_summary=(
                "one or more fixed verifier checks failed" if failed else ""
            ),
        )

    def _run_check(
        self,
        code: str,
        definition: HandlerDefinition,
    ) -> bool:
        if code not in self._SUPPORTED_CHECKS:
            return False
        if code == "manifest.contract":
            return bool(
                definition.tool_identifier
                and len(definition.manifest_hash) == 64
                and len(definition.public_schema_hash) == 64
            )
        if code == "implementation.binding":
            return bool(
                definition.implementation_key
                and len(definition.implementation_digest) == 64
            )
        if code == "readonly.boundary":
            return bool(
                definition.safety_boundary.read_only
                and definition.safety_boundary.allowed_effects
                and definition.safety_boundary.required_guards
            )
        return bool(
            definition.resource_slots
            and all(slot.required for slot in definition.resource_slots)
        )


def verification_input_hash(definition: HandlerDefinition) -> str:
    canonical = json.dumps(
        {
            "tool_identifier": definition.tool_identifier,
            "handler_version": definition.handler_version,
            "implementation_digest": definition.implementation_digest,
            "manifest_hash": definition.manifest_hash,
            "public_schema_hash": definition.public_schema_hash,
            "verifier_plan": definition.verifier_plan.public(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
