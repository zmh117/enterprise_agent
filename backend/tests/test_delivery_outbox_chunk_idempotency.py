from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.bootstrap import Container
from app.modules.agent.domain.runtime import AgentRunResult
from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.delivery.application.report_chunker import (
    FIXED_CHUNKING,
    PARAGRAPH_CHUNKING,
    ReportChunker,
)
from app.modules.delivery.domain import DeliveryEvent
from app.modules.delivery.infrastructure.adapters import DeliveryAdapter
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError
from backend.tests.support.runtime import container


@pytest.mark.parametrize("max_chars", [200, 3500, 20_000])
def test_complete_detail_list_chunking_preserves_all_records_and_full_titles(
    max_chars: int,
) -> None:
    # Synthetic final text tests transport preservation, not model compliance.
    identifiers = [f"SYNTHETIC-{index:04d}" for index in range(1, 21)]
    titles = [f"合成标题 {index}…保留原文 " + "完整长标题字段；" * 60 for index in range(1, 21)]
    report = "完整明细：20 条\n\n" + "\n\n".join(
        f"{index}. {identifier}\n   标题：{title}"
        for index, (identifier, title) in enumerate(zip(identifiers, titles, strict=True), start=1)
    )
    chunker = ReportChunker(max_chars=max_chars)

    chunks = chunker.chunks(report)
    assert all(len(chunk) <= max_chars for chunk in chunks)
    assert "".join(chunks) == report
    titled = chunker.titled_chunks(title="合成验收清单", text=report)
    assert all(len(text) <= max_chars for _, text in titled)
    if len(titled) == 1:
        assert titled == [("合成验收清单", report)]
        reconstructed = titled[0][1]
    else:
        for index, (title, text) in enumerate(titled, start=1):
            assert title == f"合成验收清单 part {index}/{len(titled)}"
            assert text.startswith(f"part {index}/{len(titled)}\n\n")
        reconstructed = "".join(text.split("\n\n", 1)[1] for _, text in titled)
    assert reconstructed == report
    for identifier, title in zip(identifiers, titles, strict=True):
        assert reconstructed.count(identifier) == 1
        assert title in reconstructed


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_chunker_prefers_complete_record_paragraphs_then_lines(newline: str) -> None:
    records = [
        f"### 🔎 SYN-{index}{newline}**合成标题**："
        + "完整字段" * 10
        + f"{newline}⚠️ 原始状态：待确认 [详情](https://example.test/{index}){newline * 2}"
        for index in range(5)
    ]
    chunker = ReportChunker(200)
    paragraphs = chunker.titled_chunks(title="合成清单", text="".join(records))
    assert [text.split("\n\n", 1)[1] for _, text in paragraphs] == records
    lines = ["保留的合成长行 " * 10 + newline for _ in range(5)]
    assert chunker.chunks("".join(lines)) == ["".join(lines[:2]), "".join(lines[2:4]), lines[4]]


@pytest.mark.parametrize("report", ["", " \n\r\n ", "字" * 200, "字" * 4000, "🔎字段\n\n" * 500])
def test_chunker_bounds_prefix_and_preserves_exact_text(report: str) -> None:
    chunks = ReportChunker(200).titled_chunks(title="合成报告", text=report)
    assert all(len(text) <= 200 for _, text in chunks)
    assert (
        "".join(text.split("\n\n", 1)[1] if len(chunks) > 1 else text for _, text in chunks)
        == report
    )


@pytest.mark.parametrize(
    "policy",
    [
        None,
        {},
        {"version": "unknown", "max_chars": 200},
        {"version": PARAGRAPH_CHUNKING, "max_chars": True},
        {"version": PARAGRAPH_CHUNKING, "max_chars": 199},
    ],
)
def test_chunker_rejects_unknown_or_invalid_persisted_plan(policy: object) -> None:
    with pytest.raises(NonRetryableExecutionError) as caught:
        ReportChunker.from_policy(policy)
    assert caught.value.error_code == "delivery_chunk_plan_invalid"


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


