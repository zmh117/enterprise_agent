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


class SelfDingTalkIdentityResponse(StrictResponse):
    provider: Literal["dingtalk"]
    nickname: str
    status: Literal["enabled", "disabled"]
    enterprise: DingTalkEnterpriseResponse | None
    last_used_at: str | None = None
    staff_id: str


class TeamResponse(StrictResponse):
    id: str
    name: str


class SelfOnesIdentityResponse(StrictResponse):
    provider: Literal["ones"]
    user_name: str
    availability: Literal[
        "AVAILABLE",
        "REVERIFY_REQUIRED",
        "ADMIN_DISABLED",
        "UNBOUND",
    ]
    default_team: TeamResponse | None
    verified_at: str | None = None
    last_success_at: str | None = None
    user_id: str
    teams: list[TeamResponse]


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


class AdminDingTalkIdentityResponse(SelfDingTalkIdentityResponse):
    status: Literal["enabled", "disabled", "unbound"]
    identity_id: str
    revision: int = Field(ge=1)
    binding_confirmed_at: str | None = None
    observations: list[DingTalkApplicationObservationResponse]


class AdminOnesIdentityResponse(SelfOnesIdentityResponse):
    identity_id: str
    identity_status: Literal["enabled", "disabled", "unbound"]
    identity_revision: int = Field(ge=1)


AdminIdentityResponse = Annotated[
    AdminDingTalkIdentityResponse | AdminOnesIdentityResponse,
    Field(discriminator="provider"),
]


class AdminIdentityOverviewResponse(StrictResponse):
    user_id: str
    current: list[AdminIdentityResponse]
    history: list[AdminIdentityResponse]


class CredentialTechnicalResponse(StrictResponse):
    status: Literal["ACTIVE", "INVALID", "DISABLED"]
    revision: int = Field(ge=1)
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_error_code: str
    last_error_at: str | None = None


class ConnectionTechnicalResponse(StrictResponse):
    name: str
    revision: int = Field(ge=1)
    status: str


class AdminOnesTechnicalResponse(AdminOnesIdentityResponse):
    credential: CredentialTechnicalResponse | None
    connection: ConnectionTechnicalResponse | None


class AdminOnesStatusResponse(StrictResponse):
    user_id: str
    ones: AdminOnesTechnicalResponse | None


class IdentityMutationSummaryResponse(StrictResponse):
    id: str
    status: Literal["enabled", "disabled", "unbound"]
    revision: int = Field(ge=1)


class IdentityMutationResponse(StrictResponse):
    identity: IdentityMutationSummaryResponse
