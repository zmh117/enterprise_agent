from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.managed_channel.domain import (
    ChannelIngressSubmission,
    DingTalkApplicationInput,
)
from app.shared.config import IdentitySettings, Settings
from backend.tests.helpers import ensure_active_dingtalk_test_enterprise


ADMIN_PASSWORD = "111111111111"
ORIGIN = "http://admin.test"


def _settings() -> Settings:
    return Settings(
        database_dsn="sqlite:///:memory:",
        app_config_master_key="identity-discovery-api-test-key",
        environment="local",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=False,
            cookie_secure=False,
            allowed_origins=(ORIGIN,),
            dingtalk_tenant_code="tenant-discovery",
        ),
    )


def _container():
    container = build_test_container(_settings(), migrate=True, seed=True)
    enterprise = ensure_active_dingtalk_test_enterprise(
        container,
        corp_id="corp-discovery-api",
        name="管理端身份发现测试企业",
    )
    connector = container.managed_channel_service.create_dingtalk(
        DingTalkApplicationInput(
            name="管理端发现测试机器人",
            client_id="identity-discovery-api-client",
            client_secret="fixture-only-api-secret",
            dingtalk_enterprise_id=str(enterprise["id"]),
        ),
        actor_id="user_local_admin",
        enabled=True,
    )
    return container, connector


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("enterprise_agent_csrf")
    assert csrf
    return {"origin": ORIGIN, "x-csrf-token": csrf}


def _submission(
    connector_id: str,
    event_id: str,
    *,
    sender_id: str,
    sender_name: str,
    conversation_type: str = "1",
    conversation_id: str = "private-discovery",
    robot_code: str = "robot-discovery-api",
    text: str = "需要管理员绑定",
    extra: dict[str, Any] | None = None,
) -> ChannelIngressSubmission:
    payload: dict[str, Any] = {
        "conversationId": conversation_id,
        "conversationType": conversation_type,
        "senderStaffId": sender_id,
        "senderNick": sender_name,
        "senderCorpId": "corp-discovery-api",
        "chatbotCorpId": "corp-discovery-api",
        "msgId": event_id,
        "robotCode": robot_code,
        "createAt": 1_785_024_000_000,
        "msgtype": "text",
        "text": {"content": text},
    }
    payload.update(extra or {})
    return ChannelIngressSubmission(
        connector_id=connector_id,
        external_event_id=event_id,
        correlation_id=f"correlation-{event_id}",
        normalized_event=payload,
        safe_summary={"msgtype": str(payload.get("msgtype") or "")},
        payload_hash=f"fixture-hash-{event_id}",
        request_bytes=512,
    )


def _dispatch(container, submission: ChannelIngressSubmission) -> dict[str, Any]:
    lease = container.runtime_control_service.acquire("runtime-discovery-api")
    if lease is None:
        lease = container.database.execute_one(
            """
            select lease_token
            from channel_runtime_lease
            where lease_name = 'dingtalk-stream-runtime-singleton'
            """
        )
    assert lease is not None
    event, _ = container.runtime_control_service.receive(
        "runtime-discovery-api",
        str(lease["lease_token"]),
        submission,
    )
    container.channel_outbox_publisher.publish_pending(limit=10)
    assert container.message_bus is not None
    container.message_bus.consume_channel_events(container.channel_dispatch_service.handle)
    return container.managed_channel_repository.get_event(str(event["id"]))


