from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.api.dependencies import (
    container,
    handle_exception,
    require_action,
)


ConversationScope = Literal["all", "direct", "group", "both"]


class BindCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_user_id: str = Field(min_length=1, max_length=200)
    expected_candidate_revision: int = Field(ge=1)
    expected_user_revision: int = Field(ge=1)


def build_identity_discovery_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/admin/dingtalk-identity-candidates",
        tags=["dingtalk-identity-discovery"],
    )

    @router.get("")
    def list_candidates(
        request: Request,
        search: str = Query(default="", max_length=200),
        conversation_scope: ConversationScope = "all",
        limit: int = Query(default=25, ge=1, le=100),
        cursor: str = Query(default="", max_length=1000),
    ) -> dict[str, object]:
        require_action(
            request,
            resource_type="identity",
            resource_code="*",
            action="manage",
        )
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
        require_action(
            request,
            resource_type="identity",
            resource_code="*",
            action="manage",
        )
        return {
            "count": container(request).identity_discovery_service.count_candidates()
        }

    @router.get("/{candidate_id}")
    def get_candidate(request: Request, candidate_id: str) -> dict[str, Any]:
        require_action(
            request,
            resource_type="identity",
            resource_code="*",
            action="manage",
        )
        try:
            candidate = container(request).identity_discovery_service.get_candidate(
                candidate_id
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"candidate": candidate}

    @router.post("/{candidate_id}/bind")
    def bind_candidate(
        request: Request,
        candidate_id: str,
        payload: BindCandidateRequest,
    ) -> dict[str, object]:
        principal = require_action(
            request,
            resource_type="identity",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        try:
            return container(request).identity_discovery_service.bind_candidate(
                actor_id=principal.user_id,
                candidate_id=candidate_id,
                target_user_id=payload.target_user_id,
                expected_candidate_revision=payload.expected_candidate_revision,
                expected_user_revision=payload.expected_user_revision,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    return router
