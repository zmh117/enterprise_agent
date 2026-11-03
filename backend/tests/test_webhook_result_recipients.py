from __future__ import annotations

from copy import deepcopy
import json

import pytest

from app.modules.delivery.domain.recipient_routes import normalized_recipients
from app.modules.delivery.infrastructure.adapters import DingTalkRobotResultDeliveryAdapter
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.managed_channel.domain.models import DingTalkApplicationInput
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.support.channels import ensure_active_dingtalk_test_enterprise
from backend.tests.support.runtime import container
from backend.tests.test_dingtalk_delivery import FakeDingTalkTransport
from backend.tests.test_webhook_trigger_service import _config, _service


def robot(runtime):
    enterprise = runtime.managed_channel_service.create_dingtalk_enterprise(
        name="Synthetic recipients",
        actor_id="user_local_admin",
    )
    item = runtime.managed_channel_service.create_dingtalk(
        DingTalkApplicationInput(
            name="Synthetic robot",
            client_id="synthetic-recipients",
            client_secret="synthetic-secret-not-real-0123456789",
            dingtalk_enterprise_id=enterprise["id"],
            enterprise_robot_code="synthetic-robot",
        ),
        actor_id="user_local_admin",
        enabled=True,
    )
    ensure_active_dingtalk_test_enterprise(runtime, connector_id=item["id"])
    return item["id"]


def route(connector_id):
    return {
        "type": "dingtalk_recipients",
        "connector_id": "",
        "options": {},
        "target": {
            "recipients": [
                {
                    "connector_id": connector_id,
                    "kind": "group",
                    "target_id": "synthetic-group",
                    "label": "group",
                },
                {
                    "connector_id": connector_id,
                    "kind": "user",
                    "target_id": "synthetic-user",
                    "label": "user",
                },
            ]
        },
    }


class PartialTransport(FakeDingTalkTransport):
    def __init__(self):
        super().__init__()
        self.fail_user = True

    def post_json(self, url, payload, headers, timeout_seconds):
        result = super().post_json(url, payload, headers, timeout_seconds)
        if url.endswith("oToMessages/batchSend") and self.fail_user:
            return {"flowControlledStaffIdList": ["synthetic-user"]}
        return result


def pending(runtime, connector_id):
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="recipients",
            requester_id="local-user",
            external_conversation_id="synthetic",
            user_message="synthetic",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            project_code="default",
            correlation_id="synthetic-recipients",
            reply_route=route(connector_id),
        )
    )
    artifact = runtime.agent_repository.add_artifact(
        job_id=job.id, artifact_type="report", name="synthetic.md", content="Synthetic Agent result"
    )
    runtime.database.execute("update agent_job set status='SUCCEEDED' where id=?", (job.id,))

    def enqueue():
        return runtime.result_delivery_service.enqueue_job_result(
            job_id=job.id, artifact_id=artifact, correlation_id="synthetic-recipients"
        )

    return job, enqueue


def test_two_recipients_partial_retry_and_duplicate_enqueue():
    runtime = container()
    try:
        connector_id = robot(runtime)
        transport = PartialTransport()
        runtime.result_delivery_service.adapters["dingtalk_robot_message"] = (
            DingTalkRobotResultDeliveryAdapter(
                connector_registry=runtime.connector_registry,
                transport=transport,
            )
        )
        job, enqueue = pending(runtime, connector_id)
        assert enqueue() == enqueue()
        assert len(runtime.delivery_repository.list_delivery_events(job.id)) == 2
        first = runtime.delivery_dispatcher.dispatch_pending(limit=10)
        assert first.succeeded == 1 and first.retrying == 1
        transport.fail_user = False
        runtime.database.execute(
            "update delivery_outbox set next_attempt_at='2000-01-01T00:00:00+00:00' where job_id=?",
            (job.id,),
        )
        second = runtime.delivery_dispatcher.dispatch_pending(limit=10)
        assert second.succeeded == 1
        assert runtime.delivery_dispatcher.dispatch_pending(limit=10).succeeded == 0
        group_calls = [x for x in transport.calls if x["url"].endswith("groupMessages/send")]
        user_calls = [x for x in transport.calls if x["url"].endswith("oToMessages/batchSend")]
        assert len(group_calls) == 1 and len(user_calls) == 2
        assert group_calls[0]["payload"]["openConversationId"] == "synthetic-group"
        assert user_calls[-1]["payload"]["userIds"] == ["synthetic-user"]
        assert "Synthetic Agent result" in user_calls[-1]["payload"]["msgParam"]
        assert all(
            x["status"] == "SUCCEEDED"
            for x in runtime.delivery_repository.list_delivery_events(job.id)
        )
    finally:
        runtime.database.close()