def test_candidate_api_search_filters_cursor_count_and_safe_dto() -> None:
    container, connector = _container()
    connector_id = str(connector["id"])
    _dispatch(
        container,
        _submission(
            connector_id,
            "event-api-private",
            sender_id="staff-api-both",
            sender_name="<script>待绑定甲</script>",
            text="<b>私聊内容</b>",
        ),
    )
    _dispatch(
        container,
        _submission(
            connector_id,
            "event-api-group",
            sender_id="staff-api-both",
            sender_name="<script>待绑定甲</script>",
            conversation_type="2",
            conversation_id="group-api-safe",
            text="群聊内容",
        ),
    )
    _dispatch(
        container,
        _submission(
            connector_id,
            "event-api-group-only",
            sender_id="staff-api-group",
            sender_name="待绑定乙",
            conversation_type="2",
            conversation_id="group-api-searchable",
            robot_code="robot-searchable",
            text="只在群聊出现",
            extra={
                "msgtype": "file",
                "text": {},
                "content": {
                    "downloadCode": "fixture-api-download-code",
                    "fileName": "<img src=x onerror=alert(1)>.txt",
                    "fileSize": 256,
                },
            },
        ),
    )
    app = create_app(_settings(), container_factory=lambda _: container)

    with TestClient(app) as client:
        unauthenticated = client.get("/api/admin/dingtalk-identity-candidates")
        assert unauthenticated.status_code == 401
        _login(client)

        count = client.get("/api/admin/dingtalk-identity-candidates/count")
        assert count.status_code == 200
        assert count.json() == {"count": 2}

        both = client.get(
            "/api/admin/dingtalk-identity-candidates",
            params={"conversation_scope": "both"},
        )
        assert both.status_code == 200, both.text
        assert [item["external_subject_id"] for item in both.json()["candidates"]] == [
            "staff-api-both"
        ]

        group_only = client.get(
            "/api/admin/dingtalk-identity-candidates",
            params={"conversation_scope": "group"},
        )
        assert group_only.status_code == 200
        assert [item["external_subject_id"] for item in group_only.json()["candidates"]] == [
            "staff-api-group"
        ]

        searched = client.get(
            "/api/admin/dingtalk-identity-candidates",
            params={"search": "robot-searchable"},
        )
        assert searched.status_code == 200
        assert len(searched.json()["candidates"]) == 1

        first_page = client.get(
            "/api/admin/dingtalk-identity-candidates",
            params={"limit": 1},
        )
        assert first_page.status_code == 200
        assert first_page.json()["has_more"] is True
        assert first_page.json()["next_cursor"]
        second_page = client.get(
            "/api/admin/dingtalk-identity-candidates",
            params={
                "limit": 1,
                "cursor": first_page.json()["next_cursor"],
            },
        )
        assert second_page.status_code == 200
        assert second_page.json()["candidates"][0]["id"] != first_page.json()["candidates"][0]["id"]

        invalid_cursor = client.get(
            "/api/admin/dingtalk-identity-candidates",
            params={"cursor": "not-a-valid-cursor"},
        )
        assert invalid_cursor.status_code == 400
        assert invalid_cursor.json()["detail"]["code"] == "validation_failed"

        serialized = json.dumps(
            {
                "list": client.get("/api/admin/dingtalk-identity-candidates").json(),
                "audit": container.database.execute(
                    "select event_type, summary, payload_summary from audit_event"
                ),
            },
            ensure_ascii=False,
        )
        assert "<script>待绑定甲</script>" in serialized
        assert "<b>私聊内容</b>" in serialized
        assert "fixture-api-download-code" not in serialized
        for forbidden in (
            "normalized_event",
            "sessionWebhook",
            "reply_credential_ciphertext",
        ):
            assert forbidden not in serialized


