from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


class RetirementEvidenceError(ValueError):
    """Safe retirement rejection without business data or database details."""


REQUIRED_APPROVALS = frozenset(
    {"domain", "runtime", "database", "security_audit", "operations"}
)
DISALLOWED_SOLE_BASIS = frozenset(
    {"zero_rows", "legacy_name", "cutover_name", "local_static_search"}
)


@dataclass(frozen=True)
class RetirementDecision:
    candidate: str
    status: str
    owner: str
    unmet_conditions: tuple[str, ...]


def validate_retirement_evidence(
    evidence: dict[str, Any],
    *,
    required_environments: frozenset[str],
) -> RetirementDecision:
    candidate = str(evidence.get("candidate") or "")
    owner = str(evidence.get("owner") or "")
    if not candidate or not owner:
        raise RetirementEvidenceError("Retirement evidence requires candidate and owner")
    environments = evidence.get("environments")
    if not isinstance(environments, list) or not environments:
        raise RetirementEvidenceError("Retirement evidence requires environment observations")
    by_name = {
        str(item.get("name") or ""): item
        for item in environments
        if isinstance(item, dict)
    }
    observed = frozenset(name for name in by_name if name)
    if required_environments and observed != required_environments:
        raise RetirementEvidenceError(
            "Retirement evidence must cover every declared target environment"
        )
    if len(observed) < 2:
        raise RetirementEvidenceError(
            "Retirement evidence cannot rely on a single-environment observation"
        )
    bases = frozenset(str(item) for item in evidence.get("evidence_basis") or [])
    if not bases or bases <= DISALLOWED_SOLE_BASIS:
        raise RetirementEvidenceError(
            "Retirement evidence cannot rely only on zero rows, naming, or static search"
        )

    unmet: list[str] = []
    for name in sorted(required_environments):
        item = by_name[name]
        for field in (
            "cutover_complete",
            "retention_satisfied",
            "backup_verified",
            "retry_recovery_cycle_observed",
            "production_release_cycle_observed",
        ):
            if item.get(field) is not True:
                unmet.append(f"{name}:{field}")
        for field in ("unresolved_count", "legacy_reader_count", "legacy_writer_count"):
            if not isinstance(item.get(field), int) or int(item[field]) != 0:
                unmet.append(f"{name}:{field}")

    approvals = evidence.get("approvals")
    if not isinstance(approvals, dict):
        approvals = {}
    for approval in sorted(REQUIRED_APPROVALS):
        if approvals.get(approval) is not True:
            unmet.append(f"approval:{approval}")
    if evidence.get("audit_export_complete") is not True:
        unmet.append("audit_export_complete")
    return RetirementDecision(
        candidate=candidate,
        status="approved" if not unmet else "blocked",
        owner=owner,
        unmet_conditions=tuple(unmet),
    )


def load_retirement_decisions(path: Path) -> tuple[RetirementDecision, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetirementEvidenceError("Retirement decision registry could not be read") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
        raise RetirementEvidenceError("Retirement decision registry is invalid")
    decisions: list[RetirementDecision] = []
    for item in payload["decisions"]:
        if not isinstance(item, dict):
            raise RetirementEvidenceError("Retirement decision entry is invalid")
        decision = RetirementDecision(
            candidate=str(item.get("candidate") or ""),
            status=str(item.get("status") or ""),
            owner=str(item.get("owner") or ""),
            unmet_conditions=tuple(str(value) for value in item.get("unmet_conditions") or []),
        )
        if (
            not decision.candidate
            or decision.status not in {"approved", "blocked"}
            or not decision.owner
            or (decision.status == "blocked" and not decision.unmet_conditions)
        ):
            raise RetirementEvidenceError("Retirement decision entry is incomplete")
        decisions.append(decision)
    return tuple(decisions)
