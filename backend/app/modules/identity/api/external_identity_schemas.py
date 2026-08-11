from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserSummaryResponse(StrictResponse):
    id: str
    display_name: str


class DingTalkEnterpriseResponse(StrictResponse):
    name: str
    corp_id: str


class SelfDingTalkIdentityResponse(StrictResponse):
    provider: Literal["dingtalk"]
    nickname: str
    status: Literal["enabled", "disabled"]
    enterprise: DingTalkEnterpriseResponse | None
    last_used_at: str | None = None
    staff_id: str


class SelfIdentityOverviewResponse(StrictResponse):
    user: UserSummaryResponse
    dingtalk: list[SelfDingTalkIdentityResponse]


class DingTalkApplicationObservationResponse(StrictResponse):
    application_name: str
    first_observed_at: str | None = None
    last_observed_at: str | None = None


class AdminDingTalkIdentityResponse(SelfDingTalkIdentityResponse):
    status: Literal["enabled", "disabled", "unbound"]
    identity_id: str
    revision: int = Field(ge=1)
    binding_confirmed_at: str | None = None
    observations: list[DingTalkApplicationObservationResponse]


AdminIdentityResponse = AdminDingTalkIdentityResponse


class AdminIdentityOverviewResponse(StrictResponse):
    user_id: str
    current: list[AdminIdentityResponse]
    history: list[AdminIdentityResponse]


class IdentityMutationSummaryResponse(StrictResponse):
    id: str
    status: Literal["enabled", "disabled", "unbound"]
    revision: int = Field(ge=1)


class IdentityMutationResponse(StrictResponse):
    identity: IdentityMutationSummaryResponse
