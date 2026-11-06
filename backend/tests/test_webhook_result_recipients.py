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


def _bound_person(runtime, connector_id, suffix):
    from app.modules.job.infrastructure.persistence_values import now_iso

    user = runtime.identity_repository.create_user(
        username=f"recipient-{suffix}", display_name=f"Synthetic {suffix}"
    )
    connector = runtime.database.execute_one(
        "select dingtalk_enterprise_id from integration_connector where id=?", (connector_id,)
    )
    runtime.identity_repository.bind_dingtalk_identity(
        user_id=user["id"],
        dingtalk_enterprise_id=connector["dingtalk_enterprise_id"],
        external_subject_id=f"synthetic-{suffix}",
        display_name=user["display_name"],
        source_connector_id=connector_id,
        source_ingress_event_id="",
        observed_at=now_iso(),
        replace_current=False,
    )
    return user["id"]


def _publish_private(runtime, connector_id, user_ids):
    service = runtime.business_application_service
    code = "grafana-strict-runtime"
    detail = service.detail(actor_id="user_local_admin", code=code)
    payload = dict(detail["draft"])
    payload["triggers"] = [
        {
            key: row[key]
            for key in (
                "trigger_type",
                "connector_id",
                "routing_key",
                "actor_policy",
                "service_account_user_id",
                "enabled",
                "config",
            )
        }
        for row in payload["triggers"]
    ]
    payload["mcp_tools"] = [item["tool_identifier"] for item in payload["mcp_tools"]]
    payload["deliveries"] = [
        {
            "delivery_type": "dingtalk_private",
            "connector_id": connector_id,
            "enabled": True,
            "config": {
                "target_user_ids": user_ids,
                "trigger": {
                    key: payload["triggers"][0][key]
                    for key in ("trigger_type", "connector_id", "routing_key")
                },
            },
        }
    ]
    revision = service.save_draft(
        actor_id="user_local_admin",
        code=code,
        expected_revision=detail["revision"],
        payload=payload,
    )
    publication = service.publish(
        actor_id="user_local_admin", code=code, revision_id=revision["id"]
    )
    service.activate(
        actor_id="user_local_admin",
        code=code,
        environment="local",
        publication_id=publication["id"],
        expected_revision=detail["deployments"][0]["revision"],
    )
    return publication


def _dispatch_webhook(runtime):
    from backend.tests.test_webhook_ingress_dispatch import _receive, _firing

    received = _receive(runtime, _firing("synthetic-recipients"))
    runtime.webhook_outbox_publisher.publish_pending()
    runtime.message_bus.consume_webhook_events(runtime.webhook_dispatcher.handle)
    event = runtime.webhook_event_repository.get(received.event_id)
    assert event["status"] == "JOB_CREATED", event["error_summary"]
    return runtime.agent_repository.get_job(event["job_id"])


def test_application_owns_frozen_people_and_sends_each_result_independently():
    from backend.tests.test_webhook_ingress_dispatch import _container

    runtime = _container()
    try:
        connector_id = robot(runtime)
        people = [_bound_person(runtime, connector_id, suffix) for suffix in ("one", "two")]
        publication = _publish_private(runtime, connector_id, people)
        frozen = publication["snapshot"]["deliveries"][0]["resolved_recipients"]
        assert [row["user_id"] for row in frozen] == people
        catalog = runtime.business_application_service.catalog(
            actor_id="user_local_admin", code="grafana-strict-runtime"
        )
        assert {row["id"] for row in catalog["recipient_users_by_connector"][connector_id]} >= set(
            people
        )
        assert all(
            set(row) == {"id", "name"}
            for row in catalog["recipient_users_by_connector"][connector_id]
        )
        job = _dispatch_webhook(runtime)
        assert job.reply_route["target"]["recipients"] == frozen
        transport = FakeDingTalkTransport()
        runtime.result_delivery_service.adapters["dingtalk_robot_message"] = (
            DingTalkRobotResultDeliveryAdapter(
                connector_registry=runtime.connector_registry, transport=transport
            )
        )
        runtime.agent_executor.execute(
            job.id, worker_id="synthetic-worker", correlation_id="synthetic-recipients"
        )
        assert runtime.agent_repository.get_job(job.id).status.value == "SUCCEEDED"
        assert runtime.delivery_dispatcher.dispatch_pending(limit=10).succeeded == 2
        sends = [call for call in transport.calls if call["url"].endswith("oToMessages/batchSend")]
        assert len(sends) == 2
        assert {call["payload"]["userIds"][0] for call in sends} == {
            "synthetic-one",
            "synthetic-two",
        }
    finally:
        runtime.database.close()


