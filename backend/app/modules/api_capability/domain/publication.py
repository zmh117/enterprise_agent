from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import CapabilityIdentifier


class PublicationCapabilityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AgentCapabilityEnvelopeEntry:
    identifier: CapabilityIdentifier
    release_id: str
    release_revision: int
    capability_revision_id: str
    handler_revision_id: str
    schema_hash: str
    description: str


@dataclass(frozen=True, slots=True)
class ApplicationCapabilityAllowlistEntry:
    identifier: CapabilityIdentifier
    release_id: str


def read_agent_capability_envelope(
    snapshot: dict[str, Any],
) -> tuple[AgentCapabilityEnvelopeEntry, ...]:
    raw = snapshot.get("capability_envelope")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise PublicationCapabilityError("Agent capability_envelope must be an array")
    entries: list[AgentCapabilityEnvelopeEntry] = []
    identifiers: set[str] = set()
    for index, item in enumerate(raw):
        value = _require_entry(item, f"capability_envelope[{index}]")
        identifier = CapabilityIdentifier(str(value.get("identifier") or ""))
        if identifier.value in identifiers:
            raise PublicationCapabilityError(
                "Agent capability envelope contains duplicate Identifier"
            )
        identifiers.add(identifier.value)
        entries.append(
            AgentCapabilityEnvelopeEntry(
                identifier=identifier,
                release_id=_required_text(value, "release_id"),
                release_revision=_positive_int(value, "release_revision"),
                capability_revision_id=_required_text(value, "capability_revision_id"),
                handler_revision_id=_required_text(value, "handler_revision_id"),
                schema_hash=_sha256(value, "schema_hash"),
                description=_required_text(value, "description"),
            )
        )
    return tuple(entries)


def read_application_capability_allowlist(
    snapshot: dict[str, Any],
) -> tuple[ApplicationCapabilityAllowlistEntry, ...]:
    raw = snapshot.get("capability_allowlist")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise PublicationCapabilityError("Application capability_allowlist must be an array")
    entries: list[ApplicationCapabilityAllowlistEntry] = []
    identifiers: set[str] = set()
    for index, item in enumerate(raw):
        value = _require_entry(item, f"capability_allowlist[{index}]")
        identifier = CapabilityIdentifier(str(value.get("identifier") or ""))
        if identifier.value in identifiers:
            raise PublicationCapabilityError(
                "Application capability allowlist contains duplicate Identifier"
            )
        identifiers.add(identifier.value)
        entries.append(
            ApplicationCapabilityAllowlistEntry(
                identifier=identifier,
                release_id=_required_text(value, "release_id"),
            )
        )
    return tuple(entries)


def _require_entry(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PublicationCapabilityError(f"{path} must be an object")
    return value


def _required_text(value: dict[str, Any], field_name: str) -> str:
    result = str(value.get(field_name) or "")
    if not result:
        raise PublicationCapabilityError(f"{field_name} is required")
    return result


def _positive_int(value: dict[str, Any], field_name: str) -> int:
    raw = value.get(field_name)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise PublicationCapabilityError(f"{field_name} must be positive")
    return raw


def _sha256(value: dict[str, Any], field_name: str) -> str:
    result = _required_text(value, field_name)
    if len(result) != 64:
        raise PublicationCapabilityError(f"{field_name} must be SHA-256")
    return result
