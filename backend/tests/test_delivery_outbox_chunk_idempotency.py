from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.agent.domain.runtime import AgentRunResult
from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.delivery.infrastructure.adapters import DeliveryAdapter
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.shared.exceptions import RetryableExecutionError
from backend.tests.helpers import container


class _LongResultClient:
    def run(self, request: object) -> AgentRunResult:
        del request
        return AgentRunResult(final_answer="x" * 450)


class _FailSecondChunkOnceAdapter(DeliveryAdapter):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failed = False

    def send(
        self,
        *,
        connector: object,
        route: ReplyRoute,
        title: str,
        text: str,
    ) -> None:
        del connector, route, text
        self.calls.append(title)
        if title.endswith("part 2/3") and not self.failed:
            self.failed = True
            raise RetryableExecutionError(
                "synthetic chunk interruption",
                safe_message="投递分片暂时失败",
                error_code="delivery_chunk_interrupted",
            )


def test_chunk_retry_skips_recorded_success_and_duplicate_event_is_idempotent() -> None:
    runtime = container()
    try:
        runtime.result_delivery_service.chunker.max_chars = 200
        runtime.agent_executor.claude_client = _LongResultClient()  # type: ignore[assignment]
        adapter = _FailSecondChunkOnceAdapter()
        runtime.result_delivery_service.adapters["test_chunked"] = adapter
        job = runtime.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="delivery-chunk-idempotency",
                requester_id="local-user",
                external_conversation_id="delivery-chunk-idempotency",
                user_message="diagnose",
                source_channel="debug_api",
                source_connector_id="connector-debug-api",
                project_code="default",
                correlation_id="delivery-chunk-correlation",
                reply_route={"type": "test_chunked", "target": {}},
            )
        )
        runtime.agent_executor.execute(
            job.id,
            worker_id="chunk-test-agent",
            correlation_id="delivery-chunk-correlation",
        )
        event = runtime.agent_repository.get_delivery_event_for_job(job.id)
        assert event is not None

        first = runtime.delivery_dispatcher.dispatch_pending(limit=1)
        waiting = runtime.agent_repository.get_delivery_event(event.id)
        assert first.retrying == 1
        assert waiting.status.value == "RETRY_WAIT"
        chunks_after_first = runtime.agent_repository.list_delivery_chunks(
            job.id
        )
        assert [row["status"] for row in chunks_after_first] == [
            "SUCCEEDED",
            "FAILED",
        ]

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
        completed = runtime.agent_repository.get_delivery_event(event.id)
        assert second.succeeded == 1
        assert completed.status.value == "SUCCEEDED"
        assert adapter.calls.count("Agent 诊断报告 part 1/3") == 1
        assert adapter.calls.count("Agent 诊断报告 part 2/3") == 2
        assert adapter.calls.count("Agent 诊断报告 part 3/3") == 1
        assert runtime.database.execute_one(
            """
            select count(*) as count
              from delivery_chunk
             where delivery_outbox_id = ? and status = 'SUCCEEDED'
            """,
            (event.id,),
        ) == {"count": 3}

        artifact = runtime.agent_repository.get_artifact(
            event.result_artifact_id
        )
        duplicate_id = runtime.result_delivery_service.enqueue_job_result(
            job_id=job.id,
            artifact_id=str(artifact["id"]),
            correlation_id="delivery-chunk-correlation",
        )
        assert duplicate_id == event.id
        assert runtime.database.execute_one(
            """
            select count(*) as count
              from delivery_outbox
             where job_id = ?
            """,
            (job.id,),
        ) == {"count": 1}
        no_work = runtime.delivery_dispatcher.dispatch_pending(limit=1)
        assert no_work.succeeded == 0
        assert len(adapter.calls) == 4
    finally:
        runtime.database.close()
