from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.api.dependencies import (
    container,
    current_principal,
    handle_exception,
    require_action,
)
from app.shared.exceptions import PermissionDenied


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateAgentRequest(StrictRequest):
    expected_revision: Literal[0]
    code: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    project_code: str = Field(default="default", min_length=2, max_length=120)


class UpdateAgentRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    project_code: str = Field(min_length=2, max_length=120)
    status: Literal["enabled", "disabled", "archived"]


class ModelPolicyRequest(StrictRequest):
    runtime: Literal["claude_agent_sdk"] = "claude_agent_sdk"
    model: str = Field(min_length=1, max_length=200)
    model_connection_revision_id: str = Field(default="", max_length=200)


class ExecutionRequest(StrictRequest):
    max_turns: int = Field(default=12, ge=1, le=100)
    timeout_seconds: int = Field(default=300, ge=10, le=3600)


class RoutingRequest(StrictRequest):
    project_code: str = Field(default="default", min_length=2, max_length=120)


class ChannelsRequest(StrictRequest):
    ingress: list[str] = Field(default_factory=list, max_length=20)
    delivery: list[str] = Field(default_factory=list, max_length=20)


class AgentDraftConfigRequest(StrictRequest):
    business_role: str = Field(default="", max_length=500)
    business_instructions: str = Field(default="", max_length=20000)
    model_policy: ModelPolicyRequest
    execution: ExecutionRequest = Field(default_factory=ExecutionRequest)
    skills: list[str] = Field(default_factory=list, max_length=100)
    routing: RoutingRequest = Field(default_factory=RoutingRequest)
    channels: ChannelsRequest = Field(default_factory=ChannelsRequest)
    mcp_tool_publication_ids: list[str] = Field(default_factory=list, max_length=100)


class AgentDraftRequest(StrictRequest):
    expected_revision: int = Field(ge=0)
    config: AgentDraftConfigRequest


class RevisionRequest(StrictRequest):
    revision_id: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=1)


class RollbackRequest(StrictRequest):
    publication_id: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=1)


