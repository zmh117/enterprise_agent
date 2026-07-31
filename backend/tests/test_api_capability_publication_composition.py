from __future__ import annotations

from dataclasses import replace
import json

import pytest

from app.bootstrap import build_test_container
from app.modules.api_capability.application.runtime import (
    GovernedCapabilityReleaseResolver,
)
from app.modules.api_capability.infrastructure import (
    CapabilityPublicationRepository,
)
from app.shared.config import IdentitySettings
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import test_settings as build_test_settings
from backend.tests.test_agent_profile_model_connections import (
    ADMIN_ID,
    agent_config,
    ready_connection,
)
from backend.tests.test_business_application_control_plane import (
    draft_payload,
)
from backend.tests.test_governed_api_capability_repositories import (
    ACTOR_ID,
    NOW,
    _bound_identity,
    _published_capability,
    _published_connection,
)


def _container():
    settings = replace(
        build_test_settings(),
        identity=IdentitySettings(
            enabled=True,
            published_agent_runtime_enabled=True,
            cookie_secure=False,
        ),
    )
    value = build_test_container(settings, migrate=True, seed=True)
    value.model_connection_service.dns_resolver = lambda *args, **kwargs: [
        (2, 1, 6, "", ("1.1.1.1", 443))
    ]
    value.database.execute(
        """
        insert into app_user
          (id, username, display_name, status, created_at, updated_at)
        values (?, 'composition-admin', 'Composition Admin',
                'enabled', ?, ?)
        on conflict(id) do nothing
        """,
        (ACTOR_ID, NOW, NOW),
    )
    return value


def _release(container):
    _, connection_revision = _published_connection(container.database)
    container.database.execute(
        """
        update api_authentication_profile_revision
           set config_json = ?
         where id = ?
        """,
        (
            json.dumps(
                {
                    "schema_version": 1,
                    "login": {
                        "method": "POST",
                        "relative_path": ("/project/api/project/auth/login"),
                        "email_field": "email",
                        "password_field": "password",
                    },
                    "extract": {
                        "token_path": "$.token",
                        "user_id_path": "$.user.id",
                        "display_name_path": "$.user.name",
                        "teams_path": "$.teams",
                        "team_id_field": "id",
                        "team_name_field": "name",
                    },
                    "inject": {
                        "header_name": "Ones-Auth-Token",
                        "value_prefix": "",
                    },
                },
                sort_keys=True,
            ),
            connection_revision["authentication_profile_revision_id"],
        ),
    )
    _, credential = _bound_identity(
        container.database,
        str(connection_revision["id"]),
    )
    repository, release = _published_capability(
        container.database,
        connection_revision,
        str(credential["external_identity_id"]),
    )
    return repository, release


def _publish_agent(container, release_id: str):
    model_revision = ready_connection(container)
    current = container.agent_config_service.get()
    config = agent_config(str(model_revision["id"]))
    config["api_capability_release_ids"] = [release_id]
    revision = container.agent_config_service.save_draft(
        actor_id=ADMIN_ID,
        agent_code="default-diagnostic-agent",
        expected_revision=int(current["draft"]["revision"]),
        config=config,
    )
    return container.agent_config_service.publish(
        actor_id=ADMIN_ID,
        agent_code="default-diagnostic-agent",
        revision_id=str(revision["id"]),
    )


def test_agent_publish_freezes_exact_active_release_and_catalog_metadata() -> None:
    container = _container()
    try:
        _repository, release = _release(container)
        publication = _publish_agent(container, str(release["id"]))

        envelope = publication["snapshot"]["capability_envelope"]
        assert envelope == [
            {
                "identifier": "cap__ones__work_item__search",
                "release_id": release["id"],
                "release_revision": 1,
                "capability_revision_id": release["capability_revision_id"],
                "handler_revision_id": release["handler_revision_id"],
                "schema_hash": envelope[0]["schema_hash"],
                "description": ("Search ONES work items for the current user."),
            }
        ]
        assert len(envelope[0]["schema_hash"]) == 64
        assert (
            container.agent_config_service.publication(str(publication["id"]))["config_hash"]
            == publication["config_hash"]
        )
        catalog = container.agent_config_service.catalog()["api_capabilities"]
        selected = next(item for item in catalog if item["id"] == release["id"])
        assert selected["name"] == "Search ONES work items"
        assert selected["description"]
        assert selected["release_revision"] == 1
        assert selected["status"] == "ACTIVE"
        assert selected["release_note"] == "Initial internal release"
    finally:
        container.database.close()