@pytest.mark.parametrize("mutation", ["duplicate", "empty", "too_many", "url", "extra"])
def test_recipient_validation_is_bounded(mutation):
    value = route("robot")
    rows = value["target"]["recipients"]
    if mutation == "duplicate":
        rows.append(deepcopy(rows[0]))
    if mutation == "empty":
        rows.clear()
    if mutation == "too_many":
        rows.extend(deepcopy(rows[0]) for _ in range(20))
    if mutation == "url":
        rows[0]["target_id"] = "https://invalid.example/"
    if mutation == "extra":
        value["options"] = {"endpoint": "https://invalid.example/"}
    with pytest.raises(NonRetryableExecutionError):
        normalized_recipients(value)


@pytest.mark.parametrize("broken", ["binding", "job_route", "disabled"])
def test_dispatch_rejects_tampering_and_disabled_robot(broken):
    runtime = container()
    try:
        connector_id = robot(runtime)
        transport = FakeDingTalkTransport()
        runtime.result_delivery_service.adapters["dingtalk_robot_message"] = (
            DingTalkRobotResultDeliveryAdapter(
                connector_registry=runtime.connector_registry,
                transport=transport,
            )
        )
        job, enqueue = pending(runtime, connector_id)
        event_id = enqueue()
        if broken == "binding":
            events = runtime.database.execute(
                "select id, delivery_binding_json from delivery_outbox where job_id=? order by id",
                (job.id,),
            )
            runtime.database.execute(
                "update delivery_outbox set delivery_binding_json=? where id=?",
                (events[1]["delivery_binding_json"], events[0]["id"]),
            )
        elif broken == "job_route":
            changed = route(connector_id)
            changed["target"]["recipients"][0]["target_id"] = "other-group"
            runtime.database.execute(
                "update agent_job set reply_route_json=? where id=?", (json.dumps(changed), job.id)
            )
        else:
            runtime.database.execute(
                "update integration_connector set enabled=0 where id=?", (connector_id,)
            )
        result = runtime.delivery_dispatcher.dispatch_pending(limit=10)
        assert result.failed >= 1
        assert len([x for x in transport.calls if "robot/" in x["url"]]) <= (
            1 if broken == "binding" else 0
        )
        assert event_id
    finally:
        runtime.database.close()