@pytest.fixture
def chunk_delivery(
    request: pytest.FixtureRequest,
) -> Iterator[tuple[Container, DeliveryEvent, _FailSecondChunkOnceAdapter]]:
    runtime = container()
    try:
        runtime.result_delivery_service.chunker = ReportChunker(
            200, version=getattr(request, "param", PARAGRAPH_CHUNKING)
        )
        runtime.agent_executor.runtime_client = _LongResultClient()  # type: ignore[assignment]
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
        event = runtime.delivery_repository.get_delivery_event_for_job(job.id)
        assert event is not None
        yield runtime, event, adapter
    finally:
        runtime.database.close()


def _retry_now(runtime: Container, event: DeliveryEvent) -> None:
    runtime.database.execute(
        "update delivery_outbox set next_attempt_at = ? where id = ?",
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), event.id),
    )


@pytest.mark.parametrize("chunk_delivery", [PARAGRAPH_CHUNKING, FIXED_CHUNKING], indirect=True)
def test_chunk_retry_skips_recorded_success_and_duplicate_event_is_idempotent(
    chunk_delivery: tuple[Container, DeliveryEvent, _FailSecondChunkOnceAdapter],
) -> None:
    runtime, event, adapter = chunk_delivery
    version = runtime.result_delivery_service.chunker.version

    first = runtime.delivery_dispatcher.dispatch_pending(limit=1)
    waiting = runtime.delivery_repository.get_delivery_event(event.id)
    assert first.retrying == 1
    assert waiting.status.value == "RETRY_WAIT"
    assert waiting.delivery_binding["text_chunking"] == {"version": version, "max_chars": 200}
    chunks_after_first = runtime.delivery_repository.list_delivery_chunks(event.job_id)
    assert [row["status"] for row in chunks_after_first] == ["SUCCEEDED", "FAILED"]

    if version == FIXED_CHUNKING:
        # Simulate an interrupted pre-upgrade event: old fixed chunks, no saved policy.
        binding = dict(waiting.delivery_binding)
        binding.pop("text_chunking")
        runtime.database.execute(
            "update delivery_outbox set delivery_binding_json = ? where id = ?",
            (json.dumps(binding), event.id),
        )
    # A new process/default must not change the payload or re-send the successful first chunk.
    runtime.result_delivery_service.chunker = ReportChunker(800)
    _retry_now(runtime, event)
    second = runtime.delivery_dispatcher.dispatch_pending(limit=1)
    completed = runtime.delivery_repository.get_delivery_event(event.id)
    assert second.succeeded == 1
    assert completed.status.value == "SUCCEEDED"
    assert completed.delivery_binding["text_chunking"] == {"version": version, "max_chars": 200}
    assert adapter.calls.count("Agent 诊断报告 part 1/3") == 1
    assert adapter.calls.count("Agent 诊断报告 part 2/3") == 2
    assert adapter.calls.count("Agent 诊断报告 part 3/3") == 1
    assert runtime.database.execute_one(
        """select count(*) as count from delivery_chunk
           where delivery_outbox_id = ? and status = 'SUCCEEDED'""",
        (event.id,),
    ) == {"count": 3}

    artifact = runtime.agent_repository.get_artifact(event.result_artifact_id)
    duplicate_id = runtime.result_delivery_service.enqueue_job_result(
        job_id=event.job_id,
        artifact_id=str(artifact["id"]),
        correlation_id="delivery-chunk-correlation",
    )
    assert duplicate_id == event.id
    assert runtime.database.execute_one(
        "select count(*) as count from delivery_outbox where job_id = ?",
        (event.job_id,),
    ) == {"count": 1}
    no_work = runtime.delivery_dispatcher.dispatch_pending(limit=1)
    assert no_work.succeeded == 0
    assert len(adapter.calls) == 4


