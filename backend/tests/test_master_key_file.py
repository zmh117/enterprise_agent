from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path

import pytest

from app.shared.config import Settings, load_settings
from app.shared.master_key import (
    MASTER_KEY_PREFIX,
    MasterKeyConfigurationError,
    load_master_key_file,
    load_master_key_settings,
)


def _write_key(path: Path, *, mode: int = 0o400) -> str:
    encoded = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
    path.write_text(f"{MASTER_KEY_PREFIX}{encoded}\n", encoding="ascii")
    path.chmod(mode)
    return encoded


def test_master_key_file_requires_versioned_canonical_owner_only_format(
    tmp_path: Path,
) -> None:
    path = tmp_path / "master-key"
    encoded = _write_key(path)

    assert load_master_key_file(str(path), required=True) == encoded

    path.chmod(0o440)
    with pytest.raises(
        MasterKeyConfigurationError,
        match="owner-only",
    ):
        load_master_key_file(str(path), required=True)


@pytest.mark.parametrize(
    "content",
    (
        "plain-text-key\n",
        f"{MASTER_KEY_PREFIX}not-base64!\n",
        f"{MASTER_KEY_PREFIX}YWJj\n",
        f"{MASTER_KEY_PREFIX}{base64.urlsafe_b64encode(bytes(32)).decode()}\n",
        f"{MASTER_KEY_PREFIX}{base64.urlsafe_b64encode(bytes(32)).decode().rstrip('=')}\nsecond\n",
    ),
)
def test_master_key_file_rejects_unsafe_or_noncanonical_content(
    tmp_path: Path,
    content: str,
) -> None:
    path = tmp_path / "invalid-key"
    path.write_text(content, encoding="ascii")
    path.chmod(0o400)

    with pytest.raises(MasterKeyConfigurationError):
        load_master_key_file(str(path), required=True)


def test_non_test_loaded_settings_require_file_and_ignore_inline_fallback(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-key"
    settings = Settings(
        app_config_master_key="legacy-inline-must-not-be-used",
        app_config_master_key_file=str(missing),
        master_key_file_required=True,
    )

    with pytest.raises(
        MasterKeyConfigurationError,
        match="not found",
    ):
        load_master_key_settings(settings)

    path = tmp_path / "valid-key"
    encoded = _write_key(path)
    loaded = load_master_key_settings(replace(settings, app_config_master_key_file=str(path)))
    assert loaded.app_config_master_key == encoded
    assert encoded not in repr(loaded)
    assert "legacy-inline-must-not-be-used" not in repr(loaded)


def test_legacy_inline_environment_variable_cannot_satisfy_master_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_CONFIG_MASTER_KEY", "legacy-inline-value")
    monkeypatch.delenv("APP_CONFIG_MASTER_KEY_FILE", raising=False)

    settings = load_settings()

    assert settings.app_config_master_key == ""
    assert settings.app_config_master_key_file == ""
    with pytest.raises(
        MasterKeyConfigurationError,
        match="APP_CONFIG_MASTER_KEY_FILE is required",
    ):
        load_master_key_settings(settings)
