from __future__ import annotations

from pathlib import Path

import pytest

from app.cli.bootstrap_file_storage_secrets import (
    FileStorageSecretBootstrapError,
    _read_secret,
    bootstrap_secret,
)


class _Repository:
    def __init__(self) -> None:
        self.existing: dict[str, object] | None = None

    def get_platform_secret_by_code(self, code: str) -> dict[str, object] | None:
        del code
        return self.existing


class _Provider:
    def __init__(self) -> None:
        self.repository = _Repository()
        self.value = ""
        self.created: list[dict[str, object]] = []

    def create_secret(self, **values: object) -> None:
        self.created.append(values)
        self.value = str(values["value"])
        self.repository.existing = {"status": "enabled"}

    def resolve(self, ref: str) -> str:
        del ref
        return self.value


def test_local_file_storage_secret_bootstrap_creates_then_preserves() -> None:
    provider = _Provider()
    assert bootstrap_secret(provider, code="minio-file-access-key", value="local-access") == (
        "created"
    )
    assert provider.created[0]["purpose"] == "local-compose-file-storage-bootstrap"
    assert bootstrap_secret(provider, code="minio-file-access-key", value="local-access") == (
        "preserved"
    )
    assert len(provider.created) == 1

    with pytest.raises(FileStorageSecretBootstrapError, match="explicit rotation"):
        bootstrap_secret(provider, code="minio-file-access-key", value="changed-access")


def test_local_file_storage_secret_file_must_be_owner_only(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.write_text("protected-value", encoding="utf-8")
    secret.chmod(0o400)
    assert _read_secret(str(secret), label="test secret") == "protected-value"

    secret.chmod(0o644)
    with pytest.raises(FileStorageSecretBootstrapError, match="owner-only"):
        _read_secret(str(secret), label="test secret")