@pytest.mark.parametrize(
    "invalid", ["unknown_plan", "missing_legacy_length", "bad_legacy_summary", "payload_drift"]
)
def test_unsafe_chunk_retry_fails_before_another_send(
    chunk_delivery: tuple[Container, DeliveryEvent, _FailSecondChunkOnceAdapter],
    invalid: str,
) -> None:
    runtime, event, adapter = chunk_delivery
    assert runtime.delivery_dispatcher.dispatch_pending(limit=1).retrying == 1
    waiting = runtime.delivery_repository.get_delivery_event(event.id)
    binding = dict(waiting.delivery_binding)
    if invalid == "unknown_plan":
        binding["text_chunking"]["version"] = "unknown"
    elif invalid in {"missing_legacy_length", "bad_legacy_summary"}:
        binding.pop("text_chunking")
        runtime.database.execute(
            "update delivery_chunk set payload_summary = ? where delivery_outbox_id = ?",
            ("{}" if invalid == "missing_legacy_length" else "[]", event.id),
        )
    else:
        runtime.database.execute(
            "update delivery_chunk set payload_hash = 'synthetic-drift' where delivery_outbox_id = ?",
            (event.id,),
        )
    runtime.database.execute(
        "update delivery_outbox set delivery_binding_json = ? where id = ?",
        (json.dumps(binding), event.id),
    )
    _retry_now(runtime, event)

    assert runtime.delivery_dispatcher.dispatch_pending(limit=1).failed == 1
    failed = runtime.delivery_repository.get_delivery_event(event.id)
    assert failed.last_error_code == (
        "delivery_chunk_payload_drift"
        if invalid == "payload_drift"
        else "delivery_chunk_plan_invalid"
    )
    assert len(adapter.calls) == 2


def test_chunk_plan_requires_current_claim_and_is_immutable(
    chunk_delivery: tuple[Container, DeliveryEvent, _FailSecondChunkOnceAdapter],
) -> None:
    runtime, _, _ = chunk_delivery
    claimed = runtime.delivery_repository.claim_delivery_event(
        worker_id="synthetic-worker", claim_timeout_seconds=60
    )
    assert claimed is not None
    with pytest.raises(NonRetryableExecutionError) as caught:
        runtime.delivery_repository.freeze_text_chunking(
            event=replace(claimed, claim_token="stale-token"), policy=ReportChunker(800).policy()
        )
    assert caught.value.error_code == "delivery_claim_lost"
    assert (
        "text_chunking"
        not in runtime.delivery_repository.get_delivery_event(claimed.id).delivery_binding
    )
    policy = runtime.delivery_repository.freeze_text_chunking(
        event=claimed, policy=ReportChunker(200).policy()
    )
    assert (
        runtime.delivery_repository.freeze_text_chunking(
            event=claimed, policy=ReportChunker(800).policy()
        )
        == policy
        == {"version": PARAGRAPH_CHUNKING, "max_chars": 200}
    )


def test_system_notice_also_freezes_chunks_across_retries() -> None:
    runtime = container()
    try:
        adapter = _FailSecondChunkOnceAdapter()
        runtime.result_delivery_service.adapters["test_chunked"] = adapter
        runtime.result_delivery_service.chunker = ReportChunker(200)
        event_id = runtime.result_delivery_service.enqueue_system_notice(
            idempotency_key="synthetic-chunked-notice",
            session_id="synthetic-session",
            reply_route={"type": "test_chunked", "target": {}},
            title="合成说明",
            markdown="x" * 450,
            reason_code="synthetic",
            correlation_id="synthetic-notice",
        )
        assert runtime.delivery_dispatcher.dispatch_pending(limit=1).retrying == 1
        event = runtime.delivery_repository.get_delivery_event(event_id)
        assert event.delivery_binding["text_chunking"] == {
            "version": PARAGRAPH_CHUNKING,
            "max_chars": 200,
        }
        runtime.result_delivery_service.chunker = ReportChunker(800)
        _retry_now(runtime, event)
        assert runtime.delivery_dispatcher.dispatch_pending(limit=1).succeeded == 1
        assert adapter.calls == [
            "合成说明 part 1/3",
            "合成说明 part 2/3",
            "合成说明 part 2/3",
            "合成说明 part 3/3",
        ]
    finally:
        runtime.database.close()
