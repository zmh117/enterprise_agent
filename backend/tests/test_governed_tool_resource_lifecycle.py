from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import NonRetryableExecutionError, NotFound
from backend.tests.helpers import container


class PassingVerifier:
    def verify(
        self,
        *,
        resource: dict[str, object],
        draft: dict[str, object],
    ) -> ResourceVerificationOutcome:
        return ResourceVerificationOutcome(
            status="PASSED",
            provider_contract_version="mysql_v1",
            checks={
                "connection": "passed",
                "readonly": True,
                "password": "must-not-persist",
                "resource_code": resource["code"],
                "draft_revision": draft["draft_revision"],
            },
        )


class ExternalBoundaryVerifier(PassingVerifier):
    def verify(
        self,
        *,
        resource: dict[str, object],
        draft: dict[str, object],
    ) -> ResourceVerificationOutcome:
        assert_external_io_allowed("test.resource_verification")
        return super().verify(resource=resource, draft=draft)


class FailingVerifier:
    def verify(
        self,
        *,
        resource: dict[str, object],
        draft: dict[str, object],
    ) -> ResourceVerificationOutcome:
        del resource, draft
        return ResourceVerificationOutcome(
            status="FAILED",
            provider_contract_version="mysql_v1",
            checks={"connection": False},
            safe_error_summary="测试连接失败",
        )


def _create_resource() -> tuple[object, object, dict[str, object]]:
    runtime = container()
    service = runtime.platform_config_service.governed_resources
    runtime.platform_config_service.upsert_environment(
        {"code": "governed_env"},
        actor_id="local-user",
    )
    runtime.platform_config_service.upsert_base(
        {
            "environment_code": "governed_env",
            "code": "governed_base",
            "engine": "mysql",
        },
        actor_id="local-user",
    )
    runtime.platform_config_service.create_platform_secret(
        {
            "code": "governed_mysql_password",
            "value": "governed-resource-password",
        },
        actor_id="local-user",
    )
    created = service.create_resource(
        {
            "code": "governed_mysql",
            "name": "Governed MySQL",
            "resource_kind": "database",
            "scope_type": "base",
            "environment_code": "governed_env",
            "base_code": "governed_base",
            "provider_type": "mysql",
            "config": {
                "host": "mysql",
                "port": 3306,
                "database": "orders",
                "username": "reader",
            },
            "secret_refs": {"password_ref": ("secret://platform/governed_mysql_password")},
        },
        actor_id="local-user",
    )
    return runtime, service, created


def test_resource_publish_requires_current_passed_verification() -> None:
    runtime, service, created = _create_resource()

    with pytest.raises(
        NonRetryableExecutionError,
        match="Resource Draft is not verified",
    ):
        service.publish_draft(
            "governed_mysql",
            actor_id="local-user",
        )

    verification = service.verify_draft(
        "governed_mysql",
        actor_id="local-user",
        verifier=PassingVerifier(),
    )
    assert verification["status"] == "PASSED"
    assert verification["checks"]["password"] == "[REDACTED]"

    changed = service.save_draft(
        "governed_mysql",
        {
            "provider_type": "mysql",
            "config": {
                **created["draft"]["config"],
                "database": "orders_v2",
            },
            "secret_refs": created["draft"]["secret_refs"],
        },
        expected_revision=1,
        actor_id="local-user",
    )
    assert changed["status"] == "DRAFT"
    with pytest.raises(
        NonRetryableExecutionError,
        match="Resource Draft is not verified",
    ):
        service.publish_draft(
            "governed_mysql",
            actor_id="local-user",
        )
    runtime.database.close()


def test_external_resource_probe_runs_outside_platform_database_uow() -> None:
    runtime, service, _created = _create_resource()
    try:
        verification = service.verify_draft(
            "governed_mysql",
            actor_id="local-user",
            verifier=ExternalBoundaryVerifier(),
        )
        assert verification["status"] == "PASSED"
    finally:
        runtime.database.close()


