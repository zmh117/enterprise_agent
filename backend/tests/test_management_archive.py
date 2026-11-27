import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_agent_profile_creation import _creation_payload
from backend.tests.test_unified_identity_rbac import (
    csrf_headers,
    login,
    unified_container,
    unified_settings,
)


@pytest.fixture()
def management():
    runtime = unified_container()
    with TestClient(create_app(unified_settings(), container_factory=lambda _: runtime)) as client:
        yield runtime, client, csrf_headers(login(client))
    runtime.database.close()


def test_user_archive_checks_owners_and_hides_from_counts(management):
    runtime, client, headers = management
    repo = runtime.identity_repository
    person = repo.create_user(username="archive-person", display_name="归档测试")
    user_path = f"/api/admin/users/{person['id']}"
    form = {"display_name": person["display_name"], "email": "", "expected_revision": 1}
    assert (
        client.put(user_path, json=form | {"status": "archived"}, headers=headers).status_code
        == 400
    )
    stopped = client.put(user_path, json=form | {"status": "disabled"}, headers=headers).json()[
        "user"
    ]
    app = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="archive-owner",
        name="归档测试应用",
        project_code="default",
        description="",
        owner_user_id=person["id"],
    )
    archive = form | {"status": "archived", "expected_revision": stopped["revision"]}
    assert client.put(user_path, json=archive, headers=headers).status_code == 400
    runtime.business_application_service.update_metadata(
        actor_id="user_local_admin",
        code=app["code"],
        expected_revision=app["revision"],
        name=app["name"],
        description="",
        project_code="default",
        owner_user_id=person["id"],
        status="archived",
    )
    archived = client.put(user_path, json=archive, headers=headers).json()["user"]
    assert archived["status"] == "archived"
    assert client.get("/api/admin/users?search=archive-person").json()["pagination"]["total"] == 0
    assert (
        client.get("/api/admin/users?search=archive-person&status=archived").json()["users"][0][
            "id"
        ]
        == person["id"]
    )
    assert (
        client.put(
            user_path,
            json=form | {"status": "enabled", "expected_revision": archived["revision"]},
            headers=headers,
        ).status_code
        == 400
    )
    assert not runtime.business_application_service.repository.list_applications(
        search="archive-owner"
    )
    assert (
        runtime.business_application_service.repository.list_applications(
            search="archive-owner", include_archived=True
        )[0]["status"]
        == "archived"
    )


def test_disabled_custom_role_archive_preserves_membership_history(management):
    runtime, client, headers = management
    path = "/api/admin/authorization/roles"
    role = client.post(
        path,
        headers=headers,
        json={"code": "archive-role", "name": "归档测试", "description": "", "purpose_tags": []},
    ).json()["role"]
    form = {
        "name": role["name"],
        "description": "",
        "purpose_tags": [],
        "confirmed": True,
        "reason": "归档测试",
    }

    def status(value, revision):
        return client.put(
            f"{path}/{role['id']}/metadata",
            headers=headers,
            json=form | {"status": value, "expected_revision": revision},
        )

    person = runtime.identity_repository.create_user(
        username="archive-member", display_name="角色成员"
    )
    member = runtime.identity_repository.assign_role(
        user_id=person["id"],
        role_id=role["id"],
        assigned_by="user_local_admin",
        expected_revision=0,
    )
    stopped = status("disabled", role["metadata_revision"]).json()["role"]
    assert status("archived", stopped["metadata_revision"]).status_code == 400
    runtime.identity_repository.remove_role(
        user_id=person["id"], role_id=role["id"], expected_revision=member["revision"]
    )
    archived = status("archived", stopped["metadata_revision"]).json()["role"]
    assert archived["status"] == "archived"
    assert client.get(path, params={"search": "archive-role"}).json()["page"]["total"] == 0
    assert (
        client.get(path, params={"search": "archive-role", "status": "archived"}).json()["page"][
            "total"
        ]
        == 1
    )
    assert status("enabled", archived["metadata_revision"]).status_code == 400


