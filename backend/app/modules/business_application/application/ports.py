from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ComponentReference:
    id: str
    code: str
    revision: int
    project_code: str
    status: str
    config_hash: str
    direction: str = ""
    component_type: str = ""


class AgentPublicationReader(Protocol):
    def resolve(self, publication_id: str) -> ComponentReference: ...

    def catalog(self, project_code: str) -> list[ComponentReference]: ...


class WorkflowPublicationReader(Protocol):
    def resolve(self, publication_id: str) -> ComponentReference: ...

    def catalog(self, project_code: str) -> list[ComponentReference]: ...


class ChannelConnectorReader(Protocol):
    def resolve(self, connector_id: str, direction: str) -> ComponentReference: ...

    def catalog(self) -> list[ComponentReference]: ...


class IdentitySubjectReader(Protocol):
    def resolve_service_account(self, user_id: str) -> ComponentReference: ...


class CapabilityCatalogReader(Protocol):
    def resolve(
        self, code: str, version_constraint: str, environment: str
    ) -> ComponentReference: ...