def test_fanout_rolls_back_if_second_event_cannot_be_persisted(monkeypatch):
    runtime = container()
    try:
        job, enqueue = pending(runtime, robot(runtime))
        original = runtime.delivery_repository.create_delivery_event
        calls = 0

        def fail_second(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic persistence failure")
            return original(**kwargs)

        monkeypatch.setattr(runtime.delivery_repository, "create_delivery_event", fail_second)
        with pytest.raises(RuntimeError):
            enqueue()
        assert runtime.delivery_repository.list_delivery_events(job.id) == []
    finally:
        runtime.database.close()


def test_publish_requires_agent_delivery_assignment(monkeypatch):
    runtime, service = _service(monkeypatch)
    try:
        connector_id = robot(runtime)
        config = _config()
        config["delivery"] = route(connector_id)
        created = service.create(
            actor_id="user_local_admin",
            code="recipients",
            name="Synthetic recipients",
            trigger_type="grafana",
            connector_id="connector-grafana-default",
            config=config,
        )
        errors, _ = service.validator.validate(
            definition=created["definition"], config=created["draft"]["config"]
        )
        assert any("delivery" in error["field"] for error in errors)
        runtime.database.execute(
            "insert into agent_channel_binding (id, publication_id, direction, connector_id, config_json, created_at) values ('synthetic-recipient-binding','agent_publication_default_v1','delivery',?,'{}',CURRENT_TIMESTAMP)",
            (connector_id,),
        )
        errors, _ = service.validator.validate(
            definition=created["definition"], config=created["draft"]["config"]
        )
        assert errors == []
        assert any(
            x["id"] == connector_id and x["supports_robot_delivery"]
            for x in runtime.agent_config_service.repository.connector_catalog()
        )
        with pytest.raises(NonRetryableExecutionError):
            runtime.connector_registry.require_delivery(connector_id)
    finally:
        runtime.database.close()


def test_webhook_application_preserves_frozen_recipients_through_agent_result():
    from backend.tests.test_webhook_ingress_dispatch import _container, _receive, _firing
    from app.modules.webhook.domain.models import config_hash
    from app.modules.webhook.application.ingress_service import _revision_config

    runtime = _container(webhook_result=True)
    try:
        connector_id = robot(runtime)
        publication = runtime.webhook_trigger_repository.get_publication(
            "webhook_trigger_publication_grafana_v1"
        )
        snapshot = publication["snapshot"]
        snapshot["delivery"] = route(connector_id)
        runtime.database.execute(
            "update webhook_trigger_publication set snapshot_json=?, config_hash=? where id=?",
            (json.dumps(snapshot), config_hash(_revision_config(snapshot)), publication["id"]),
        )
        runtime.database.execute(
            "insert into agent_channel_binding (id, publication_id, direction, connector_id, config_json, created_at) values ('synthetic-runtime-binding','agent_publication_default_v1','delivery',?,'{}',CURRENT_TIMESTAMP)",
            (connector_id,),
        )
        received = _receive(runtime, _firing("synthetic-recipients"))
        assert received.accepted
        runtime.webhook_outbox_publisher.publish_pending()
        runtime.message_bus.consume_webhook_events(runtime.webhook_dispatcher.handle)
        event = runtime.webhook_event_repository.get(received.event_id)
        assert event["status"] == "JOB_CREATED"
        job = runtime.agent_repository.get_job(event["job_id"])
        assert job.reply_route == route(connector_id)
        # Later configuration cannot replace the accepted event / Job recipients.
        snapshot["delivery"]["target"]["recipients"][0]["target_id"] = "later-config-group"
        runtime.database.execute(
            "update webhook_trigger_publication set snapshot_json=?, config_hash=? where id=?",
            (json.dumps(snapshot), config_hash(_revision_config(snapshot)), publication["id"]),
        )
        transport = FakeDingTalkTransport()
        runtime.result_delivery_service.adapters["dingtalk_robot_message"] = (
            DingTalkRobotResultDeliveryAdapter(
                connector_registry=runtime.connector_registry, transport=transport
            )
        )
        runtime.agent_executor.execute(
            job.id, worker_id="synthetic-worker", correlation_id="synthetic-recipients"
        )
        completed = runtime.agent_repository.get_job(job.id)
        assert completed.status.value == "SUCCEEDED"
        assert runtime.delivery_dispatcher.dispatch_pending(limit=10).succeeded == 2
        group_call = next(x for x in transport.calls if x["url"].endswith("groupMessages/send"))
        assert group_call["payload"]["openConversationId"] == "synthetic-group"
    finally:
        runtime.database.close()


def test_sqlite_upgrade_preserves_existing_delivery_and_binding(tmp_path, monkeypatch):
    from app.shared.database import default_migrations_dir
    from app.shared.migrations import Migrator
    from backend.tests.test_dingtalk_enterprise_migration import _catalog_through
    from backend.tests.test_delivery_outbox_schema import _insert_event

    current = default_migrations_dir()
    old = _catalog_through(tmp_path, 147)
    with monkeypatch.context() as patch:
        patch.setattr("app.bootstrap.default_migrations_dir", lambda: old)
        patch.setattr("app.shared.runtime_config_loader.default_migrations_dir", lambda: old)
        runtime = container()
    try:
        job = runtime.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="migration-recipient",
                requester_id="local-user",
                external_conversation_id="migration",
                user_message="synthetic",
                source_channel="debug_api",
                source_connector_id="connector-debug-api",
                project_code="default",
                correlation_id="synthetic-upgrade",
                reply_route={"type": "none"},
            )
        )
        artifact = runtime.agent_repository.add_artifact(
            job_id=job.id,
            artifact_type="report",
            name="synthetic.md",
            content="Synthetic migration result",
        )
        _insert_event(runtime, job.id, artifact)
        before = runtime.database.execute("select * from delivery_outbox")
        result = Migrator(runtime.database, current, migrator_build="recipient-upgrade-test").run()
        assert result.applied == ("148", "149")
        after = runtime.database.execute("select * from delivery_outbox")
        assert [{k: v for k, v in row.items() if k != "recipient_key"} for row in after] == before
        assert all(row["recipient_key"] == "" for row in after)
        assert runtime.database.execute("pragma foreign_key_check") == []
        assert Migrator(runtime.database, current, migrator_build="repeat").run().applied == ()
    finally:
        runtime.database.close()