def build_agent_config_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin/agents", tags=["agent-configuration"])

    @router.get("")
    def list_agents(request: Request) -> dict[str, Any]:
        principal = current_principal(request)
        authorization = container(request).authorization_evaluator
        values = [
            value
            for value in container(request).agent_config_service.list_agents()
            if authorization.decide(
                user_id=principal.user_id,
                resource_type="agent",
                resource_code=str(value["code"]),
                action="read",
            ).allowed
            or authorization.decide(
                user_id=principal.user_id,
                resource_type="agent",
                resource_code=str(value["code"]),
                action="edit",
            ).allowed
        ]
        return {
            "agents": values,
            "permissions": {
                "can_create": authorization.decide(
                    user_id=principal.user_id,
                    resource_type="agent",
                    resource_code="*",
                    action="edit",
                ).allowed
            },
        }

    @router.post("")
    def create_agent(
        request: Request,
        payload: CreateAgentRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent",
            resource_code="*",
            action="edit",
            csrf=True,
        )
        try:
            agent = container(request).agent_config_service.create(
                actor_id=principal.user_id,
                expected_revision=payload.expected_revision,
                idempotency_key=idempotency_key,
                **payload.model_dump(exclude={"expected_revision"}),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"agent": _safe_agent_detail(agent)}

    @router.get("/{agent_code}")
    def get_agent(request: Request, agent_code: str) -> dict[str, Any]:
        principal = current_principal(request)
        authorization = container(request).authorization_evaluator
        readable = authorization.decide(
            user_id=principal.user_id,
            resource_type="agent",
            resource_code=agent_code,
            action="read",
        ).allowed
        editable = authorization.decide(
            user_id=principal.user_id,
            resource_type="agent",
            resource_code=agent_code,
            action="edit",
        ).allowed
        if not readable and not editable:
            raise HTTPException(status_code=404, detail="未找到 Agent")
        try:
            agent = container(request).agent_config_service.get(agent_code)
        except PermissionDenied as exc:
            raise HTTPException(status_code=404, detail="未找到 Agent") from exc
        except Exception as exc:
            raise handle_exception(exc) from exc
        agent["permissions"] = {
            "can_edit": editable,
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
        return {"agent": _safe_agent_detail(agent)}

    @router.put("/{agent_code}")
    def update_agent(
        request: Request,
        agent_code: str,
        payload: UpdateAgentRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent",
            resource_code=agent_code,
            action="edit",
            csrf=True,
        )
        try:
            agent = container(request).agent_config_service.update_definition(
                actor_id=principal.user_id,
                agent_code=agent_code,
                idempotency_key=idempotency_key,
                **payload.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"agent": _safe_agent_detail(agent)}

    @router.put("/{agent_code}/draft")
    def save_draft(
        request: Request,
        agent_code: str,
        payload: AgentDraftRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
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
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"revision": revision}

    @router.post("/{agent_code}/validate")
    def validate(
        request: Request,
        agent_code: str,
        payload: RevisionRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
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
                expected_revision=payload.expected_revision,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"revision": revision}

    @router.post("/{agent_code}/publish")
    def publish(
        request: Request,
        agent_code: str,
        payload: RevisionRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
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
                expected_revision=payload.expected_revision,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"publication": _safe_publication(publication)}

    @router.post("/{agent_code}/rollback")
    def rollback(
        request: Request,
        agent_code: str,
        payload: RollbackRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
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
                expected_revision=payload.expected_revision,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"publication": _safe_publication(publication)}

    @router.get("/{agent_code}/publications")
    def publications(request: Request, agent_code: str) -> dict[str, Any]:
        require_action(
            request,
            resource_type="agent",
            resource_code=agent_code,
            action="read",
        )
        try:
            values = container(request).agent_config_service.publications(agent_code)
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"publications": [_safe_publication(value) for value in values]}

    @router.get("/{agent_code}/effective-config")
    def effective(request: Request, agent_code: str) -> dict[str, Any]:
        require_action(
            request,
            resource_type="agent",
            resource_code=agent_code,
            action="read",
        )
        try:
            publication = container(request).agent_config_service.current_publication(agent_code)
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {
            "effective": {
                "publication_id": publication["id"],
                "revision": publication["revision"],
                "config_hash": publication["config_hash"],
                "snapshot": _safe_snapshot(dict(publication["snapshot"])),
                "platform_enforced": {
                    "read_only_mcp_only": True,
                    "built_in_mutation_tools_disabled": True,
                    "authorization_required": True,
                    "runtime_protocol_version": "1.0",
                },
            }
        }

    return router


def _safe_agent_detail(agent: dict[str, Any]) -> dict[str, Any]:
    result = dict(agent)
    current = result.get("current_publication")
    if isinstance(current, dict):
        result["current_publication"] = _safe_publication(current)
    return result


def _safe_publication(publication: dict[str, Any]) -> dict[str, Any]:
    result = dict(publication)
    snapshot = result.get("snapshot")
    if isinstance(snapshot, dict):
        result["snapshot"] = _safe_snapshot(snapshot)
    return result


def _safe_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    result = dict(snapshot)
    connection = result.get("model_connection")
    if isinstance(connection, dict):
        safe_connection = {
            key: connection[key]
            for key in ("id", "code", "revision_id", "revision", "config_hash")
            if key in connection
        }
        config = connection.get("config")
        if isinstance(config, dict):
            safe_connection["config"] = {
                key: config[key]
                for key in (
                    "protocol",
                    "model",
                    "default_opus_model",
                    "default_sonnet_model",
                    "default_haiku_model",
                    "subagent_model",
                    "effort_level",
                )
                if key in config
            }
        result["model_connection"] = safe_connection
    return result
