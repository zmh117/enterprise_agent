from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.api.dependencies import (
    container,
    handle_exception,
    require_action,
)


DEFAULT_AGENT = "default-diagnostic-agent"


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelPolicyRequest(StrictRequest):
    model: str = Field(min_length=1, max_length=200)


class ExecutionRequest(StrictRequest):
    max_turns: int = Field(ge=1, le=100)
    timeout_seconds: int = Field(ge=10, le=3600)


class RoutingRequest(StrictRequest):
    project_code: str = Field(min_length=1, max_length=120)


class ChannelsRequest(StrictRequest):
    ingress: list[str] = Field(default_factory=list)
    delivery: list[str] = Field(default_factory=list)


class AgentDraftConfigRequest(StrictRequest):
    business_role: str = Field(default="", max_length=500)
    business_instructions: str = Field(default="", max_length=20000)
    model_policy: ModelPolicyRequest
    execution: ExecutionRequest
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    routing: RoutingRequest
    channels: ChannelsRequest


class AgentDraftRequest(StrictRequest):
    expected_revision: int = Field(ge=0)
    config: AgentDraftConfigRequest


class RevisionRequest(BaseModel):
    revision_id: str


class RollbackRequest(BaseModel):
    publication_id: str


def build_agent_config_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin/agents", tags=["agent-configuration"])

    @router.get("")
    def list_agents(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="agent", resource_code="*", action="edit")
        return {"agents": container(request).agent_config_service.list_agents()}

    @router.get("/{agent_code}")
    def get_agent(request: Request, agent_code: str) -> dict[str, Any]:
        require_action(request, resource_type="agent", resource_code=agent_code, action="edit")
        try:
            return {"agent": container(request).agent_config_service.get(agent_code)}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.put("/{agent_code}/draft")
    def save_draft(request: Request, agent_code: str, payload: AgentDraftRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent",
            resource_code=agent_code,
            action="edit",
            csrf=True,
        )
        try:
            revision = container(request).agent_config_service.save_draft(
                actor_id=principal.user_id,
                agent_code=agent_code,
                expected_revision=payload.expected_revision,
                config=payload.config.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"revision": revision}

    @router.post("/{agent_code}/validate")
    def validate(request: Request, agent_code: str, payload: RevisionRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent",
            resource_code=agent_code,
            action="edit",
            csrf=True,
        )
        try:
            revision = container(request).agent_config_service.validate_revision(
                actor_id=principal.user_id,
                agent_code=agent_code,
                revision_id=payload.revision_id,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"revision": revision}

    @router.post("/{agent_code}/publish")
    def publish(request: Request, agent_code: str, payload: RevisionRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent",
            resource_code=agent_code,
            action="publish",
            csrf=True,
        )
        try:
            publication = container(request).agent_config_service.publish(
                actor_id=principal.user_id,
                agent_code=agent_code,
                revision_id=payload.revision_id,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"publication": publication}

    @router.post("/{agent_code}/rollback")
    def rollback(request: Request, agent_code: str, payload: RollbackRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent",
            resource_code=agent_code,
            action="publish",
            csrf=True,
        )
        try:
            publication = container(request).agent_config_service.rollback(
                actor_id=principal.user_id,
                agent_code=agent_code,
                publication_id=payload.publication_id,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"publication": publication}

    @router.get("/{agent_code}/publications")
    def publications(request: Request, agent_code: str) -> dict[str, Any]:
        require_action(request, resource_type="agent", resource_code=agent_code, action="edit")
        try:
            values = container(request).agent_config_service.publications(agent_code)
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"publications": values}

    @router.get("/{agent_code}/effective-config")
    def effective(request: Request, agent_code: str) -> dict[str, Any]:
        require_action(request, resource_type="agent", resource_code=agent_code, action="edit")
        try:
            publication = container(request).agent_config_service.current_publication(agent_code)
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {
            "effective": {
                "publication_id": publication["id"],
                "revision": publication["revision"],
                "config_hash": publication["config_hash"],
                "snapshot": publication["snapshot"],
                "platform_enforced": {
                    "read_only_tools": True,
                    "built_in_mutation_tools_disabled": True,
                    "authorization_required": True,
                },
            }
        }

    return router
