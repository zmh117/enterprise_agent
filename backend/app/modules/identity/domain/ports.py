from __future__ import annotations

from typing import Any, Protocol


class DingTalkIdentityObservationPort(Protocol):
    def record_dingtalk_message_facts(
        self,
        *,
        identity_id: str,
        connector_id: str,
        source_ingress_event_id: str,
        nickname: str,
        occurred_at: str,
        received_at: str,
    ) -> None: ...

    def list_dingtalk_application_observations(
        self,
        identity_id: str,
    ) -> list[dict[str, Any]]: ...


class ExternalCredentialUsagePort(Protocol):
    def record_usage_attempt(self, *, credential_id: str) -> dict[str, Any]: ...

    def record_usage_success(self, *, credential_id: str) -> dict[str, Any]: ...

    def record_usage_failure(
        self,
        *,
        credential_id: str,
        error_code: str,
        invalidate: bool = False,
    ) -> dict[str, Any]: ...
