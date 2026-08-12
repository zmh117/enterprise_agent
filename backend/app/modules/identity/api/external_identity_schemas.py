from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserSummaryResponse(StrictResponse):
    id: str
    display_name: str


class DingTalkEnterpriseResponse(StrictResponse):
    name: str
    corp_id: str


class DingTalkIdentityResponseBase(StrictResponse):
    provider: Literal["dingtalk"]
    nickname: str
    enterprise: DingTalkEnterpriseResponse | None
    last_used_at: str | None = None
    staff_id: str


class SelfDingTalkIdentityResponse(DingTalkIdentityResponseBase):
    status: Literal["enabled", "disabled"]


class TeamResponse(StrictResponse):
    id: str
    name: str


class ExternalCredentialStatusResponse(StrictResponse):
    configured: bool
    status: Literal["ACTIVE", "REAUTH_REQUIRED", "DISABLED", "UNBOUND"]
    revision: int = Field(ge=1)
    verified_at: str
    token_refreshed_at: str | None = None
    last_used_at: str | None = None
    reauth_required_at: str | None = None
    disabled_at: str | None = None
    unbound_at: str | None = None


class OnesIdentityResponseBase(StrictResponse):
    provider: Literal["ones"]
    user_name: str
    default_team: TeamResponse | None
    verified_at: str | None = None
    user_id: str
    teams: list[TeamResponse]
    credential: ExternalCredentialStatusResponse | None


class SelfOnesIdentityResponse(OnesIdentityResponseBase):
    status: Literal["enabled", "disabled"]


class SelfIdentityOverviewResponse(StrictResponse):
    user: UserSummaryResponse
    dingtalk: list[SelfDingTalkIdentityResponse]
    ones: SelfOnesIdentityResponse | None


class SelfOnesStatusResponse(StrictResponse):
    user: UserSummaryResponse
    ones: SelfOnesIdentityResponse | None


class DingTalkApplicationObservationResponse(StrictResponse):
    application_name: str
    first_observed_at: str | None = None
    last_observed_at: str | None = None


class AdminDingTalkIdentityResponse(DingTalkIdentityResponseBase):
    status: Literal["enabled", "disabled", "unbound"]
    identity_id: str
    revision: int = Field(ge=1)
    binding_confirmed_at: str | None = None
    observations: list[DingTalkApplicationObservationResponse]


class AdminOnesIdentityResponse(OnesIdentityResponseBase):
    status: Literal["enabled", "disabled", "unbound"]
    identity_id: str
    revision: int = Field(ge=1)


AdminIdentityResponse = Annotated[
    AdminDingTalkIdentityResponse | AdminOnesIdentityResponse,
    Field(discriminator="provider"),
]


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


class OnesIdentityChallengeResponse(StrictResponse):
    id: str
    provider: Literal["ones"]
    external_user_id: str
    display_name: str
    teams: list[TeamResponse]
    team_ids: list[str]
    verified_at: str
    expires_at: str
    status: Literal["PENDING", "CONSUMED", "EXPIRED"]
    created_at: str


class BeginOnesIdentityResponse(StrictResponse):
    challenge: OnesIdentityChallengeResponse