def test_agent_archive_preserves_draft_and_requires_current_revision(management):
    runtime, client, headers = management
    path = "/api/admin/agents"
    agent = runtime.agent_config_service.create_agent(
        actor_id="user_local_admin", **_creation_payload()
    )
    code = agent["definition"]["code"]
    url = f"{path}/{code}/lifecycle/archived"
    version = agent["definition"]["revision"]
    assert (
        client.post(url, headers=headers, params={"expected_revision": version + 1}).status_code
        == 409
    )
    assert (
        client.post(url, headers=headers, params={"expected_revision": version}).status_code == 200
    )
    assert code not in {item["code"] for item in client.get(path).json()["agents"]}
    assert [
        item["code"] for item in client.get(path, params={"archived": True}).json()["agents"]
    ] == [code]
    retained = client.get(f"{path}/{code}").json()["agent"]
    assert retained["draft"]["id"] == agent["draft"]["id"]
    assert not any(retained["permissions"].values())
    assert (
        client.post(
            f"{path}/{code}/lifecycle/enabled",
            headers=headers,
            params={"expected_revision": version + 1},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"{path}/default-diagnostic-agent/lifecycle/archived",
            headers=headers,
            params={"expected_revision": 1},
        ).status_code
        == 400
    )


def test_archived_webhook_excluded_from_management_and_writes(management):
    runtime, client, headers = management
    path = "/api/admin/managed-channels"
    definition = client.post(
        f"{path}/webhooks",
        headers=headers,
        json={"code": "archive-hook", "name": "归档测试", "trigger_type": "generic"},
    ).json()["webhook"]["definition"]
    archive = f"{path}/{definition['connector_id']}/archive?webhook_code=archive-hook"
    assert (
        client.post(
            archive, headers=headers, json={"expected_revision": definition["revision"]}
        ).status_code
        == 200
    )
    assert "archive-hook" not in {item.get("code") for item in client.get(path).json()["items"]}
    (history,) = client.get(path, params={"archived": True}).json()["items"]
    assert history["code"] == "archive-hook" and history["archived"] and not history["enabled"]
    with pytest.raises(NonRetryableExecutionError, match="read-only"):
        runtime.webhook_trigger_service.update_definition(
            actor_id="user_local_admin",
            code="archive-hook",
            status="enabled",
            name=definition["name"],
            connector_id=definition["connector_id"],
            expected_revision=history["revision"],
        )


def test_secret_archive_keeps_public_history_and_rejects_rotation(management):
    runtime, _, _ = management
    service = runtime.platform_config_service
    actor = "user_local_admin"
    code = "archive_secret"
    service.create_platform_secret(
        {"code": code, "value": "synthetic-archive-fixture"}, actor_id=actor
    )
    disabled = service.disable_platform_secret(code, actor_id=actor)
    archived = service.archive_platform_secret(
        code, expected_revision=disabled["revision"], actor_id=actor
    )
    assert archived["status"] == "archived" and not archived["configured"]
    assert code not in {item["code"] for item in service.list_platform_secrets()}
    assert [item["code"] for item in service.list_platform_secrets(archived=True)] == [code]
    with pytest.raises(NonRetryableExecutionError, match="read-only"):
        service.rotate_platform_secret(
            code, {"value": "synthetic-rejected-rotation"}, actor_id=actor
        )


def test_published_agent_with_new_draft_needs_explicit_disable(management):
    runtime, _, _ = management
    agents = runtime.agent_config_service
    # Publish a synthetic profile without contacting a model provider.
    agents.model_connection_service = None
    actor = "user_local_admin"
    created = agents.create_agent(actor_id=actor, **_creation_payload())
    code = created["definition"]["code"]
    agents.publish(actor_id=actor, agent_code=code, revision_id=created["draft"]["id"])
    draft = agents.save_draft(
        actor_id=actor,
        agent_code=code,
        expected_revision=created["draft"]["revision"],
        config=created["draft"]["config"],
    )
    revision = agents.repository.get_definition(code)["revision"]
    with pytest.raises(NonRetryableExecutionError, match="cannot be archived"):
        agents.set_status(
            agent_code=code, actor_id=actor, status="archived", expected_revision=revision
        )
    agents.set_status(
        agent_code=code, actor_id=actor, status="disabled", expected_revision=revision
    )
    agents.set_status(
        agent_code=code, actor_id=actor, status="archived", expected_revision=revision + 1
    )
    retained = agents.get(code)
    assert retained["draft"]["id"] == draft["id"]
    assert retained["current_publication"]["revision"] == 1
