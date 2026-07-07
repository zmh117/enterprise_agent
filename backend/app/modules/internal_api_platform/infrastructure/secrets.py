from __future__ import annotations

import os
import re
from typing import Protocol

from app.shared.exceptions import NonRetryableExecutionError


class SecretResolver(Protocol):
    def resolve(self, ref: str) -> str: ...


def _ref_to_env_name(ref: str) -> str:
    if ref.startswith("env:"):
        return ref.removeprefix("env:")
    without_scheme = re.sub(r"^secret://", "", ref)
    return "SECRET_" + re.sub(r"[^A-Za-z0-9]+", "_", without_scheme).upper().strip("_")


class EnvSecretResolver:
    """Resolve secret references from environment variables.

    `secret://sanjiu/guanlan/db_password` -> `SECRET_SANJIU_GUANLAN_DB_PASSWORD`.
    `env:ORDER_DB_PASSWORD` -> `ORDER_DB_PASSWORD`.
    """

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else dict(os.environ)

    def resolve(self, ref: str) -> str:
        env_name = _ref_to_env_name(ref)
        return self._environ.get(env_name, "")


class MappingSecretResolver:
    """Resolve references directly from an in-memory mapping (used in tests)."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def resolve(self, ref: str) -> str:
        return self._values.get(ref, "")


class DbBackedSecretResolver:
    """Resolve Web-managed platform secrets and keep env fallback behavior."""

    def __init__(
        self,
        repository: object,
        *,
        master_key: str = "",
        fallback: SecretResolver | None = None,
    ) -> None:
        self._repository = repository
        self._master_key = master_key
        self._fallback = fallback or EnvSecretResolver()

    def resolve(self, ref: str) -> str:
        if ref.startswith("secret://platform/"):
            from app.modules.platform_config.application.secrets import EncryptedDbSecretProvider

            return EncryptedDbSecretProvider(
                self._repository,  # type: ignore[arg-type]
                master_key=self._master_key,
            ).resolve(ref)
        if ref.startswith(("vault:", "kms:")):
            raise NonRetryableExecutionError(
                "External secret provider is not configured",
                safe_message="External secret provider is not configured",
            )
        return self._fallback.resolve(ref)
