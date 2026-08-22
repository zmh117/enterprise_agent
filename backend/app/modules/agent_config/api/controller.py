from __future__ import annotations

from typing import Any, Literal

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
    runtime: str = Field(default="claude_agent_sdk", pattern="^claude_agent_sdk$")
    model: str = Field(min_length=1, max_length=200)
    model_connection_revision_id: str = Field(default="", max_length=200)


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
    skills: list[str] = Field(default_factory=list)
    routing: RoutingRequest
    channels: ChannelsRequest
    mcp_tool_ids: list[str] = Field(
        default_factory=list,
        max_length=100,
    )


class AgentDraftRequest(StrictRequest):
    expected_revision: int = Field(ge=0)
    config: AgentDraftConfigRequest


class AgentCreateRequest(StrictRequest):
    code: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$",
    )
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    project_code: str = Field(
        default="default",
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    runtime_kind: Literal["python-v1"]


class RevisionRequest(BaseModel):
    revision_id: str


class RollbackRequest(BaseModel):
    publication_id: str


def build_agent_config_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin/agents", tags=["agent-configuration"])

    @router.get("")
    def list_agents(request: Request) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent",
            resource_code="*",
            action="read",
        )
        can_create = (
            container(request)
            .authorization_evaluator.decide(
                user_id=principal.user_id,
                resource_type="agent",
                resource_code="*",
                action="edit",
            )
            .allowed
        )
        return {
            "agents": container(request).agent_config_service.list_agents(),
            "permissions": {"can_create": can_create},
        }

    @router.post("")
    def create_agent(request: Request, payload: AgentCreateRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent",
            resource_code="*",
            action="edit",
            csrf=True,
        )
        try:
            created: dict[str, Any] = container(request).agent_config_service.create_agent(
                actor_id=principal.user_id,
                code=payload.code,
                name=payload.name,
                description=payload.description,
                project_code=payload.project_code,
                runtime_kind=payload.runtime_kind,
                correlation_id=str(getattr(request.state, "correlation_id", "") or ""),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return created

    @router.get("/{agent_code}")
    def get_agent(request: Request, agent_code: str) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent",
            resource_code=agent_code,
            action="read",
        )
        try:
            agent = container(request).agent_config_service.get(agent_code)
            authorization = container(request).authorization_evaluator
            agent["permissions"] = {
                "can_edit_profile": authorization.decide(
                    user_id=principal.user_id,
                    resource_type="agent",
                    resource_code=agent_code,
                    action="edit",
                ).allowed,
                "can_publish": authorization.decide(
                    user_id=principal.user_id,
                    resource_type="agent",
                    resource_code=agent_code,
                    action="publish",
                ).allowed,
                "can_manage_credential": authorization.decide(
                    user_id=principal.user_id,
                    resource_type="secret",
                    resource_code="*",
                    action="manage",
                ).allowed,
            }
            agent["permissions"]["can_test_connection"] = agent["permissions"][
                "can_manage_credential"
            ]
            return {"agent": agent}
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
                correlation_id=str(getattr(request.state, "correlation_id", "") or ""),
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
                correlation_id=str(getattr(request.state, "correlation_id", "") or ""),
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
        require_action(request, resource_type="agent", resource_code=agent_code, action="read")
        try:
            values = container(request).agent_config_service.publications(agent_code)
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"publications": values}

    @router.get("/{agent_code}/effective-config")
    def effective(request: Request, agent_code: str) -> dict[str, Any]:
        require_action(request, resource_type="agent", resource_code=agent_code, action="read")
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
                    "read_only_mcp_tools": True,
                    "authorization_required": True,
                },
            }
        }

    return router