def test_repeated_verification_updates_the_same_result_without_500() -> None:
    runtime, service, created = _create_resource()
    try:
        passed = service.verify_draft(
            "governed_mysql",
            actor_id="local-user",
            verifier=PassingVerifier(),
        )
        assert passed["status"] == "PASSED"
        assert created["draft"]["id"] == passed["draft_id"]
        assert service.repository.get_draft(str(created["resource"]["id"]))["status"] == "VERIFIED"

        failed = service.verify_draft(
            "governed_mysql",
            actor_id="local-user",
            verifier=FailingVerifier(),
        )

        assert failed["id"] == passed["id"]
        assert failed["status"] == "FAILED"
        assert failed["safe_error_summary"] == "测试连接失败"
        assert service.repository.get_draft(str(created["resource"]["id"]))["status"] == "DRAFT"
        listed = service.list_resources()[0]
        assert listed["draft_verification"]["id"] == passed["id"]
        assert listed["draft_verification"]["status"] == "FAILED"
    finally:
        runtime.database.close()


def test_concurrent_publish_has_exactly_one_resource_revision() -> None:
    runtime, service, created = _create_resource()
    try:
        service.verify_draft(
            "governed_mysql",
            actor_id="local-user",
            verifier=PassingVerifier(),
        )

        def publish() -> dict[str, object]:
            return service.publish_draft(
                "governed_mysql",
                actor_id="local-user",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(publish) for _ in range(2)]
            outcomes: list[object] = []
            for future in futures:
                try:
                    outcomes.append(future.result())
                except Exception as exc:
                    outcomes.append(exc)

        assert sum(isinstance(value, dict) for value in outcomes) == 1
        revisions = service.repository.list_revisions(str(created["resource"]["id"]))
        assert len(revisions) == 1
        assert revisions[0]["revision"] == 1
        assert service.repository.find_draft(str(created["resource"]["id"])) is None
    finally:
        runtime.database.close()


def test_published_revision_is_append_only_and_draft_is_independent() -> None:
    runtime, service, _ = _create_resource()
    service.verify_draft(
        "governed_mysql",
        actor_id="local-user",
        verifier=PassingVerifier(),
    )
    published = service.publish_draft(
        "governed_mysql",
        actor_id="local-user",
    )
    assert published["status"] == "PUBLISHED"
    assert published["revision"] == 1
    assert published["published_by"] == "local-user"
    resource_id = str(published["resource_id"])
    with pytest.raises(NotFound):
        service.repository.get_draft(resource_id)

    draft = service.create_draft_from_revision(
        "governed_mysql",
        str(published["id"]),
        actor_id="local-user",
    )
    assert draft["status"] == "DRAFT"
    changed = service.save_draft(
        "governed_mysql",
        {
            "provider_type": "mysql",
            "config": {
                **draft["config"],
                "database": "orders_next",
            },
            "secret_refs": draft["secret_refs"],
        },
        expected_revision=int(draft["draft_revision"]),
        actor_id="local-user",
    )
    original = service.repository.get_revision(str(published["id"]))
    assert original["config"]["database"] == "orders"
    assert changed["config"]["database"] == "orders_next"

    service.delete_draft(
        "governed_mysql",
        expected_revision=int(changed["draft_revision"]),
        actor_id="local-user",
    )
    with pytest.raises(NotFound):
        service.repository.get_draft(resource_id)

    disabled = service.set_revision_status(
        "governed_mysql",
        str(published["id"]),
        "disabled",
        actor_id="local-user",
    )
    assert disabled["status"] == "DISABLED"
    assert disabled["config"] == original["config"]
    assert disabled["secret_refs"] == original["secret_refs"]
    assert disabled["content_hash"] == original["content_hash"]
    assert disabled["verification_id"] == original["verification_id"]
    archived = service.set_revision_status(
        "governed_mysql",
        str(published["id"]),
        "archived",
        actor_id="local-user",
    )
    assert archived["status"] == "ARCHIVED"
    identity = service.repository.get_resource(resource_id)
    assert identity["status"] == "enabled"
    assert identity["revision"] == 1

    replacement_draft = service.create_draft_from_revision(
        "governed_mysql",
        str(archived["id"]),
        actor_id="local-user",
    )
    assert replacement_draft["status"] == "DRAFT"
    assert replacement_draft["config"] == archived["config"]
    with pytest.raises(
        NonRetryableExecutionError,
        match="cannot be modified",
    ):
        service.set_revision_status(
            "governed_mysql",
            str(published["id"]),
            "published",
            actor_id="local-user",
        )

    audit = runtime.platform_config_service.repository.list_config_audit(limit=30)
    serialized = str(audit)
    assert "governed-resource-password" not in serialized
    assert "must-not-persist" not in serialized
    runtime.database.close()


