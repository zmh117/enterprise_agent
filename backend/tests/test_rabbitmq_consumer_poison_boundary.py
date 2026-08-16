from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.message_bus.infrastructure.rabbitmq_consumer import (
    process_agent_job_delivery,
)
from app.modules.message_bus.infrastructure.rabbitmq_topology import (
    declare_agent_job_topology,
)
from app.shared.config import QueueSettings


class _Channel:
    def __init__(self, *, publish_confirmed: bool = True) -> None:
        self.is_open = True
        self.publish_confirmed = publish_confirmed
        self.acks: list[str] = []
        self.nacks: list[tuple[str, bool]] = []
        self.published: list[dict[str, Any]] = []
        self.declarations: list[dict[str, Any]] = []

    def basic_ack(self, *, delivery_tag: str) -> None:
        self.acks.append(delivery_tag)

    def basic_nack(self, *, delivery_tag: str, requeue: bool) -> None:
        self.nacks.append((delivery_tag, requeue))

    def basic_publish(self, **kwargs: Any) -> bool:
        self.published.append(kwargs)
        return self.publish_confirmed

    def queue_declare(self, **kwargs: Any) -> None:
        self.declarations.append(kwargs)


def _method(*, redelivered: bool = False) -> SimpleNamespace:
    return SimpleNamespace(delivery_tag="delivery-1", redelivered=redelivered)


def _properties_factory(_original: Any, classification: str) -> dict[str, Any]:
    return {"delivery_mode": 2, "classification": classification}


def _body(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "event_id": "dispatch-event-1",
        "job_id": "job-1",
        "correlation_id": "correlation-1",
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


@pytest.mark.parametrize(
    "body",
    (
        b"\xff",
        b"not-json",
        b"[]",
        json.dumps({"job_id": "job-1"}).encode(),
        json.dumps({"event_id": "event-1"}).encode(),
        json.dumps({"event_id": " ", "job_id": "job-1"}).encode(),
        b"x" * (64 * 1024 + 1),
    ),
)
def test_malformed_agent_job_envelope_is_quarantined_without_handler(body: bytes) -> None:
    channel = _Channel()
    calls: list[object] = []

    disposition = process_agent_job_delivery(
        channel,
        _method(),
        SimpleNamespace(),
        body,
        calls.append,
        dead_queue="agent.job.dead.test",
        properties_factory=_properties_factory,
    )

    assert disposition == "quarantined"
    assert calls == []
    assert channel.nacks == []
    assert channel.acks == ["delivery-1"]
    assert channel.published[0]["routing_key"] == "agent.job.dead.test"
    assert channel.published[0]["body"] == body
    assert channel.published[0]["mandatory"] is True
    assert channel.published[0]["properties"]["delivery_mode"] == 2


def test_first_valid_handler_failure_requeues_once_without_quarantine() -> None:
    channel = _Channel()

    def fail(_message: object) -> None:
        raise RuntimeError("synthetic infrastructure failure")

    disposition = process_agent_job_delivery(
        channel,
        _method(redelivered=False),
        SimpleNamespace(),
        _body(),
        fail,
        dead_queue="agent.job.dead.test",
        properties_factory=_properties_factory,
    )

    assert disposition == "requeued"
    assert channel.nacks == [("delivery-1", True)]
    assert channel.acks == []
    assert channel.published == []


def test_redelivered_handler_failure_is_quarantined_and_acked() -> None:
    channel = _Channel()

    def fail(_message: object) -> None:
        raise RuntimeError("synthetic persistent infrastructure failure")

    disposition = process_agent_job_delivery(
        channel,
        _method(redelivered=True),
        SimpleNamespace(),
        _body(),
        fail,
        dead_queue="agent.job.dead.test",
        properties_factory=_properties_factory,
    )

    assert disposition == "quarantined"
    assert channel.nacks == []
    assert channel.acks == ["delivery-1"]
    assert channel.published[0]["properties"]["classification"] == (
        "handler_failed_after_redelivery"
    )


def test_failed_quarantine_publish_is_not_acked() -> None:
    channel = _Channel(publish_confirmed=False)

    with pytest.raises(RuntimeError, match="quarantine publish confirm failed"):
        process_agent_job_delivery(
            channel,
            _method(),
            SimpleNamespace(),
            b"not-json",
            lambda _message: None,
            dead_queue="agent.job.dead.test",
            properties_factory=_properties_factory,
        )

    assert channel.acks == []
    assert channel.nacks == []


def test_handler_business_retry_return_is_only_acked_by_consumer() -> None:
    channel = _Channel()
    persisted = {"job_retry": 0, "outbox": 0}

    def persist_business_retry(_message: object) -> None:
        persisted["job_retry"] += 1
        persisted["outbox"] += 1

    disposition = process_agent_job_delivery(
        channel,
        _method(),
        SimpleNamespace(),
        _body(),
        persist_business_retry,
        dead_queue="agent.job.dead.test",
        properties_factory=_properties_factory,
    )

    assert disposition == "acked"
    assert persisted == {"job_retry": 1, "outbox": 1}
    assert channel.acks == ["delivery-1"]
    assert channel.nacks == []
    assert channel.published == []


def test_agent_job_topology_declares_main_and_durable_dead_queue() -> None:
    channel = _Channel()
    queue = QueueSettings(
        job_queue="agent.job.main.test",
        dead_queue="agent.job.dead.test",
    )

    declare_agent_job_topology(channel, queue)

    assert channel.declarations == [
        {"queue": "agent.job.dead.test", "durable": True},
        {"queue": "agent.job.main.test", "durable": True},
    ]