@pytest.mark.parametrize("variant", ["valid", "other_source", "duplicate"])
def test_application_webhook_result_binding_is_explicit_and_unique(variant):
    from types import SimpleNamespace
    from app.modules.business_application.domain.runtime import (
        RuntimeReadinessEvaluator,
        RouteResolutionOutcome,
    )
    from app.modules.channel.application.channel_ingress_service import ChannelIngressService
    from app.modules.channel.domain.channel_event import (
        ChannelEvent,
        ChannelSource,
        ReplyRoute,
        RoutingContext,
    )

    source = "synthetic-ingress"
    binding = {
        "delivery_type": "webhook_result",
        "connector_id": source if variant != "other_source" else "wrong-source",
        "enabled": True,
        "config": {},
    }
    snapshot = {
        "agent": {"id": "synthetic-agent", "config_hash": "hash"},
        "triggers": [
            {
                "trigger_type": "webhook",
                "connector_id": source,
                "enabled": True,
                "actor_policy": "SERVICE_ACCOUNT",
                "service_account_user_id": "synthetic-service",
                "routing_key": "webhook:synthetic",
                "config": {"webhook_definition_id": "synthetic"},
            }
        ],
        "deliveries": [binding] * (2 if variant == "duplicate" else 1),
    }
    readiness = RuntimeReadinessEvaluator(
        data_plane_enabled=True, runtime_environment="local"
    ).evaluate(snapshot=snapshot, deployment={"environment": "local", "active": True})
    event = ChannelEvent(
        source=ChannelSource(
            type="managed_webhook",
            connector_id=source,
            event_id="synthetic",
            actor_id="synthetic-service",
        ),
        delivery=ReplyRoute.from_dict(route("synthetic-robot")),
        routing=RoutingContext(),
        webhook_trigger_id="synthetic",
    )
    resolution = SimpleNamespace(outcome=RouteResolutionOutcome.MATCHED)
    if variant == "valid":
        assert readiness.components["delivery"].status.value == "wired"
        assert (
            ChannelIngressService._application_reply_route(event, resolution, snapshot)
            == event.delivery.to_dict()
        )
    else:
        assert readiness.components["delivery"].status.value == "blocked"
        with pytest.raises(NonRetryableExecutionError):
            ChannelIngressService._application_reply_route(event, resolution, snapshot)


def test_invalid_user_response_is_failure_without_resending_successful_group():
    class InvalidUserTransport(FakeDingTalkTransport):
        def post_json(self, url, payload, headers, timeout_seconds):
            result = super().post_json(url, payload, headers, timeout_seconds)
            if url.endswith("oToMessages/batchSend"):
                return {"invalidStaffIdList": ["synthetic-user"]}
            return result

    runtime = container()
    try:
        transport = InvalidUserTransport()
        runtime.result_delivery_service.adapters["dingtalk_robot_message"] = (
            DingTalkRobotResultDeliveryAdapter(
                connector_registry=runtime.connector_registry, transport=transport
            )
        )
        job, enqueue = pending(runtime, robot(runtime))
        enqueue()
        result = runtime.delivery_dispatcher.dispatch_pending(limit=10)
        assert result.succeeded == 1 and result.failed == 1
        assert {x["status"] for x in runtime.delivery_repository.list_delivery_events(job.id)} == {
            "SUCCEEDED",
            "FAILED",
        }
        assert runtime.delivery_dispatcher.dispatch_pending(limit=10).succeeded == 0
        assert len([x for x in transport.calls if "robot/" in x["url"]]) == 2
    finally:
        runtime.database.close()
