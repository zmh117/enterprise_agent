from __future__ import annotations

import pytest

from app.shared.config import load_settings


def test_application_settings_only_expose_governed_file_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FILE_STORAGE_ENDPOINT_URL", "https://files.example.test")
    monkeypatch.setenv("FILE_STORAGE_BUCKET", "managed-files")
    monkeypatch.setenv("FILE_STORAGE_ACCESS_KEY_REF", "secret://platform/file-storage-access")
    monkeypatch.setenv("FILE_STORAGE_SECRET_KEY_REF", "secret://platform/file-storage-secret")

    settings = load_settings()

    assert not hasattr(settings, "object_storage")
    assert settings.file_service.endpoint_url == "https://files.example.test"
    assert settings.file_service.bucket == "managed-files"
    assert settings.file_service.access_key_ref == "secret://platform/file-storage-access"
    assert settings.file_service.secret_key_ref == "secret://platform/file-storage-secret"
