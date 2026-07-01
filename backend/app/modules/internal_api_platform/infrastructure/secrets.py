from __future__ import annotations

import os
import re
from typing import Protocol


class SecretResolver(Protocol):
    def resolve(self, ref: str) -> str: ...


def _ref_to_env_name(ref: str) -> str:
    without_scheme = re.sub(r"^secret://", "", ref)
    return "SECRET_" + re.sub(r"[^A-Za-z0-9]+", "_", without_scheme).upper().strip("_")


class EnvSecretResolver:
    """Resolve `secret://a/b/c` references from environment variables.

    `secret://sanjiu/guanlan/db_password` -> `SECRET_SANJIU_GUANLAN_DB_PASSWORD`.
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
