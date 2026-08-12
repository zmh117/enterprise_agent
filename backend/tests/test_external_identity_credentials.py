from __future__ import annotations

import json

import pytest

from app.bootstrap import build_test_container
from app.modules.identity.infrastructure.external_identity_credentials import (
    CredentialSecretBundle,
    EncryptedCredentialValue,
    ExternalIdentityCredentialCipher,
    ExternalIdentityCredentialRepository,
)
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import test_settings as settings_for_test


MASTER_KEY = "external-identity-credential-test-master-key"


def test_credential_cipher_binds_context_purpose_key_and_integrity() -> None:
    cipher = ExternalIdentityCredentialCipher(MASTER_KEY)
    encrypted = cipher.encrypt_login_material(
        email="identity@example.test",
        password="not-a-real-password",
        context="challenge",
        context_id="challenge-1",
    )

    assert cipher.decrypt_login_material(
        encrypted,
        context="challenge",
        context_id="challenge-1",
    ) == ("identity@example.test", "not-a-real-password")
    assert "identity@example.test" not in repr(encrypted)
    assert "not-a-real-password" not in repr(encrypted)

    failures = (
        lambda: cipher.decrypt_login_material(
            encrypted,
            context="credential",
            context_id="challenge-1",
        ),
        lambda: cipher.decrypt_login_material(
            encrypted,
            context="challenge",
            context_id="challenge-2",
        ),
        lambda: ExternalIdentityCredentialCipher("another-test-master-key").decrypt_login_material(
            encrypted,
            context="challenge",
            context_id="challenge-1",
        ),
        lambda: cipher.decrypt_login_material(
            EncryptedCredentialValue(
                ciphertext=(
                    ("A" if encrypted.ciphertext[0] != "A" else "B") + encrypted.ciphertext[1:]
                ),
                nonce=encrypted.nonce,
                key_id=encrypted.key_id,
                algorithm=encrypted.algorithm,
            ),
            context="challenge",
            context_id="challenge-1",
        ),
        lambda: cipher.encrypt(
            "",
            context="challenge",
            context_id="challenge-1",
            purpose="provider-token",
        ),
    )
    for fail in failures:
        with pytest.raises(
            NonRetryableExecutionError,
            match="cryptographic operation failed",
        ):
            fail()


def test_external_credential_repository_lifecycle_and_safe_projection() -> None:
    runtime = build_test_container(settings_for_test(), migrate=True, seed=True)
    user = runtime.identity_repository.create_user(
        username="credential-owner",
        display_name="Credential Owner",
    )
    identity = runtime.identity_repository.bind_external_identity(
        user_id=str(user["id"]),
        provider="ones",
        tenant_code="default",
        external_subject_id="ONES-CREDENTIAL-OWNER",
        connector_id="",
        display_name="ONES Credential Owner",
        metadata={"default_team_id": "TEAM-CREDENTIAL"},
    )
    repository = ExternalIdentityCredentialRepository(
        runtime.database,
        ExternalIdentityCredentialCipher(MASTER_KEY),
    )
    secrets = CredentialSecretBundle(
        email="credential.owner@example.test",
        password="not-a-real-password",
        token="not-a-real-token",
    )

    created = repository.upsert_active(
        external_identity_id=str(identity["id"]),
        provider="ones",
        secrets=secrets,
        verified_at="2026-08-12T00:00:00+00:00",
    )
    row = repository.get_by_identity(str(identity["id"]))

    assert created == {
        "configured": True,
        "status": "ACTIVE",
        "revision": 1,
        "verified_at": "2026-08-12T00:00:00+00:00",
        "token_refreshed_at": None,
        "last_used_at": None,
        "reauth_required_at": None,
        "disabled_at": None,
        "unbound_at": None,
    }
    assert row is not None
    persisted = json.dumps(row, ensure_ascii=False)
    for forbidden in (
        "credential.owner@example.test",
        "not-a-real-password",
        "not-a-real-token",
    ):
        assert forbidden not in persisted
    resolved = repository.resolve_active(str(row["id"]))
    assert resolved.secrets == secrets
    assert "not-a-real-password" not in repr(resolved)
    assert "not-a-real-token" not in repr(resolved)

    rotated = repository.rotate_token(
        credential_id=str(row["id"]),
        expected_revision=1,
        token="rotated-test-token",
    )
    assert rotated["revision"] == 2
    assert repository.resolve_active(str(row["id"])).secrets.token == "rotated-test-token"
    with pytest.raises(
        NonRetryableExecutionError,
        match="credential state is invalid",
    ):
        repository.rotate_token(
            credential_id=str(row["id"]),
            expected_revision=1,
            token="stale-test-token",
        )

    reauth = repository.mark_reauth_required(
        credential_id=str(row["id"]),
        expected_revision=2,
        error_code="ones_login_rejected",
    )
    assert reauth["status"] == "REAUTH_REQUIRED"
    assert reauth["revision"] == 3
    with pytest.raises(NonRetryableExecutionError):
        repository.resolve_active(str(row["id"]))

    reverified = repository.upsert_active(
        external_identity_id=str(identity["id"]),
        provider="ones",
        secrets=secrets,
        verified_at="2026-08-12T01:00:00+00:00",
    )
    assert reverified["status"] == "ACTIVE"
    assert reverified["revision"] == 4
    disabled = repository.disable(
        credential_id=str(row["id"]),
        expected_revision=4,
    )
    assert disabled["status"] == "DISABLED"
    assert disabled["revision"] == 5
    unbound = repository.unbind(
        credential_id=str(row["id"]),
        expected_revision=5,
    )
    assert unbound["status"] == "UNBOUND"
    assert unbound["revision"] == 6
    assert unbound["configured"] is False
    cleared = repository.get_by_id(str(row["id"]))
    for column in (
        "login_material_ciphertext",
        "login_material_nonce",
        "token_ciphertext",
        "token_nonce",
    ):
        assert cleared[column] is None
