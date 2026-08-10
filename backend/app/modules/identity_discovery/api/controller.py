from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.api.dependencies import container, handle_exception, require_action


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _BindCandidateRequest(_StrictRequest):
    target_user_id: str = Field(min_length=1, max_length=200)
    expected_candidate_revision: int = Field(ge=1)
    expected_user_revision: int = Field(ge=1)
    initial_role_ids: list[str] = Field(default_factory=list, max_length=50)
    bind_without_access_confirmed: bool = False
    replace_current_confirmed: bool = False


def build_identity_discovery_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/admin/dingtalk-identity-candidates",
        tags=["dingtalk-identity-discovery"],
    )

    @router.get("")
    def list_candidates(
        request: Request,
        search: str = "",
        conversation_scope: Literal["all", "direct", "group", "both"] = "all",
        limit: int = 25,
        cursor: str = "",
    ) -> dict[str, object]:
        require_action(request, resource_type="identity", resource_code="*", action="read")
        try:
            return container(request).identity_discovery_service.list_candidates(
                search=search,
                conversation_scope=conversation_scope,
                limit=limit,
                cursor=cursor,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/count")
    def count_candidates(request: Request) -> dict[str, int]:
        require_action(request, resource_type="identity", resource_code="*", action="read")
        return {"count": container(request).identity_discovery_service.count_candidates()}

    @router.get("/{candidate_id}")
    def candidate_detail(request: Request, candidate_id: str) -> dict[str, object]:
        require_action(request, resource_type="identity", resource_code="*", action="read")
        try:
            return {
                "candidate": container(request).identity_discovery_service.get_candidate(
                    candidate_id
                )
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/{candidate_id}/bind")
    def bind_candidate(
        request: Request,
        candidate_id: str,
        payload: _BindCandidateRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        del idempotency_key
        principal = require_action(
            request,
            resource_type="identity",
            resource_code=candidate_id,
            action="manage",
            csrf=True,
        )
        require_action(request, resource_type="user", resource_code=payload.target_user_id, action="manage")
        try:
            return container(request).identity_discovery_service.bind_candidate(
                actor_id=principal.user_id,
                candidate_id=candidate_id,
                target_user_id=payload.target_user_id,
                expected_candidate_revision=payload.expected_candidate_revision,
                expected_user_revision=payload.expected_user_revision,
                initial_role_ids=payload.initial_role_ids,
                bind_without_access_confirmed=payload.bind_without_access_confirmed,
                replace_current_confirmed=payload.replace_current_confirmed,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    return router
