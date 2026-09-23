"""将平台凭据中心引用装配为只读、限时限量的固定 ONES 采集连接。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.modules.knowledge.domain.normalization import ExportValidationError, identifier
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient
from services.ones_mcp_server.provider.target import ProviderContractError, validate_provider_target

from .ones_collection_provider import HttpOnesCollectionProvider


class ManagedOnesCollectionProviderFactory:
    def __init__(
        self,
        resolve_secret: Callable[[str], str],
        *,
        allowed_hosts: tuple[str, ...],
        app_env: str,
        allow_insecure_local: bool = False,
    ) -> None:
        self.resolve_secret = resolve_secret
        self.allowed_hosts = allowed_hosts
        self.app_env = app_env
        self.allow_insecure_local = allow_insecure_local

    def __call__(self, collector: dict[str, Any]) -> HttpOnesCollectionProvider:
        try:
            target = validate_provider_target(
                collector["provider_origin"],
                allowed_hosts=self.allowed_hosts,
                app_env=self.app_env,
                allow_insecure_local=self.allow_insecure_local,
            )
        except (ProviderContractError, ValueError, KeyError):
            raise ExportValidationError("knowledge_collection_target_invalid") from None
        try:
            secret = json.loads(self.resolve_secret(collector["credential_ref"]))
            if not isinstance(secret, dict) or set(secret) != {"token", "user_id"}:
                raise ValueError
            token, user_id = secret["token"], identifier(secret["user_id"])
            if (
                not isinstance(token, str)
                or not token
                or len(token) > 8192
                or any(ord(char) < 32 or ord(char) == 127 for char in token)
            ):
                raise ValueError
        except Exception:
            raise ExportValidationError("knowledge_collection_identity_missing") from None
        http = OnesProviderHttpClient(
            target,
            timeout_seconds=30,
            max_response_bytes=1024 * 1024,
        )
        return HttpOnesCollectionProvider(
            http,
            team_id=collector["team_id"],
            project_ids=frozenset(collector["project_ids"]),
            token=token,
            user_id=user_id,
        )
