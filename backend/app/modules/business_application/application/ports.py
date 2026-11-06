from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ComponentReference:
    id: str
    code: str
    revision: int
    project_code: str
    status: str
    config_hash: str
    runtime_kind: str | None = None
    runtime_protocol_versions: tuple[str, ...] = ()
    ingress_connector_ids: tuple[str, ...] = ()
    direction: str = ""
    component_type: str = ""


class AgentPublicationReader(Protocol):
    def resolve(self, publication_id: str) -> ComponentReference: ...

    def catalog(self) -> list[ComponentReference]: ...


class WorkflowPublicationReader(Protocol):
    def resolve(self, publication_id: str) -> ComponentReference: ...

    def catalog(self, project_code: str) -> list[ComponentReference]: ...


class ChannelConnectorReader(Protocol):
    def webhook_trigger(self, connector_id: str) -> dict[str, Any]: ...

    def resolve(
        self, connector_id: str, direction: str, trigger_type: str = ""
    ) -> ComponentReference: ...

    def catalog(self) -> list[ComponentReference]: ...


class IdentitySubjectReader(Protocol):
    def resolve_service_account(self, user_id: str) -> ComponentReference: ...