def test_agent_rejects_duplicate_identifier_and_publish_status_drift() -> None:
    container = _container()
    try:
        repository, release = _release(container)
        duplicate = {
            **release,
            "id": "api-capability-release-duplicate",
            "release_revision": 2,
            "publication_idempotency_key": "duplicate-release",
        }
        container.database.execute(
            """
            insert into api_capability_release
              (id, capability_id, identifier, release_revision,
               capability_revision_id, handler_revision_id,
               connection_revision_id,
               authentication_profile_revision_id, mapping_plan_id,
               verification_id, config_hash,
               publication_idempotency_key, status, release_note,
               published_by, published_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE',
                    '', ?, ?)
            """,
            (
                duplicate["id"],
                duplicate["capability_id"],
                duplicate["identifier"],
                duplicate["release_revision"],
                duplicate["capability_revision_id"],
                duplicate["handler_revision_id"],
                duplicate["connection_revision_id"],
                duplicate["authentication_profile_revision_id"],
                duplicate["mapping_plan_id"],
                duplicate["verification_id"],
                duplicate["config_hash"],
                duplicate["publication_idempotency_key"],
                ACTOR_ID,
                NOW,
            ),
        )
        publication_repository = CapabilityPublicationRepository(container.database)
        with pytest.raises(
            NonRetryableExecutionError,
            match="duplicate identifiers",
        ):
            publication_repository.prepare_agent_envelope(
                [str(release["id"]), str(duplicate["id"])]
            )

        model_revision = ready_connection(container)
        current = container.agent_config_service.get()
        config = agent_config(str(model_revision["id"]))
        config["api_capability_release_ids"] = [str(release["id"])]
        revision = container.agent_config_service.save_draft(
            actor_id=ADMIN_ID,
            agent_code="default-diagnostic-agent",
            expected_revision=int(current["draft"]["revision"]),
            config=config,
        )
        repository.set_release_status(
            str(release["id"]),
            status="DEPRECATED",
            actor_id=ACTOR_ID,
            reason="Use the next release",
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="validation failed",
        ):
            container.agent_config_service.publish(
                actor_id=ADMIN_ID,
                agent_code="default-diagnostic-agent",
                revision_id=str(revision["id"]),
            )
    finally:
        container.database.close()


def test_application_freezes_only_explicit_agent_envelope_subset() -> None:
    container = _container()
    try:
        repository, release = _release(container)
        agent_publication = _publish_agent(
            container,
            str(release["id"]),
        )
        application = container.business_application_service.create(
            actor_id=ADMIN_ID,
            code="ones-search-app",
            name="ONES Search",
            description="Search ONES",
            project_code="default",
            owner_user_id=ADMIN_ID,
        )
        payload = draft_payload()
        payload["agent_publication_id"] = agent_publication["id"]
        payload["api_capability_release_ids"] = [release["id"]]
        revision = container.business_application_service.save_draft(
            actor_id=ADMIN_ID,
            code="ones-search-app",
            expected_revision=int(application["revision"]),
            payload=payload,
        )
        publication = container.business_application_service.publish(
            actor_id=ADMIN_ID,
            code="ones-search-app",
            revision_id=str(revision["id"]),
        )
        assert publication["snapshot"]["capability_allowlist"] == [
            {
                "identifier": "cap__ones__work_item__search",
                "release_id": release["id"],
            }
        ]
        assert publication["snapshot"]["capability_agent_publication_id"] == agent_publication["id"]

        repository.set_release_status(
            str(release["id"]),
            status="DEPRECATED",
            actor_id=ACTOR_ID,
            reason="Replacement available",
        )
        historical = container.business_application_repository.get_publication(
            str(publication["id"])
        )
        assert historical["snapshot"]["capability_allowlist"][0]["release_id"] == release["id"]
        resolved = GovernedCapabilityReleaseResolver(
            repository,
            container.api_connection_service.repository,
        ).resolve(
            str(release["id"]),
            expected_identifier="cap__ones__work_item__search",
        )
        assert resolved.release["status"] == "DEPRECATED"
    finally:
        container.database.close()


def test_application_rejects_release_outside_agent_and_non_active_drift() -> None:
    container = _container()
    try:
        repository, release = _release(container)
        agent_publication = _publish_agent(
            container,
            str(release["id"]),
        )
        application = container.business_application_service.create(
            actor_id=ADMIN_ID,
            code="bounded-app",
            name="Bounded App",
            description="Bounded",
            project_code="default",
            owner_user_id=ADMIN_ID,
        )
        payload = draft_payload()
        payload["agent_publication_id"] = agent_publication["id"]
        payload["api_capability_release_ids"] = ["unowned-release"]
        with pytest.raises(
            NonRetryableExecutionError,
            match="selection is invalid",
        ):
            container.business_application_service.save_draft(
                actor_id=ADMIN_ID,
                code="bounded-app",
                expected_revision=int(application["revision"]),
                payload=payload,
            )

        payload["api_capability_release_ids"] = [release["id"]]
        revision = container.business_application_service.save_draft(
            actor_id=ADMIN_ID,
            code="bounded-app",
            expected_revision=int(application["revision"]),
            payload=payload,
        )
        repository.set_release_status(
            str(release["id"]),
            status="DISABLED",
            actor_id=ACTOR_ID,
            reason="Emergency stop",
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="validation failed",
        ):
            container.business_application_service.publish(
                actor_id=ADMIN_ID,
                code="bounded-app",
                revision_id=str(revision["id"]),
            )
        with pytest.raises(
            NonRetryableExecutionError,
            match="disabled or archived",
        ):
            GovernedCapabilityReleaseResolver(
                repository,
                container.api_connection_service.repository,
            ).resolve(
                str(release["id"]),
                expected_identifier="cap__ones__work_item__search",
            )
    finally:
        container.database.close()