def test_candidate_binding_is_trusted_csrf_protected_and_immediately_hidden() -> None:
    container, connector = _container()
    connector_id = str(connector["id"])
    _dispatch(
        container,
        _submission(
            connector_id,
            "event-api-bind",
            sender_id="staff-api-bind",
            sender_name="准备绑定人员",
            text="这条旧消息不能回放",
        ),
    )
    target = container.identity_repository.create_user(
        username="candidate-target",
        display_name="候选目标人员",
    )
    app = create_app(_settings(), container_factory=lambda _: container)

    with TestClient(app) as client:
        headers = _login(client)
        candidate = client.get("/api/admin/dingtalk-identity-candidates").json()["candidates"][0]
        body = {
            "target_user_id": target["id"],
            "expected_candidate_revision": candidate["revision"],
            "expected_user_revision": target["revision"],
            "bind_without_access_confirmed": True,
        }

        missing_csrf = client.post(
            f"/api/admin/dingtalk-identity-candidates/{candidate['id']}/bind",
            json=body,
        )
        assert missing_csrf.status_code == 403

        forged = client.post(
            f"/api/admin/dingtalk-identity-candidates/{candidate['id']}/bind",
            headers=headers,
            json={
                **body,
                "tenant_code": "forged-tenant",
                "external_subject_id": "forged-subject",
                "connector_id": "forged-connector",
            },
        )
        assert forged.status_code == 422

        stale = client.post(
            f"/api/admin/dingtalk-identity-candidates/{candidate['id']}/bind",
            headers=headers,
            json={**body, "expected_candidate_revision": candidate["revision"] + 1},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "revision_conflict"

        created_before_failed_binding = client.post(
            "/api/admin/users",
            headers=headers,
            json={
                "username": "created-before-bind-failure",
                "display_name": "绑定失败后保留",
            },
        )
        assert created_before_failed_binding.status_code == 200
        retained_user = created_before_failed_binding.json()["user"]
        failed_after_create = client.post(
            f"/api/admin/dingtalk-identity-candidates/{candidate['id']}/bind",
            headers=headers,
            json={
                "target_user_id": retained_user["id"],
                "expected_candidate_revision": candidate["revision"] + 1,
                "expected_user_revision": retained_user["revision"],
                "bind_without_access_confirmed": True,
            },
        )
        assert failed_after_create.status_code == 409
        assert client.get(f"/api/admin/users/{retained_user['id']}").status_code == 200

        bound = client.post(
            f"/api/admin/dingtalk-identity-candidates/{candidate['id']}/bind",
            headers=headers,
            json=body,
        )
        assert bound.status_code == 200, bound.text
        identity = bound.json()["identity"]
        assert identity["dingtalk_enterprise_id"] == connector["enterprise"]["id"]
        assert identity["external_subject_id"] == "staff-api-bind"
        assert identity["connector_id"] == ""

        assert client.get("/api/admin/dingtalk-identity-candidates/count").json() == {"count": 0}
        assert (
            client.get(f"/api/admin/dingtalk-identity-candidates/{candidate['id']}").status_code
            == 404
        )
        assert (
            container.database.execute_one("select count(*) as count from agent_job") or {}
        ).get("count") == 0

        audit = json.dumps(
            container.database.execute(
                """
                select event_type, summary, payload_summary
                from audit_event
                where event_type like 'identity.discovery.%'
                order by created_at
                """
            ),
            ensure_ascii=False,
        )
        assert "这条旧消息不能回放" not in audit
        assert "staff-api-bind" not in audit
        assert "identity.discovery.bound" in audit


def test_historical_identity_can_only_return_to_original_user() -> None:
    container, connector = _container()
    connector_id = str(connector["id"])
    original = container.identity_repository.create_user(
        username="historical-original",
        display_name="历史原人员",
    )
    identity = container.identity_repository.bind_external_identity(
        user_id=str(original["id"]),
        provider="dingtalk",
        tenant_code=connector["enterprise"]["id"],
        external_subject_id="staff-historical-api",
        connector_id="",
        display_name="历史原人员",
    )
    container.database.execute(
        "update user_external_identity set dingtalk_enterprise_id = ? where id = ?",
        (connector["enterprise"]["id"], identity["id"]),
    )
    identity = container.identity_repository.get_external_identity(str(identity["id"]))
    unbound = container.identity_repository.unbind_external_identity(
        str(identity["id"]),
        expected_revision=int(identity["revision"]),
    )
    target = container.identity_repository.create_user(
        username="historical-other",
        display_name="其它人员",
    )
    _dispatch(
        container,
        _submission(
            connector_id,
            "event-api-historical",
            sender_id="staff-historical-api",
            sender_name="历史原人员",
        ),
    )
    app = create_app(_settings(), container_factory=lambda _: container)

    with TestClient(app) as client:
        headers = _login(client)
        candidate = client.get("/api/admin/dingtalk-identity-candidates").json()["candidates"][0]
        assert candidate["identity_state"] == "restore_required"
        assert candidate["historical_identity"] == {
            "id": identity["id"],
            "status": "unbound",
            "revision": unbound["revision"],
            "user_id": original["id"],
            "username": original["username"],
            "user_display_name": original["display_name"],
            "user_status": "enabled",
        }

        conflict = client.post(
            f"/api/admin/dingtalk-identity-candidates/{candidate['id']}/bind",
            headers=headers,
            json={
                "target_user_id": target["id"],
                "expected_candidate_revision": candidate["revision"],
                "expected_user_revision": target["revision"],
                "bind_without_access_confirmed": True,
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "identity_restore_required"
        assert (
            container.identity_repository.get_external_identity(str(identity["id"]))["user_id"]
            == original["id"]
        )

        direct_restore = client.put(
            f"/api/admin/identities/{identity['id']}/status",
            headers=headers,
            json={
                "expected_revision": unbound["revision"],
                "status": "enabled",
            },
        )
        assert direct_restore.status_code == 409
        assert direct_restore.json()["detail"]["code"] == "identity_restore_required"

        restored = client.post(
            f"/api/admin/dingtalk-identity-candidates/{candidate['id']}/bind",
            headers=headers,
            json={
                "target_user_id": original["id"],
                "expected_candidate_revision": candidate["revision"],
                "expected_user_revision": original["revision"],
                "bind_without_access_confirmed": True,
            },
        )
        assert restored.status_code == 200
        assert restored.json()["identity"]["id"] == identity["id"]
        assert restored.json()["identity"]["status"] == "enabled"
        assert client.get("/api/admin/dingtalk-identity-candidates/count").json() == {"count": 0}


def test_candidate_binding_rejects_non_human_disabled_user_and_disabled_connector() -> None:
    container, connector = _container()
    connector_id = str(connector["id"])
    _dispatch(
        container,
        _submission(
            connector_id,
            "event-api-bind-guards",
            sender_id="staff-api-bind-guards",
            sender_name="绑定保护候选",
        ),
    )
    service_account = container.identity_repository.create_user(
        username="candidate-service-account",
        display_name="候选服务账号",
        account_type="service",
    )
    disabled_user = container.identity_repository.create_user(
        username="candidate-disabled-user",
        display_name="已停用候选目标",
        status="disabled",
    )
    valid_user = container.identity_repository.create_user(
        username="candidate-valid-before-channel-disable",
        display_name="渠道停用前有效人员",
    )
    app = create_app(_settings(), container_factory=lambda _: container)

    with TestClient(app) as client:
        headers = _login(client)
        candidate = client.get("/api/admin/dingtalk-identity-candidates").json()["candidates"][0]

        def bind_to(user: dict[str, Any]):
            return client.post(
                f"/api/admin/dingtalk-identity-candidates/{candidate['id']}/bind",
                headers=headers,
                json={
                    "target_user_id": user["id"],
                    "expected_candidate_revision": candidate["revision"],
                    "expected_user_revision": user["revision"],
                    "bind_without_access_confirmed": True,
                },
            )

        assert bind_to(service_account).status_code == 403
        disabled_result = bind_to(disabled_user)
        assert disabled_result.status_code == 409
        assert disabled_result.json()["detail"]["code"] == "revision_conflict"

        container.managed_channel_service.set_enabled(
            connector_id,
            enabled=False,
            expected_revision=int(connector["revision"]),
            actor_id="user_local_admin",
        )
        unavailable = bind_to(valid_user)
        assert unavailable.status_code == 403
        assert client.get("/api/admin/dingtalk-identity-candidates/count").json() == {"count": 1}


def test_private_and_group_candidates_bind_multiple_roles_atomically() -> None:
    container, connector = _container()
    connector_id = str(connector["id"])
    roles = [
        container.authorization_center_service.create_role(
            actor_id="user_local_admin",
            code=f"binding-role-{index}",
            name=f"绑定角色 {index}",
            description="",
            purpose_tags=["身份绑定"],
        )["role"]
        for index in (1, 2)
    ]
    cases = [
        ("private", "1", "private-binding-conversation"),
        ("group", "2", "group-binding-conversation"),
    ]
    targets: dict[str, dict[str, Any]] = {}
    for suffix, conversation_type, conversation_id in cases:
        _dispatch(
            container,
            _submission(
                connector_id,
                f"event-multi-role-{suffix}",
                sender_id=f"staff-multi-role-{suffix}",
                sender_name=f"多角色{suffix}",
                conversation_type=conversation_type,
                conversation_id=conversation_id,
            ),
        )
        targets[suffix] = container.identity_repository.create_user(
            username=f"multi-role-{suffix}",
            display_name=f"多角色目标{suffix}",
        )

    app = create_app(_settings(), container_factory=lambda _: container)
    with TestClient(app) as client:
        headers = _login(client)
        candidates = client.get("/api/admin/dingtalk-identity-candidates").json()["candidates"]
        by_subject = {candidate["external_subject_id"]: candidate for candidate in candidates}
        for suffix, _, _ in cases:
            candidate = by_subject[f"staff-multi-role-{suffix}"]
            target = targets[suffix]
            bound = client.post(
                f"/api/admin/dingtalk-identity-candidates/{candidate['id']}/bind",
                headers=headers,
                json={
                    "target_user_id": target["id"],
                    "expected_candidate_revision": candidate["revision"],
                    "expected_user_revision": target["revision"],
                    "initial_role_ids": [role["id"] for role in roles],
                    "bind_without_access_confirmed": False,
                },
            )
            assert bound.status_code == 200, bound.text
            result = bound.json()
            assert len(result["memberships"]) == 2
            assert result["authorization_summary"]["role_ids"] == [role["id"] for role in roles]
            assert result["authorization_summary"]["access_status"] == "未获得应用权限"
            assert {
                row["code"]
                for row in container.identity_repository.list_user_roles(str(target["id"]))
                if row["membership_status"] == "enabled"
            } == {"binding-role-1", "binding-role-2"}
        assert client.get("/api/admin/dingtalk-identity-candidates/count").json() == {"count": 0}


def test_cleanup_removes_only_expired_projection() -> None:
    container, connector = _container()
    event = _dispatch(
        container,
        _submission(
            str(connector["id"]),
            "event-api-expired",
            sender_id="staff-api-expired",
            sender_name="过期候选",
        ),
    )
    candidate = container.database.execute_one(
        """
        select id
        from dingtalk_identity_candidate
        where external_subject_id = 'staff-api-expired'
        """
    )
    assert candidate is not None
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    container.database.execute(
        """
        update dingtalk_identity_candidate
        set last_seen_at = ?, updated_at = ?
        where id = ?
        """,
        (old, old, candidate["id"]),
    )

    assert container.identity_discovery_service.count_candidates() == 0
    assert container.identity_discovery_service.cleanup_expired() == 1
    assert (
        container.database.execute_one(
            "select id from dingtalk_identity_candidate where id = ?",
            (candidate["id"],),
        )
        is None
    )
    assert container.managed_channel_repository.get_event(str(event["id"]))["status"] == (
        "REJECTED"
    )


def test_time_fallback_thirty_day_boundary_and_large_count() -> None:
    container, connector = _container()
    connector_id = str(connector["id"])
    valid_event = _dispatch(
        container,
        _submission(
            connector_id,
            "event-api-valid-time",
            sender_id="staff-api-valid-time",
            sender_name="有效时间",
        ),
    )
    invalid_event = _dispatch(
        container,
        _submission(
            connector_id,
            "event-api-invalid-time",
            sender_id="staff-api-invalid-time",
            sender_name="异常时间",
            extra={"createAt": "far-from-a-timestamp"},
        ),
    )
    valid_message = container.database.execute_one(
        """
        select occurred_at
        from dingtalk_identity_candidate_message
        where source_ingress_event_id = ?
        """,
        (valid_event["id"],),
    )
    invalid_message = container.database.execute_one(
        """
        select occurred_at, received_at
        from dingtalk_identity_candidate_message
        where source_ingress_event_id = ?
        """,
        (invalid_event["id"],),
    )
    assert valid_message is not None
    assert str(valid_message["occurred_at"]).startswith("2026-07-26T")
    assert invalid_message is not None
    assert invalid_message["occurred_at"] == invalid_message["received_at"]

    cutoff = "2026-06-26T00:00:00+00:00"
    candidates = container.database.execute(
        """
        select id, external_subject_id
        from dingtalk_identity_candidate
        where external_subject_id in (?, ?)
        """,
        ("staff-api-valid-time", "staff-api-invalid-time"),
    )
    at_boundary = next(
        row for row in candidates if row["external_subject_id"] == "staff-api-valid-time"
    )
    before_boundary = next(
        row for row in candidates if row["external_subject_id"] == "staff-api-invalid-time"
    )
    container.database.execute(
        "update dingtalk_identity_candidate set last_seen_at = ? where id = ?",
        (cutoff, at_boundary["id"]),
    )
    container.database.execute(
        "update dingtalk_identity_candidate set last_seen_at = ? where id = ?",
        ("2026-06-25T23:59:59+00:00", before_boundary["id"]),
    )
    assert container.identity_discovery_repository.count_visible(cutoff=cutoff) == 1

    now = datetime.now(UTC).isoformat()
    for index in range(100):
        container.database.execute(
            """
            insert into dingtalk_identity_candidate
              (id, tenant_code, external_subject_id, display_name,
               first_seen_at, last_seen_at, observation_count, revision,
               created_at, updated_at, dingtalk_enterprise_id)
            values (?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?)
            """,
            (
                f"candidate-count-{index:03d}",
                connector["enterprise"]["id"],
                f"staff-count-{index:03d}",
                f"计数候选 {index + 1}",
                now,
                now,
                now,
                now,
                connector["enterprise"]["id"],
            ),
        )
    assert (
        container.database.execute_one(
            """
            select count(*) as count
            from dingtalk_identity_candidate
            where dingtalk_enterprise_id = ?
              and id like 'candidate-count-%'
            """,
            (connector["enterprise"]["id"],),
        )
        or {}
    ).get("count") == 100
    assert container.identity_discovery_service.count_candidates() >= 100


def test_user_without_identity_manage_permission_cannot_read_candidates() -> None:
    container, connector = _container()
    _dispatch(
        container,
        _submission(
            str(connector["id"]),
            "event-api-rbac",
            sender_id="staff-api-rbac",
            sender_name="权限测试候选",
        ),
    )
    ordinary = container.identity_admin_service.create_user(
        actor_id="user_local_admin",
        username="ordinary-no-role",
        display_name="普通用户",
        email="",
        password="ordinary-user-password",
    )
    app = create_app(_settings(), container_factory=lambda _: container)

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={
                "username": ordinary["username"],
                "password": "ordinary-user-password",
            },
        )
        assert login.status_code == 200
        denied = client.get("/api/admin/dingtalk-identity-candidates")
        assert denied.status_code == 403
        assert "staff-api-rbac" not in denied.text