def test_resource_identity_lifecycle_is_concurrent_and_dependency_guarded() -> None:
    runtime, service, created = _create_resource()
    try:
        disabled = service.set_resource_status(
            "governed_mysql",
            "disabled",
            expected_revision=1,
            actor_id="local-user",
        )
        assert disabled["status"] == "disabled"
        assert disabled["revision"] == 2

        with pytest.raises(
            NonRetryableExecutionError,
            match="Resource Identity is not enabled",
        ):
            service.save_draft(
                "governed_mysql",
                {
                    "provider_type": "mysql",
                    "config": created["draft"]["config"],
                    "secret_refs": created["draft"]["secret_refs"],
                },
                expected_revision=1,
                actor_id="local-user",
            )

        with pytest.raises(
            NonRetryableExecutionError,
            match="Resource Identity revision conflict",
        ):
            service.set_resource_status(
                "governed_mysql",
                "enabled",
                expected_revision=1,
                actor_id="local-user",
            )

        restored = service.set_resource_status(
            "governed_mysql",
            "enabled",
            expected_revision=2,
            actor_id="local-user",
        )
        assert restored["status"] == "enabled"
        assert restored["revision"] == 3

        disabled_again = service.set_resource_status(
            "governed_mysql",
            "disabled",
            expected_revision=3,
            actor_id="local-user",
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="Resource Identity still has an active Draft",
        ):
            service.set_resource_status(
                "governed_mysql",
                "archived",
                expected_revision=int(disabled_again["revision"]),
                actor_id="local-user",
            )

        service.delete_draft(
            "governed_mysql",
            expected_revision=int(created["draft"]["draft_revision"]),
            actor_id="local-user",
        )
        archived_identity = service.set_resource_status(
            "governed_mysql",
            "archived",
            expected_revision=int(disabled_again["revision"]),
            actor_id="local-user",
        )
        assert archived_identity["status"] == "archived"
        assert archived_identity["revision"] == 5

        with pytest.raises(
            NonRetryableExecutionError,
            match="Resource Identity status transition is invalid",
        ):
            service.set_resource_status(
                "governed_mysql",
                "enabled",
                expected_revision=5,
                actor_id="local-user",
            )
    finally:
        runtime.database.close()


def test_resource_identity_archive_requires_no_published_revision() -> None:
    runtime, service, _created = _create_resource()
    try:
        service.verify_draft(
            "governed_mysql",
            actor_id="local-user",
            verifier=PassingVerifier(),
        )
        published = service.publish_draft(
            "governed_mysql",
            actor_id="local-user",
        )
        disabled_identity = service.set_resource_status(
            "governed_mysql",
            "disabled",
            expected_revision=1,
            actor_id="local-user",
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="Resource Identity still has a published Revision",
        ):
            service.set_resource_status(
                "governed_mysql",
                "archived",
                expected_revision=int(disabled_identity["revision"]),
                actor_id="local-user",
            )

        service.set_revision_status(
            "governed_mysql",
            str(published["id"]),
            "disabled",
            actor_id="local-user",
        )
        service.set_revision_status(
            "governed_mysql",
            str(published["id"]),
            "archived",
            actor_id="local-user",
        )
        archived_identity = service.set_resource_status(
            "governed_mysql",
            "archived",
            expected_revision=int(disabled_identity["revision"]),
            actor_id="local-user",
        )
        assert archived_identity["status"] == "archived"
    finally:
        runtime.database.close()
