from __future__ import annotations

from app.modules.platform_config.application.secrets import EncryptedDbSecretProvider
from app.modules.platform_config.infrastructure.repository import PlatformConfigRepository
from app.shared.exceptions import NonRetryableExecutionError


class DbBackedSecretResolver:
    """Resolve only encrypted platform Secret references."""

    def __init__(
        self,
        repository: PlatformConfigRepository,
        *,
        master_key: str = "",
    ) -> None:
        self._provider = EncryptedDbSecretProvider(repository, master_key=master_key)

    def resolve(self, ref: str) -> str:
        if ref.startswith("secret://platform/"):
            return self._provider.resolve(ref)
        if ref.startswith(("vault:", "kms:")):
            raise NonRetryableExecutionError(
                "Reserved secret provider is not implemented",
                safe_message="Provider 尚未实现",
            )
        if ref.startswith("env:"):
            raise NonRetryableExecutionError(
                "Environment secret references require explicit import",
                safe_message="env 凭据引用必须先导入凭据中心",
            )
        raise NonRetryableExecutionError(
            "Unsupported secret reference",
            safe_message="新配置只能使用凭据中心 Secret",
        )
