from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from app.bootstrap import Container, build_api_container
from app.modules.dingding.infrastructure.dingtalk_stream_client import (
    DingTalkStreamClient,
    DingTalkStreamSdkClient,
    StreamCallback,
)
from app.shared.config import Settings, load_settings
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied
from app.shared.logging import configure_logging, new_correlation_id

logger = logging.getLogger(__name__)

_RUNNING_CONNECTORS: set[str] = set()


StreamClientFactory = Callable[[str, str, StreamCallback], DingTalkStreamClient]
SleepFn = Callable[[float], None]


class DingTalkStreamIngressWorker:
    def __init__(
        self,
        settings: Settings,
        *,
        container: Container | None = None,
        stream_client_factory: StreamClientFactory | None = None,
        sleep: SleepFn = time.sleep,
    ) -> None:
        self.settings = settings
        self.container = container or build_api_container(
            settings,
            migrate=settings.app_startup_migrate,
            seed=settings.seed_local_config,
        )
        self.stream_client_factory = stream_client_factory or self._sdk_client_factory
        self.sleep = sleep
        self.worker_id = f"{settings.dingtalk.stream_worker_id}-{uuid.uuid4().hex[:8]}"

    def handle_payload(self, payload: dict[str, Any]) -> Any:
        return self.container.dingtalk_stream_message_service.handle_callback(
            payload=payload,
            correlation_id=new_correlation_id(),
            connector_id=self.settings.dingtalk.stream_connector_id,
        )

    def run_once(self) -> None:
        if not self.settings.dingtalk.stream_enabled:
            self.container.audit_service.record(
                "dingtalk.stream.disabled",
                status="SKIPPED",
                summary="DingTalk Stream ingress is disabled",
                actor_id=self.worker_id,
                payload={"connector_id": self.settings.dingtalk.stream_connector_id},
            )
            logger.info("DingTalk Stream ingress is disabled")
            return

        connector_id = self.settings.dingtalk.stream_connector_id
        if connector_id in _RUNNING_CONNECTORS:
            raise NonRetryableExecutionError(
                f"DingTalk Stream connector already running: {connector_id}",
                safe_message="DingTalk Stream connector is already running",
            )
        _RUNNING_CONNECTORS.add(connector_id)
        try:
            client_id, client_secret = self._credentials(connector_id)
            self.container.audit_service.record(
                "dingtalk.stream.starting",
                status="STARTED",
                summary="DingTalk Stream connector starting",
                actor_id=self.worker_id,
                payload={"connector_id": connector_id},
            )
            client = self.stream_client_factory(client_id, client_secret, self.handle_payload)
            self.container.audit_service.record(
                "dingtalk.stream.connected",
                status="SUCCEEDED",
                summary="DingTalk Stream connector connected",
                actor_id=self.worker_id,
                payload={"connector_id": connector_id},
            )
            client.start_forever()
        finally:
            _RUNNING_CONNECTORS.discard(connector_id)

    def run_forever(self, *, max_attempts: int | None = None) -> None:
        if not self.settings.dingtalk.stream_enabled:
            self.run_once()
            return
        delay = max(1, self.settings.dingtalk.stream_reconnect_initial_seconds)
        max_delay = max(delay, self.settings.dingtalk.stream_reconnect_max_seconds)
        attempts = 0
        while True:
            attempts += 1
            try:
                self.run_once()
                self.container.audit_service.record(
                    "dingtalk.stream.disconnected",
                    status="FAILED",
                    summary="DingTalk Stream connector stopped unexpectedly",
                    actor_id=self.worker_id,
                    payload={
                        "connector_id": self.settings.dingtalk.stream_connector_id,
                        "attempt": attempts,
                    },
                )
            except KeyboardInterrupt:
                raise
            except NonRetryableExecutionError:
                self.container.audit_service.record(
                    "dingtalk.stream.permanent_failure",
                    status="FAILED",
                    summary="DingTalk Stream connector cannot start",
                    actor_id=self.worker_id,
                    payload={
                        "connector_id": self.settings.dingtalk.stream_connector_id,
                        "attempt": attempts,
                    },
                )
                raise
            except Exception as exc:
                safe_message = getattr(exc, "safe_message", str(exc))
                self.container.audit_service.record(
                    "dingtalk.stream.disconnected",
                    status="FAILED",
                    summary=safe_message,
                    actor_id=self.worker_id,
                    payload={
                        "connector_id": self.settings.dingtalk.stream_connector_id,
                        "attempt": attempts,
                    },
                )
                logger.warning("DingTalk Stream connector disconnected: %s", safe_message)

            if max_attempts is not None and attempts >= max_attempts:
                return
            self.container.audit_service.record(
                "dingtalk.stream.reconnect_scheduled",
                status="STARTED",
                summary="DingTalk Stream connector reconnect scheduled",
                actor_id=self.worker_id,
                payload={
                    "connector_id": self.settings.dingtalk.stream_connector_id,
                    "delay_seconds": delay,
                    "attempt": attempts + 1,
                },
            )
            self.sleep(float(delay))
            delay = min(max_delay, delay * 2)

    def _credentials(self, connector_id: str) -> tuple[str, str]:
        try:
            connector = self.container.connector_registry.require_dingtalk_stream_ingress(
                connector_id
            )
        except PermissionDenied as exc:
            raise NonRetryableExecutionError(str(exc), safe_message=exc.safe_message) from exc
        client_id = (
            self.container.connector_registry.resolve_metadata_reference(connector, "client_id_ref")
            or self.container.connector_registry.metadata_value(connector, "client_id")
            or self.settings.dingtalk.stream_client_id
            or self.settings.dingtalk.client_id
        )
        client_secret = (
            self.container.connector_registry.resolve_secret(connector)
            or self.settings.dingtalk.stream_client_secret
            or self.settings.dingtalk.client_secret
        )
        if not client_id or not client_secret:
            self.container.audit_service.record(
                "dingtalk.stream.config_failed",
                status="FAILED",
                summary="DingTalk Stream credentials are missing",
                actor_id=self.worker_id,
                payload={"connector_id": connector_id},
            )
            raise NonRetryableExecutionError(
                "DingTalk Stream credentials are missing",
                safe_message="DingTalk Stream credentials are missing",
            )
        return client_id, client_secret

    def _sdk_client_factory(
        self, client_id: str, client_secret: str, callback: StreamCallback
    ) -> DingTalkStreamClient:
        return DingTalkStreamSdkClient(
            client_id=client_id,
            client_secret=client_secret,
            callback=callback,
        )


def main() -> None:
    configure_logging()
    DingTalkStreamIngressWorker(load_settings()).run_forever()


if __name__ == "__main__":
    main()
