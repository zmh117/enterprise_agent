from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import sqlite3
import threading
import time

from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.delivery.application.delivery_dispatch_service import (
    DeliveryDispatchResult,
    DeliveryOutboxDispatcher,
)
from app.modules.delivery.infrastructure.adapters import DeliveryAdapter
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.modules.job.domain.job_status import JobStatus
from app.shared.exceptions import (
    NonRetryableExecutionError,
    RetryableExecutionError,
)
from backend.tests.helpers import container


class _CaptureAdapter(DeliveryAdapter):
    def __init__(self) -> None:
        self.sent: list[str] = []
        self._lock = threading.Lock()

    def send(
        self,
        *,
        connector: object,
        route: ReplyRoute,
        title: str,
        text: str,
    ) -> None:
        del connector, route, title
        with self._lock:
            self.sent.append(text)


class _FailingAdapter(DeliveryAdapter):
    def __init__(self, *, retryable: bool) -> None:
        self.retryable = retryable
        self.calls = 0

    def send(
        self,
        *,
        connector: object,
        route: ReplyRoute,
        title: str,
        text: str,
    ) -> None:
        del connector, route, title, text
        self.calls += 1
        if self.retryable:
            raise RetryableExecutionError(
                "synthetic transient delivery failure",
                safe_message="投递服务暂时不可用",
                error_code="delivery_transient",
            )
        raise NonRetryableExecutionError(
            "synthetic terminal delivery failure",
            safe_message="投递配置无效",
            error_code="delivery_config_invalid",
        )


def _complete_job(
    runtime: object,
    key: str,
    *,
    route_type: str,
) -> object:
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key=key,
            requester_id="local-user",
            external_conversation_id=f"conversation-{key}",
            user_message="diagnose",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            project_code="default",
            correlation_id=f"correlation-{key}",
            reply_route={"type": route_type, "target": {}},
        )
    )
    runtime.agent_executor.execute(
        job.id,
        worker_id="delivery-dispatch-test-agent",
        correlation_id=f"correlation-{key}",
    )
    return job


def test_none_route_is_persisted_then_atomically_skipped() -> None:
    runtime = container()
    try:
        job = _complete_job(
            runtime,
            "delivery-none-route",
            route_type="none",
        )
        pending = runtime.agent_repository.get_delivery_event_for_job(job.id)
        assert pending is not None
        assert pending.status.value == "PENDING"

        result = runtime.delivery_dispatcher.dispatch_pending(limit=1)

        skipped = runtime.agent_repository.get_delivery_event(pending.id)
        attempts = runtime.agent_repository.list_delivery_attempts(job.id)
        assert result.skipped == 1
        assert skipped.status.value == "SKIPPED"
        assert attempts[0]["status"] == "SKIPPED"
        assert runtime.agent_repository.get_job(job.id).status == JobStatus.SUCCEEDED
    finally:
        runtime.database.close()


def test_retryable_delivery_exhausts_finite_attempts_into_dead() -> None:
    runtime = container()
    try:
        adapter = _FailingAdapter(retryable=True)
        runtime.result_delivery_service.adapters["test_retry"] = adapter
        job = _complete_job(
            runtime,
            "delivery-finite-dead",
            route_type="test_retry",
        )
        event = runtime.agent_repository.get_delivery_event_for_job(job.id)
        assert event is not None
        runtime.database.execute(
            "update delivery_outbox set max_attempts = 2 where id = ?",
            (event.id,),
        )

        first = runtime.delivery_dispatcher.dispatch_pending(limit=1)
        waiting = runtime.agent_repository.get_delivery_event(event.id)
        assert first.retrying == 1
        assert waiting.status.value == "RETRY_WAIT"
        assert waiting.attempt_count == 1
        assert runtime.agent_repository.get_job(job.id).status == JobStatus.SUCCEEDED

        runtime.database.execute(
            """
            update delivery_outbox
               set next_attempt_at = ?
             where id = ?
            """,
            (
                (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                event.id,
            ),
        )
        second = runtime.delivery_dispatcher.dispatch_pending(limit=1)
        dead = runtime.agent_repository.get_delivery_event(event.id)
        assert second.dead == 1
        assert dead.status.value == "DEAD"
        assert dead.attempt_count == 2
        assert adapter.calls == 2
        assert runtime.agent_repository.get_job(job.id).status == JobStatus.SUCCEEDED
    finally:
        runtime.database.close()


def test_non_retryable_delivery_failure_is_terminal_failed() -> None:
    runtime = container()
    try:
        adapter = _FailingAdapter(retryable=False)
        runtime.result_delivery_service.adapters["test_terminal"] = adapter
        job = _complete_job(
            runtime,
            "delivery-terminal-failed",
            route_type="test_terminal",
        )
        event = runtime.agent_repository.get_delivery_event_for_job(job.id)
        assert event is not None

        result = runtime.delivery_dispatcher.dispatch_pending(limit=1)

        failed = runtime.agent_repository.get_delivery_event(event.id)
        assert result.failed == 1
        assert failed.status.value == "FAILED"
        assert failed.last_error_code == "delivery_config_invalid"
        assert runtime.agent_repository.get_job(job.id).status == JobStatus.SUCCEEDED
    finally:
        runtime.database.close()


def test_two_dispatchers_do_not_own_or_send_the_same_delivery() -> None:
    runtime = container()
    try:
        adapter = _CaptureAdapter()
        runtime.result_delivery_service.adapters["test_capture"] = adapter
        jobs = [
            _complete_job(
                runtime,
                f"delivery-concurrent-{index}",
                route_type="test_capture",
            )
            for index in range(20)
        ]
        dispatchers = [
            DeliveryOutboxDispatcher(
                repository=runtime.agent_repository,
                delivery_service=runtime.result_delivery_service,
                audit_service=runtime.audit_service,
                settings=runtime.settings.delivery,
                worker_id=f"delivery-dispatcher-{index}",
            )
            for index in range(2)
        ]

        def dispatch_with_sqlite_lock_retry(
            dispatcher: DeliveryOutboxDispatcher,
        ) -> DeliveryDispatchResult:
            for _ in range(50):
                try:
                    return dispatcher.dispatch_pending(limit=20)
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower():
                        raise
                    time.sleep(0.01)
            raise AssertionError("SQLite Delivery Dispatcher lock did not clear")

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    dispatch_with_sqlite_lock_retry,
                    dispatchers,
                )
            )

        runtime.database.execute(
            """
            update delivery_outbox
               set claim_expires_at = ?
             where status = 'RUNNING'
            """,
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )
        results.append(dispatchers[0].dispatch_pending(limit=20))

        assert all(result.failed == 0 and result.dead == 0 for result in results)
        assert len(adapter.sent) == 20
        assert runtime.database.execute_one(
            """
            select count(*) as count
              from delivery_outbox
             where status = 'SUCCEEDED'
            """
        ) == {"count": 20}
        assert runtime.database.execute_one(
            """
            select count(*) as count
              from delivery_attempt
             where delivery_outbox_id is not null
               and status = 'SUCCEEDED'
            """
        ) == {"count": 20}
        assert all(
            runtime.agent_repository.get_job(job.id).status == JobStatus.SUCCEEDED for job in jobs
        )
    finally:
        runtime.database.close()
