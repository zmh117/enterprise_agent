from __future__ import annotations

import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.webhook.infrastructure import WebhookEventRepository
from app.shared.exceptions import PermissionDenied


class WebhookAuthenticator:
    def __init__(
        self,
        *,
        connector_registry: ConnectorRegistry,
        event_repository: WebhookEventRepository,
    ) -> None:
        self.connector_registry = connector_registry
        self.event_repository = event_repository

    def authenticate(
        self,
        *,
        trigger_id: str,
        config: dict[str, Any],
        headers: Mapping[str, str],
        raw_body: bytes,
    ) -> str:
        auth = config.get("authentication") or {}
        secret = self.connector_registry.resolve_reference(auth.get("secret_ref"))
        if not secret:
            raise PermissionDenied(
                "Webhook secret reference could not be resolved",
                safe_message="Webhook authentication failed",
                error_code="webhook_auth_failed",
            )
        auth_type = str(auth.get("type") or "")
        lowered = {str(key).lower(): str(value) for key, value in headers.items()}
        if auth_type == "bearer_v1":
            provided = lowered.get("authorization", "")
            prefix = "Bearer "
            token = provided[len(prefix) :] if provided.startswith(prefix) else ""
            if not token or not hmac.compare_digest(secret.encode(), token.encode()):
                raise PermissionDenied(
                    "Webhook bearer credential is invalid",
                    safe_message="Webhook authentication failed",
                    error_code="webhook_auth_failed",
                )
            return "bearer_v1"
        if auth_type == "hmac_sha256_v1":
            return self._hmac(
                trigger_id=trigger_id,
                auth=auth,
                secret=secret,
                headers=lowered,
                raw_body=raw_body,
            )
        raise PermissionDenied(
            "Webhook authentication scheme is unsupported",
            safe_message="Webhook authentication failed",
            error_code="webhook_auth_failed",
        )

    def _hmac(
        self,
        *,
        trigger_id: str,
        auth: dict[str, Any],
        secret: str,
        headers: Mapping[str, str],
        raw_body: bytes,
    ) -> str:
        timestamp_header = str(auth.get("timestamp_header") or "x-webhook-timestamp").lower()
        nonce_header = str(auth.get("nonce_header") or "x-webhook-nonce").lower()
        signature_header = str(auth.get("signature_header") or "x-webhook-signature").lower()
        timestamp_text = headers.get(timestamp_header, "")
        nonce = headers.get(nonce_header, "")
        provided = headers.get(signature_header, "")
        if not timestamp_text or not nonce or not provided or len(nonce) > 256:
            raise PermissionDenied(
                "Webhook HMAC headers are missing",
                safe_message="Webhook authentication failed",
                error_code="webhook_auth_required",
            )
        try:
            timestamp = int(timestamp_text)
        except ValueError as exc:
            raise PermissionDenied(
                "Webhook HMAC timestamp is invalid",
                safe_message="Webhook authentication failed",
                error_code="webhook_signature_expired",
            ) from exc
        window = int(auth.get("window_seconds") or 300)
        if abs(int(time.time()) - timestamp) > window:
            raise PermissionDenied(
                "Webhook HMAC timestamp is outside the allowed window",
                safe_message="Webhook signature timestamp expired",
                error_code="webhook_signature_expired",
            )
        canonical = timestamp_text.encode() + b"." + raw_body
        expected = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
        normalized_provided = provided.removeprefix("sha256=")
        if not hmac.compare_digest(expected.encode(), normalized_provided.encode()):
            raise PermissionDenied(
                "Webhook HMAC signature is invalid",
                safe_message="Webhook authentication failed",
                error_code="webhook_auth_failed",
            )
        nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
        expires_at = (datetime.now(UTC) + timedelta(seconds=window)).isoformat()
        if not self.event_repository.register_nonce(
            trigger_id=trigger_id, nonce_hash=nonce_hash, expires_at=expires_at
        ):
            raise PermissionDenied(
                "Webhook HMAC nonce was already used",
                safe_message="Webhook replay detected",
                error_code="webhook_replay_detected",
            )
        return "hmac_sha256_v1"
