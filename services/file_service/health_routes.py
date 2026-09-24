from __future__ import annotations

from typing import Any, Protocol

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.modules.document_processing.profile import (
    DOCLING_LAYOUT_OCR_V2,
    DOCLING_LAYOUT_OCR_V2_PROFILE_HASH,
)
from app.modules.file_workspace.contracts import FILE_MCP_SERVER_CODE, FILE_TOOL_MANIFEST
from app.shared.build_identity import BuildIdentity
from services.file_service.auth import CachedPrincipalJwks
from services.file_service.processing_routes import DocumentProcessingOperations


REQUIRED_SCHEMA_VERSION = 121


class FileServiceReadiness(Protocol):
    def assert_ready(self) -> None: ...


class FileServiceHealthRoutes:
    def __init__(
        self,
        *,
        build_identity: BuildIdentity,
        database: Any,
        storage: FileServiceReadiness,
        jwks: CachedPrincipalJwks,
        document_processing: DocumentProcessingOperations | None,
        document_processing_expected: bool,
    ) -> None:
        self._build_identity = build_identity
        self._database = database
        self._storage = storage
        self._jwks = jwks
        self._document_processing = document_processing
        self._document_processing_expected = document_processing_expected

    async def health(self, _: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "server_code": FILE_MCP_SERVER_CODE,
                "runtime_protocol_version": "1.5",
                "build_identity": self._build_identity.to_dict(),
            }
        )

    async def readiness(self, _: Request) -> JSONResponse:
        try:
            self._database.execute_one("select 1 as ready")
            schema = self._database.execute_one(
                "select version from schema_migration order by version desc limit 1"
            )
            if schema is None or int(schema["version"]) < REQUIRED_SCHEMA_VERSION:
                raise ValueError("File Service schema is not current")
            self._database.execute("select id from task_workspace where 1 = 0")
            self._database.execute("select id from managed_file_version where 1 = 0")
            self._database.execute("select id from document_picture_asset where 1 = 0")
            self._database.execute("select id from document_processing_stage_outbox where 1 = 0")
            layout_options = DOCLING_LAYOUT_OCR_V2.layout_ocr_options
            if (
                layout_options is None
                or DOCLING_LAYOUT_OCR_V2.profile_hash != DOCLING_LAYOUT_OCR_V2_PROFILE_HASH
                or layout_options["layout_schema"]
                != {
                    "name": "enterprise-agent.office-image-ocr-layout",
                    "version": "v2",
                }
                or tuple(DOCLING_LAYOUT_OCR_V2.output_kinds)
                != ("MARKDOWN", "DOCLING_JSON", "OCR_LAYOUT_JSON")
            ):
                raise ValueError("File Service layout OCR registry is invalid")
            self._storage.assert_ready()
            self._jwks.current()
            if tuple(sorted(FILE_TOOL_MANIFEST)) != (
                "file_create_commit_intent",
                "file_deliver_version",
                "file_get_metadata",
                "file_prepare_materialization",
                "file_retain_version",
                "task_workspace_get",
                "task_workspace_list_files",
                "task_workspace_search_files",
            ):
                raise ValueError("File Tool Manifest is invalid")
            if self._document_processing_expected and self._document_processing is None:
                raise ValueError(
                    "File Service document processing is configured but was not composed"
                )
            processing_readiness = (
                self._document_processing.docling_concurrency_readiness()
                if self._document_processing is not None
                else {
                    "configured": False,
                    "ready": False,
                    "reason_code": "document_processing_not_configured",
                    "expected_workers": 2,
                    "active_workers": 0,
                    "eligible_workers": 0,
                    "slots_total": 0,
                    "slots_occupied": 0,
                    "slots_quarantined": 0,
                    "oldest_lease_expires_at": "",
                }
            )
            return JSONResponse(
                {
                    "status": "ok",
                    "server_code": FILE_MCP_SERVER_CODE,
                    "database": "ready",
                    "schema": "ready",
                    "object_storage": "ready",
                    "principal_jwks": "ready",
                    "tool_manifest": "ready",
                    "streaming_api": "ready",
                    "layout_ocr_profile_registry": "ready",
                    "layout_ocr_schema": "ready",
                    "document_processing": processing_readiness,
                    "runtime_protocol_version": "1.5",
                    "build_identity": self._build_identity.to_dict(),
                }
            )
        except Exception:
            return JSONResponse(
                {
                    "status": "degraded",
                    "server_code": FILE_MCP_SERVER_CODE,
                    "dependency": "unavailable",
                    "runtime_protocol_version": "1.5",
                    "build_identity": self._build_identity.to_dict(),
                },
                status_code=503,
            )
