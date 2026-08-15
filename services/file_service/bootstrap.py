from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Never

from app.bootstrap import build_worker_container
from app.modules.file_workspace.application import FileWorkspaceApplicationService
from app.modules.file_workspace.authorization import FileAuthorizationService
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.lifecycle_service import FileLifecycleService
from app.modules.file_workspace.delivery_service import FileVersionDeliveryService
from app.modules.file_workspace.storage import (
    FileObjectStorageSettings,
    MinioFileObjectStorage,
)
from app.modules.file_workspace.streaming_service import GovernedFileStreamingService
from app.modules.mcp_audit import McpAuditCoordinator
from app.shared.config import load_settings
from app.shared.exceptions import NonRetryableExecutionError
from services.file_service.app import create_app
from services.file_service.audit import FileMcpAudit
from services.file_service.auth import (
    CachedPrincipalJwks,
    FilePrincipalVerifier,
    FileWorkerPrincipalVerifier,
)
from services.file_service.principal import FilePrincipalResolver


class _UnavailableStreamingOperations:
    async def download_delivery(
        self,
        *,
        delivery_id: str,
        service_claims: dict[str, Any],
    ) -> tuple[AsyncIterator[bytes], dict[str, str | int]]:
        del delivery_id, service_claims
        self._raise()

    async def download_transfer(
        self, *, transfer_id: str, token: str
    ) -> tuple[AsyncIterator[bytes], str]:
        del transfer_id, token
        self._raise()

    async def upload_commit(
        self,
        *,
        commit_id: str,
        token: str,
        body: AsyncIterator[bytes],
    ) -> dict[str, Any]:
        del commit_id, token, body
        self._raise()

    async def import_attachment(
        self,
        *,
        attachment_id: str,
        service_claims: dict[str, Any],
        media_type: str,
        body: AsyncIterator[bytes],
    ) -> dict[str, Any]:
        del attachment_id, service_claims, media_type, body
        self._raise()

    async def run_maintenance(
        self, *, service_claims: dict[str, Any]
    ) -> dict[str, Any]:
        del service_claims
        self._raise()

    async def maintenance_metrics(
        self, *, service_claims: dict[str, Any]
    ) -> dict[str, Any]:
        del service_claims
        self._raise()

    @staticmethod
    def _raise() -> Never:
        raise NonRetryableExecutionError(
            "File streaming operation is not enabled",
            safe_message="文件流式操作尚未就绪",
            error_code="file_streaming_not_ready",
        )


class _UnavailableStorage:
    def assert_ready(self) -> None:
        raise NonRetryableExecutionError(
            "File object storage is not configured",
            safe_message="文件对象存储尚未就绪",
            error_code="file_storage_unavailable",
        )


class _StorageReadiness:
    def __init__(self, *storages: MinioFileObjectStorage) -> None:
        self.storages = storages

    def assert_ready(self) -> None:
        for storage in self.storages:
            storage.assert_ready()


def create_default_app() -> Any:
    settings = load_settings()
    runtime = build_worker_container(
        settings,
        seed=settings.seed_local_config,
        service_name="file-service",
    )
    repository = FileWorkspaceRepository(runtime.database)
    authorization = FileAuthorizationService(
        runtime.database,
        runtime.business_authorization_service,
    )
    jwks = CachedPrincipalJwks(
        settings.principal_jwt.public_jwks_file,
        refresh_seconds=settings.file_service.jwks_refresh_seconds,
    )
    service_jwks = CachedPrincipalJwks(
        settings.file_service.service_principal_jwks_file,
        refresh_seconds=settings.file_service.jwks_refresh_seconds,
    )
    verifier = FilePrincipalVerifier(jwks)
    principal = FilePrincipalResolver(
        verifier,
        runtime.mcp_tool_snapshot_service,
        authorization,
    )
    service_verifier = FileWorkerPrincipalVerifier(service_jwks)
    storage: MinioFileObjectStorage | _UnavailableStorage
    legacy_storage: MinioFileObjectStorage | None = None
    storage_readiness: _StorageReadiness | _UnavailableStorage
    try:
        storage = MinioFileObjectStorage(
            FileObjectStorageSettings(
                endpoint_url=settings.file_service.endpoint_url,
                bucket=settings.file_service.bucket,
                access_key_ref=settings.file_service.access_key_ref,
                secret_key_ref=settings.file_service.secret_key_ref,
                region=settings.file_service.region,
                secure=settings.file_service.secure,
            ),
            runtime.platform_config_service.resolve_secret,
        )
        legacy_storage = MinioFileObjectStorage(
            FileObjectStorageSettings(
                endpoint_url=settings.file_service.endpoint_url,
                bucket=settings.file_service.legacy_attachment_bucket,
                access_key_ref=settings.file_service.access_key_ref,
                secret_key_ref=settings.file_service.secret_key_ref,
                region=settings.file_service.region,
                secure=settings.file_service.secure,
            ),
            runtime.platform_config_service.resolve_secret,
        )
        storage_readiness = _StorageReadiness(storage, legacy_storage)
    except Exception:
        storage = _UnavailableStorage()
        storage_readiness = storage
    streaming: GovernedFileStreamingService | _UnavailableStreamingOperations
    if isinstance(storage, MinioFileObjectStorage):
        streaming = GovernedFileStreamingService(
            repository,
            authorization,
            storage,
            principal,
            lifecycle=FileLifecycleService(
                repository,
                storage,
                legacy_attachment_storage=legacy_storage,
                legacy_attachment_bucket=settings.file_service.legacy_attachment_bucket,
            ),
            delivery_intents=FileVersionDeliveryService(
                repository,
                runtime.agent_repository,
                settings.delivery,
            ),
        )
        application = FileWorkspaceApplicationService(
            repository, authorization, streaming
        )
    else:
        streaming = _UnavailableStreamingOperations()
        application = FileWorkspaceApplicationService(repository, authorization)
    return create_app(
        principal=principal,
        service_principal=service_verifier,
        application=application,
        streaming=streaming,
        database=runtime.database,
        storage=storage_readiness,
        jwks=jwks,
        service_jwks=service_jwks,
        audit=FileMcpAudit(
            McpAuditCoordinator(
                runtime.database,
                max_payload_bytes=256 * 1024,
                audit_service=runtime.audit_service,
            )
        ),
        max_request_bytes=settings.file_service.max_mcp_request_bytes,
    )
