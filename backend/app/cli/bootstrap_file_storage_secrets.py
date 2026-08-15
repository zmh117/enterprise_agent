from __future__ import annotations

import hmac
import os
import stat
from pathlib import Path

from app.modules.platform_config.application.secrets import EncryptedDbSecretProvider
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.master_key import load_master_key_settings
from app.shared.migrations import SchemaHeadValidator


LOCAL_ENVIRONMENTS = frozenset({"local", "test", "testing", "development"})
ACCESS_KEY_CODE = "minio-file-access-key"
SECRET_KEY_CODE = "minio-file-secret-key"
DEFAULT_ACCESS_KEY_FILE = "/run/secrets/file_storage_bootstrap_access_key"
DEFAULT_SECRET_KEY_FILE = "/run/secrets/file_storage_bootstrap_secret_key"


class FileStorageSecretBootstrapError(RuntimeError):
    """Safe local bootstrap failure that never contains credential material."""


def _enabled() -> bool:
    return os.getenv("FILE_STORAGE_SECRET_BOOTSTRAP_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _read_secret(path: str, *, label: str) -> str:
    file_path = Path(path)
    try:
        metadata = file_path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise FileStorageSecretBootstrapError(f"{label} must be a regular file")
        if not 3 <= metadata.st_size <= 4096:
            raise FileStorageSecretBootstrapError(f"{label} size is invalid")
        mode = stat.S_IMODE(metadata.st_mode)
        if file_path.is_relative_to(Path("/run/secrets")):
            if mode & 0o222:
                raise FileStorageSecretBootstrapError(f"{label} must be read-only")
        elif mode & 0o077:
            raise FileStorageSecretBootstrapError(f"{label} must be owner-only")
        value = file_path.read_text(encoding="utf-8")
    except FileStorageSecretBootstrapError:
        raise
    except (OSError, UnicodeError) as exc:
        raise FileStorageSecretBootstrapError(f"{label} is unavailable") from exc
    if value.endswith("\n"):
        value = value[:-1]
    if not value or "\n" in value or "\r" in value or "\x00" in value:
        raise FileStorageSecretBootstrapError(f"{label} format is invalid")
    return value


def bootstrap_secret(
    provider: EncryptedDbSecretProvider,
    *,
    code: str,
    value: str,
) -> str:
    existing = provider.repository.get_platform_secret_by_code(code)
    if existing is None:
        provider.create_secret(
            code=code,
            value=value,
            purpose="local-compose-file-storage-bootstrap",
            actor_id="local-compose-migrator",
            metadata={"managed_by": "local-compose-bootstrap"},
        )
        return "created"
    try:
        resolved = provider.resolve(f"secret://platform/{code}")
    except Exception as exc:
        raise FileStorageSecretBootstrapError(
            f"existing {code} secret is not usable"
        ) from exc
    if not hmac.compare_digest(resolved.encode("utf-8"), value.encode("utf-8")):
        raise FileStorageSecretBootstrapError(
            f"existing {code} secret differs; explicit rotation is required"
        )
    return "preserved"


def main() -> int:
    if not _enabled():
        print("FILE_STORAGE_SECRET_BOOTSTRAP_SKIPPED: status=disabled")
        return 0
    settings = load_master_key_settings(load_settings())
    if settings.environment.lower() not in LOCAL_ENVIRONMENTS:
        print("FILE_STORAGE_SECRET_BOOTSTRAP_FAILED: local-only bootstrap was rejected")
        return 1
    access_key = ""
    secret_key = ""
    database = Database(settings.database_dsn)
    try:
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        access_key = _read_secret(
            os.getenv("FILE_STORAGE_BOOTSTRAP_ACCESS_KEY_FILE", DEFAULT_ACCESS_KEY_FILE),
            label="File storage bootstrap access key",
        )
        secret_key = _read_secret(
            os.getenv("FILE_STORAGE_BOOTSTRAP_SECRET_KEY_FILE", DEFAULT_SECRET_KEY_FILE),
            label="File storage bootstrap secret key",
        )
        provider = EncryptedDbSecretProvider(
            PlatformConfigRepository(database),
            master_key=settings.app_config_master_key,
        )
        with database.unit_of_work():
            access_status = bootstrap_secret(
                provider,
                code=ACCESS_KEY_CODE,
                value=access_key,
            )
            secret_status = bootstrap_secret(
                provider,
                code=SECRET_KEY_CODE,
                value=secret_key,
            )
    except Exception:
        print(
            "FILE_STORAGE_SECRET_BOOTSTRAP_FAILED: "
            "schema, protected files, or existing governed secrets were rejected"
        )
        return 1
    finally:
        access_key = ""
        secret_key = ""
        database.close()
    print(
        "FILE_STORAGE_SECRET_BOOTSTRAP_SUCCEEDED: "
        f"access_key={access_status} secret_key={secret_status}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