def test_empty_people_runs_and_saves_result_without_sending():
    from backend.tests.test_webhook_ingress_dispatch import _container

    runtime = _container()
    try:
        connector_id = robot(runtime)
        _publish_private(runtime, connector_id, [])
        job = _dispatch_webhook(runtime)
        assert job.reply_route["type"] == "none"
        runtime.agent_executor.execute(
            job.id, worker_id="synthetic-worker", correlation_id="synthetic-none"
        )
        assert runtime.agent_repository.get_job(job.id).status.value == "SUCCEEDED"
        result = runtime.delivery_dispatcher.dispatch_pending(limit=10)
        assert result.succeeded == 0
    finally:
        runtime.database.close()


def test_disabled_recipient_fails_only_its_delivery_after_job_finishes():
    from backend.tests.test_webhook_ingress_dispatch import _container

    runtime = _container()
    try:
        connector_id = robot(runtime)
        people = [_bound_person(runtime, connector_id, suffix) for suffix in ("one", "two")]
        _publish_private(runtime, connector_id, people)
        job = _dispatch_webhook(runtime)
        transport = FakeDingTalkTransport()
        runtime.result_delivery_service.adapters["dingtalk_robot_message"] = (
            DingTalkRobotResultDeliveryAdapter(
                connector_registry=runtime.connector_registry, transport=transport
            )
        )
        runtime.agent_executor.execute(
            job.id, worker_id="synthetic-worker", correlation_id="synthetic-disabled"
        )
        runtime.database.execute(
            "update user_external_identity set status='disabled' where user_id=?", (people[0],)
        )
        result = runtime.delivery_dispatcher.dispatch_pending(limit=10)
        assert result.succeeded == 1 and result.failed == 1
        sends = [call for call in transport.calls if call["url"].endswith("oToMessages/batchSend")]
        assert len(sends) == 1 and sends[0]["payload"]["userIds"] == ["synthetic-two"]
    finally:
        runtime.database.close()


def test_cross_enterprise_or_unbound_people_cannot_be_published():
    from backend.tests.test_webhook_ingress_dispatch import _container

    runtime = _container()
    try:
        connector_id = robot(runtime)
        unbound = runtime.identity_repository.create_user(
            username="unbound-target", display_name="Unbound"
        )
        with pytest.raises(NonRetryableExecutionError):
            _publish_private(runtime, connector_id, [unbound["id"]])
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
        assert result.applied[:2] == ("148", "149")
        after = runtime.database.execute("select * from delivery_outbox")
        assert [{k: v for k, v in row.items() if k != "recipient_key"} for row in after] == before
        assert all(row["recipient_key"] == "" for row in after)
        assert runtime.database.execute("pragma foreign_key_check") == []
        assert Migrator(runtime.database, current, migrator_build="repeat").run().applied == ()
    finally:
        runtime.database.close()


@pytest.mark.parametrize("variant", ["valid", "legacy", "duplicate", "none"])
def test_application_private_binding_is_explicit_and_optional(variant):
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
        "delivery_type": "webhook_result" if variant == "legacy" else "dingtalk_private",
        "connector_id": "synthetic-robot",
        "resolved_recipients": route("synthetic-robot")["target"]["recipients"],
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
        "deliveries": [] if variant == "none" else [binding] * (2 if variant == "duplicate" else 1),
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
    if variant == "none":
        assert readiness.components["delivery"].status.value == "wired"
        assert (
            ChannelIngressService._application_reply_route(event, resolution, snapshot)["type"]
            == "none"
        )
    elif variant == "valid":
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


