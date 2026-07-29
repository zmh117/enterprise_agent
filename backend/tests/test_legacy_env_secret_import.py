from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.platform_config.application.legacy_env_import import (
    LegacyEnvSecretImportService,
)
from app.modules.platform_config.infrastructure.repository import now_iso
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container, test_settings as make_settings


def _seed_legacy_env_references(runtime: object) -> None:
    repository = runtime.platform_config_service.repository
    database = runtime.database
    env_ref = "env:LEGACY_SHARED_SECRET"
    repository.upsert_secret_reference(
        code="legacy_shared",
        provider="env",
        ref=env_ref,
        purpose="legacy-test",
    )
    repository.upsert_environment(code="legacy")
    repository.upsert_base(
        environment_code="legacy",
        code="main",
        engine="mysql",
    )
    repository.upsert_resource_binding(
        code="legacy_main_database",
        scope_type="base",
        environment_code="legacy",
        base_code="main",
        resource_kind="database",
        engine="mysql",
        config={
            "host": "mysql",
            "port": 3306,
            "database": "legacy",
            "username": "reader",
        },
        secret_refs={"password": env_ref},
    )
    repository.upsert_runtime_config_definition(
        key="LEGACY_RUNTIME_SECRET",
        value_type="secret_ref",
        sensitive=True,
    )
    repository.upsert_runtime_config_value(
        key="LEGACY_RUNTIME_SECRET",
        secret_ref=env_ref,
    )
    timestamp = now_iso()
    database.execute(
        """
        insert into integration_connector
          (id, connector_type, name, secret_ref, endpoint_ref, metadata,
           created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "connector-legacy-env-import",
            "webhook",
            "Legacy env import connector",
            env_ref,
            env_ref,
            json.dumps(
                {
                    "client_id_ref": env_ref,
                    "nested": {"token_ref": env_ref},
                }
            ),
            timestamp,
            timestamp,
        ),
    )


def _target_reference_count(report: dict[str, object]) -> int:
    references = report["references"]
    assert isinstance(references, list)
    return sum(
        1
        for item in references
        if isinstance(item, dict)
        and item.get("env_ref") == "env:LEGACY_SHARED_SECRET"
    )


def test_legacy_env_import_dry_run_reads_no_value_and_apply_reads_once() -> None:
    runtime = container()
    _seed_legacy_env_references(runtime)
    reads: list[str] = []

    def read_environment(name: str) -> str | None:
        reads.append(name)
        return "legacy-value-never-returned"

    migration = LegacyEnvSecretImportService(
        runtime.platform_config_service.repository,
        runtime.platform_config_service.secret_provider,
        read_environment=read_environment,
    )
    preview = migration.import_reference(
        env_ref="env:LEGACY_SHARED_SECRET",
        code="legacy_shared_secret",
        actor_id="local-user",
        dry_run=True,
    )

    assert preview["count"] == 7
    assert reads == []
    assert "legacy-value-never-returned" not in str(preview)

    with runtime.database.unit_of_work():
        applied = migration.import_reference(
            env_ref="env:LEGACY_SHARED_SECRET",
            code="legacy_shared_secret",
            actor_id="local-user",
            correlation_id="legacy-import-test",
            dry_run=False,
            expected_digest=preview["digest"],
        )

    assert applied["rewritten"] == 7
    assert reads == ["LEGACY_SHARED_SECRET"]
    assert _target_reference_count(migration.report()) == 0
    secret = runtime.platform_config_service.repository.get_platform_secret_by_code(
        "legacy_shared_secret"
    )
    assert secret is not None
    assert secret["metadata"] == {
        "legacy_env_ref": "env:LEGACY_SHARED_SECRET"
    }
    assert (
        runtime.platform_config_service.secret_provider.resolve(secret["ref"])
        == "legacy-value-never-returned"
    )
    persisted_text = str(
        runtime.database.execute(
            """
            select ref from platform_secret_reference
            union all select secret_ref from platform_runtime_config_value
            union all select secret_refs_json from platform_resource_binding
            union all select secret_ref from integration_connector
            union all select endpoint_ref from integration_connector
            union all select metadata from integration_connector
            """
        )
    )
    assert "env:LEGACY_SHARED_SECRET" not in persisted_text
    assert "legacy-value-never-returned" not in persisted_text
    audit_text = str(
        runtime.platform_config_service.repository.list_config_audit(limit=50)
    )
    assert "legacy-value-never-returned" not in audit_text
    assert "legacy_env_secret_import" in audit_text

    with runtime.database.unit_of_work():
        repeated = migration.import_reference(
            env_ref="env:LEGACY_SHARED_SECRET",
            code="legacy_shared_secret",
            actor_id="local-user",
            dry_run=False,
            expected_digest=preview["digest"],
        )
    assert repeated["already_applied"] is True
    assert repeated["rewritten"] == 0
    assert reads == ["LEGACY_SHARED_SECRET"]


def test_legacy_env_import_missing_value_rolls_back_without_rewrite() -> None:
    runtime = container()
    _seed_legacy_env_references(runtime)
    migration = LegacyEnvSecretImportService(
        runtime.platform_config_service.repository,
        runtime.platform_config_service.secret_provider,
        read_environment=lambda _: None,
    )
    preview = migration.import_reference(
        env_ref="env:LEGACY_SHARED_SECRET",
        code="missing_legacy_secret",
        actor_id="local-user",
        dry_run=True,
    )

    with pytest.raises(NonRetryableExecutionError):
        with runtime.database.unit_of_work():
            migration.import_reference(
                env_ref="env:LEGACY_SHARED_SECRET",
                code="missing_legacy_secret",
                actor_id="local-user",
                dry_run=False,
                expected_digest=preview["digest"],
            )

    assert _target_reference_count(migration.report()) == 7
    assert (
        runtime.platform_config_service.repository.get_platform_secret_by_code(
            "missing_legacy_secret"
        )
        is None
    )


def test_legacy_env_import_api_is_two_step_and_never_returns_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = container()
    _seed_legacy_env_references(runtime)
    plaintext = "api-import-value-never-returned"
    monkeypatch.setenv("LEGACY_SHARED_SECRET", plaintext)
    app = create_app(make_settings(), container_factory=lambda _: runtime)

    with TestClient(app) as client:
        report = client.get("/api/platform/secrets/legacy-env/report")
        dry_run = client.post(
            "/api/platform/secrets/legacy-env/import",
            json={
                "env_ref": "env:LEGACY_SHARED_SECRET",
                "code": "legacy_api_import",
                "dry_run": True,
            },
            headers={"x-admin-user-id": "local-user"},
        )
        apply = client.post(
            "/api/platform/secrets/legacy-env/import",
            json={
                "env_ref": "env:LEGACY_SHARED_SECRET",
                "code": "legacy_api_import",
                "dry_run": False,
                "expected_digest": dry_run.json()["result"]["digest"],
            },
            headers={
                "x-admin-user-id": "local-user",
                "x-correlation-id": "legacy-api-import",
            },
        )

    assert report.status_code == 200
    assert dry_run.status_code == 200
    assert apply.status_code == 200
    combined = f"{report.text}\n{dry_run.text}\n{apply.text}"
    assert plaintext not in combined
    assert apply.json()["result"]["rewritten"] == 7
