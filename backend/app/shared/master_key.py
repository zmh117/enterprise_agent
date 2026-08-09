from __future__ import annotations

import base64
from dataclasses import replace
import os
from pathlib import Path
import stat

from app.shared.config import Settings


MASTER_KEY_PREFIX = "EA_MASTER_KEY_V1:"
MASTER_KEY_BYTES = 32
MAX_MASTER_KEY_FILE_BYTES = 256


class MasterKeyConfigurationError(RuntimeError):
    """Safe startup failure for invalid external Master Key configuration."""


def load_master_key_settings(settings: Settings) -> Settings:
    """Load runtime key material once from the configured read-only file.

    Programmatically supplied key material is reserved for isolated tests.
    Settings created by ``load_settings`` set ``master_key_file_required`` and
    therefore cannot use the inline test path.
    """
    if settings.master_key_file_required:
        material = load_master_key_file(
            settings.app_config_master_key_file,
            required=True,
        )
        return replace(settings, app_config_master_key=material)
    if settings.app_config_master_key_file:
        material = load_master_key_file(
            settings.app_config_master_key_file,
            required=True,
        )
        return replace(settings, app_config_master_key=material)
    return settings


def load_master_key_file(path: str, *, required: bool) -> str:
    configured = str(path or "").strip()
    if not configured:
        if required:
            raise MasterKeyConfigurationError("APP_CONFIG_MASTER_KEY_FILE is required")
        return ""
    key_path = Path(configured)
    try:
        metadata = key_path.lstat()
    except FileNotFoundError as exc:
        raise MasterKeyConfigurationError("Configured Master Key file was not found") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise MasterKeyConfigurationError("Master Key path must be a regular non-symlink file")
    mode = stat.S_IMODE(metadata.st_mode)
    if _is_container_secret(key_path):
        if mode & 0o222 and not _is_read_only_filesystem(key_path):
            raise MasterKeyConfigurationError("Container Master Key file must be read-only")
    elif mode & 0o077:
        raise MasterKeyConfigurationError("Master Key file permissions must be owner-only")
    if metadata.st_size > MAX_MASTER_KEY_FILE_BYTES:
        raise MasterKeyConfigurationError("Master Key file is too large")
    try:
        content = key_path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise MasterKeyConfigurationError("Master Key file is unreadable") from exc
    if content.endswith("\n"):
        content = content[:-1]
    if "\n" in content or "\r" in content:
        raise MasterKeyConfigurationError("Master Key file must contain exactly one line")
    if not content.startswith(MASTER_KEY_PREFIX):
        raise MasterKeyConfigurationError("Master Key file format version is invalid")
    encoded = content.removeprefix(MASTER_KEY_PREFIX)
    try:
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except Exception as exc:
        raise MasterKeyConfigurationError("Master Key file payload is invalid") from exc
    if len(decoded) != MASTER_KEY_BYTES:
        raise MasterKeyConfigurationError("Master Key file must contain 32 bytes")
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if encoded != canonical:
        raise MasterKeyConfigurationError("Master Key file payload is not canonical base64url")
    return canonical


def _is_container_secret(path: Path) -> bool:
    try:
        return path.is_relative_to(Path("/run/secrets"))
    except ValueError:
        return False


def _is_read_only_filesystem(path: Path) -> bool:
    try:
        return bool(os.statvfs(path).f_flag & os.ST_RDONLY)
    except OSError:
        return False