def test_http_application_draft_saves_recipients_with_explicit_trigger():
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.shared.config import synchronize_feature_configuration
    from backend.tests.test_unified_identity_rbac import csrf_headers, login, unified_settings
    from backend.tests.test_webhook_ingress_dispatch import _container

    runtime = _container()
    settings = replace(unified_settings(), feature_business_application_control_plane=True)
    runtime.settings = synchronize_feature_configuration(
        replace(
            runtime.settings,
            identity=settings.identity,
            feature_business_application_control_plane=True,
        )
    )
    connector = robot(runtime)
    people = [_bound_person(runtime, connector, suffix) for suffix in ("http-one", "http-two")]
    detail = runtime.business_application_service.detail(
        actor_id="user_local_admin", code="grafana-strict-runtime"
    )
    draft = detail["draft"]
    source = {
        key: draft["triggers"][0][key] for key in ("trigger_type", "connector_id", "routing_key")
    }
    payload = {
        "expected_revision": detail["revision"],
        "agent_publication_id": draft["agent_publication_id"],
        "triggers": [
            {
                key: draft["triggers"][0][key]
                for key in (
                    "trigger_type",
                    "connector_id",
                    "routing_key",
                    "actor_policy",
                    "service_account_user_id",
                    "enabled",
                    "config",
                )
            }
        ],
        "deliveries": [
            {
                "delivery_type": "dingtalk_private",
                "connector_id": connector,
                "enabled": True,
                "config": {"target_user_ids": people, "trigger": source},
            }
        ],
        "mcp_tools": [tool["tool_identifier"] for tool in draft["mcp_tools"]],
    }
    path = "/api/admin/business-applications/grafana-strict-runtime"
    with TestClient(create_app(settings, container_factory=lambda _: runtime)) as client:
        headers = csrf_headers(login(client))
        saved = client.put(path + "/draft", json=payload, headers=headers)
        assert saved.status_code == 200, saved.text
        revision = saved.json()["revision"]
        assert revision["deliveries"][0]["config"]["target_user_ids"] == people
        assert revision["deliveries"][0]["config"]["trigger"] == source
        read = client.get(path).json()["application"]["draft"]
        assert read["deliveries"][0]["config"] == revision["deliveries"][0]["config"]
        payload["expected_revision"] = revision["revision"]
        for variant in ("missing", "orphan", "duplicate"):
            invalid = deepcopy(payload)
            if variant == "missing":
                invalid["deliveries"][0]["config"].pop("trigger")
            elif variant == "orphan":
                invalid["deliveries"][0]["config"]["trigger"]["routing_key"] = (
                    "webhook:another-entry"
                )
            else:
                invalid["deliveries"].append(deepcopy(invalid["deliveries"][0]))
            rejected = client.put(path + "/draft", json=invalid, headers=headers)
            assert rejected.status_code in {400, 422}, rejected.text
        payload["deliveries"][0]["config"]["target_user_ids"] = []
        empty = client.put(path + "/draft", json=payload, headers=headers)
        assert empty.status_code == 200, empty.text
        assert empty.json()["revision"]["deliveries"][0]["config"]["target_user_ids"] == []


def test_each_webhook_uses_only_its_own_delivery_independent_of_order():
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

    def source(name):
        return {
            "trigger_type": "webhook",
            "connector_id": "synthetic-ingress",
            "routing_key": f"webhook:{name}",
        }

    snapshot = {
        "delivery_binding_mode": "per_trigger",
        "agent": {"id": "synthetic-agent", "config_hash": "synthetic-hash"},
        "triggers": [
            {
                **source(name),
                "enabled": True,
                "actor_policy": "SERVICE_ACCOUNT",
                "service_account_user_id": "synthetic-service",
            }
            for name in ("one", "two", "no-delivery")
        ],
        "deliveries": [
            {
                "delivery_type": "webhook_callback",
                "connector_id": "synthetic-callback",
                "enabled": True,
                "config": {"trigger": source("two"), "target_reference": "system-two"},
            },
            {
                "delivery_type": "dingtalk_private",
                "connector_id": "synthetic-robot",
                "enabled": True,
                "config": {"trigger": source("one")},
                "resolved_recipients": [
                    {
                        "connector_id": "synthetic-robot",
                        "kind": "user",
                        "target_id": "synthetic-person-one",
                    }
                ],
            },
        ],
    }
    readiness = RuntimeReadinessEvaluator(
        data_plane_enabled=True, runtime_environment="local"
    ).evaluate(snapshot=snapshot, deployment={"environment": "local", "active": True})
    assert readiness.components["delivery"].status.value == "wired"
    resolution = SimpleNamespace(outcome=RouteResolutionOutcome.MATCHED)

    def reply(name):
        event = ChannelEvent(
            source=ChannelSource(
                type="managed_webhook",
                connector_id="synthetic-ingress",
                event_id=name,
                actor_id="synthetic-service",
            ),
            delivery=ReplyRoute(type="none"),
            routing=RoutingContext(),
            webhook_trigger_id=name,
        )
        return ChannelIngressService._application_reply_route(event, resolution, snapshot)

    assert reply("one")["target"]["recipients"][0]["target_id"] == "synthetic-person-one"
    assert reply("two")["target"] == {"target_reference": "system-two"}
    assert reply("no-delivery")["type"] == "none"
    snapshot["deliveries"].reverse()
    assert reply("two")["connector_id"] == "synthetic-callback"
    snapshot["deliveries"][0]["resolved_recipients"] = []
    assert reply("one")["type"] == "none"
