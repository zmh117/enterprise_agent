from __future__ import annotations

import pytest

from app.shared.config import load_settings


LOCAL_ENVIRONMENTS = ("local", "test", "testing", "development")


@pytest.mark.parametrize("environment", LOCAL_ENVIRONMENTS)
def test_local_environments_allow_repository_minio_defaults(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
) -> None:
    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.delenv("S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("S3_SECRET_KEY", raising=False)

    settings = load_settings()

    assert settings.environment == environment
    assert settings.object_storage.access_key
    assert settings.object_storage.secret_key


@pytest.mark.parametrize(
    ("access_key", "secret_key"),
    (
        (None, None),
        ("", ""),
        ("enterprise_agent", "explicit-non-default-secret"),
        ("explicit-non-default-access", "enterprise_agent_change_me"),
    ),
)
def test_non_local_environment_rejects_missing_or_repository_default_credentials(
    monkeypatch: pytest.MonkeyPatch,
    access_key: str | None,
    secret_key: str | None,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    for name, value in (("S3_ACCESS_KEY", access_key), ("S3_SECRET_KEY", secret_key)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)

    with pytest.raises(
        ValueError,
        match="object_storage_credentials_required_for_non_local_environment",
    ) as error:
        load_settings()

    message = str(error.value)
    assert "enterprise_agent_change_me" not in message
    assert "explicit-non-default-secret" not in message


def test_non_local_environment_accepts_explicit_non_default_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("S3_ACCESS_KEY", "production-object-storage-access")
    monkeypatch.setenv("S3_SECRET_KEY", "production-object-storage-secret")

    settings = load_settings()

    assert settings.environment == "production"
