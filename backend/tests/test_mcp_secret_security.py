from __future__ import annotations

import json

import pytest

from app.bootstrap import build_test_container
from app.shared.config import IdentitySettings, Settings
from app.shared.exceptions import NonRetryableExecutionError


def _container():
    return build_test_container(
        Settings(
            database_dsn="sqlite:///:memory:",
            app_config_master_key="test-only-master-key",
            environment="test",
            identity=IdentitySettings(enabled=True),
        ),
        migrate=True,
        seed=True,
    )


def test_secret_plaintext_is_confined_to_crypto_boundary_and_rotation_is_atomic() -> None:
    runtime = _container()
    actor = "user_local_admin"
    plaintext = "secret-sentinel-create-9wJ2!"
    rotated = "secret-sentinel-rotate-4kP7!"

    created = runtime.platform_config_service.create_platform_secret(
        {"code": "mcp_security_test", "purpose": "test", "value": plaintext},
        actor_id=actor,
        correlation_id="corr-secret-create",
    )
    assert created["secret_ref"] == "secret://platform/mcp_security_test"
    assert created["configured"] is True
    assert set(created).isdisjoint({"value", "ciphertext", "nonce", "key_id"})
    assert (
        runtime.platform_config_service.secret_provider.resolve(created["secret_ref"]) == plaintext
    )

    rows = runtime.database.execute(
        "select ciphertext, nonce, key_id from platform_secret_version where secret_id = ?",
        (created["id"],),
    )
    assert len(rows) == 1
    assert plaintext not in json.dumps(rows)
    public_and_audit = json.dumps(
        {
            "list": runtime.platform_config_service.list_platform_secrets(),
            "audit": runtime.platform_config_service.repository.list_config_audit(),
        },
        ensure_ascii=False,
    )
    assert plaintext not in public_and_audit
    assert rows[0]["ciphertext"] not in public_and_audit
    assert rows[0]["nonce"] not in public_and_audit
    assert rows[0]["key_id"] not in public_and_audit

    with pytest.raises(NonRetryableExecutionError) as conflict:
        runtime.platform_config_service.rotate_platform_secret(
            "mcp_security_test",
            {"expected_revision": created["revision"] - 1, "value": rotated},
            actor_id=actor,
        )
    assert conflict.value.error_code == "revision_conflict"
    assert (
        runtime.database.execute_one(
            "select count(*) as count from platform_secret_version where secret_id = ?",
            (created["id"],),
        )["count"]
        == 1
    )

    updated = runtime.platform_config_service.rotate_platform_secret(
        "mcp_security_test",
        {"expected_revision": created["revision"], "value": rotated},
        actor_id=actor,
        correlation_id="corr-secret-rotate",
    )
    assert updated["active_version"] == 2
    assert runtime.platform_config_service.secret_provider.resolve(updated["secret_ref"]) == rotated

    disabled = runtime.platform_config_service.disable_platform_secret(
        "mcp_security_test",
        actor_id=actor,
        expected_revision=updated["revision"],
    )
    assert disabled["status"] == "disabled"
    with pytest.raises(NonRetryableExecutionError):
        runtime.platform_config_service.secret_provider.resolve(disabled["secret_ref"])
