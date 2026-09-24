from __future__ import annotations

import io
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.file_service.app import create_app
from services.file_service.auth import FilePrincipalError


PATH_IDS = {
    "transfer_id": "transfer-7",
    "commit_id": "commit-7",
    "attachment_id": "attachment-7",
    "delivery_id": "delivery-7",
    "run_id": "run-7",
    "kind": "MARKDOWN",
    "picture_item_id": "item-7",
}
PROCESSING = "internal:file-service:document-processing"
ROW = {
    "id": "row-1",
    "kind": "MARKDOWN",
    "status": "OK",
    "attempt": 1,
    "error_code": None,
    "external_task_id": None,
    "occurrence_index": 0,
    "profile_hash": "h",
    "assembly_status": "READY",
    "assembly_attempt": 1,
    "size_bytes": 1,
    "content_sha256": "c",
}
BACKEND_DENIAL = {"error": "后端拒绝", "error_code": "contract_backend_denied"}


def _backend_denial() -> FilePrincipalError:
    return FilePrincipalError(
        "Contract backend denial",
        safe_message=BACKEND_DENIAL["error"],
        error_code=BACKEND_DENIAL["error_code"],
    )


@dataclass(frozen=True)
class RouteCase:
    method: str
    template: str
    verifier: tuple[str, str] | None
    operations: tuple[str, ...]
    json: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    content: bytes | None = None
    action: str = ""
    forwards_path_ids: bool = True

    @property
    def path(self) -> str:
        return self.template.format(**PATH_IDS, action=self.action)

    @property
    def path_values(self) -> list[str]:
        names = re.findall(r"{(\w+)}", self.template)
        return [PATH_IDS[name] for name in names if name != "action"]


def _admission(action: str, **extra: str) -> RouteCase:
    return RouteCase(
        "POST",
        "/internal/v1/document-processing/admission/{action}",
        ("processing", f"{PROCESSING}:admission"),
        (f"{action}_docling_slot",),
        json={"owner_kind": "run", "owner_id": "run-7", "worker_instance_id": "w-1", **extra},
        action=action,
    )


# Ordered as the Starlette route table: matching order is part of the contract.
ROUTE_CASES = (
    RouteCase(
        "GET",
        "/internal/v1/file-transfers/{transfer_id}/content",
        None,
        ("download_transfer",),
    ),
    RouteCase(
        "PUT",
        "/internal/v1/file-commits/{commit_id}/content",
        None,
        ("upload_commit",),
        content=b"commit",
    ),
    RouteCase(
        "POST",
        "/internal/v1/attachments/{attachment_id}/content",
        ("service", "internal:file-service:attachment:import"),
        ("import_attachment",),
        content=b"attachment",
    ),
    RouteCase(
        "POST",
        "/internal/v1/file-maintenance/run",
        ("service", "internal:file-service:content:cleanup"),
        ("run_maintenance",),
    ),
    RouteCase(
        "GET",
        "/internal/v1/file-maintenance/metrics",
        ("service", "internal:file-service:content:cleanup"),
        ("maintenance_metrics",),
    ),
    RouteCase(
        "GET",
        "/internal/v1/file-deliveries/{delivery_id}/content",
        ("delivery", "internal:file-service:delivery:read"),
        ("download_delivery",),
    ),
    _admission("acquire"),
    _admission("renew"),
    _admission("release"),
    _admission("quarantine", reason_code="docling_hung"),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/workers/heartbeat",
        ("processing", f"{PROCESSING}:heartbeat"),
        ("record_processing_worker_heartbeat",),
        json={
            "instance_id": "w-1",
            "profile_hash": "h",
            "queue_contract": "q",
            "docling_local_workers": 1,
            "status": "READY",
            "reason_code": "ready",
        },
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/claim",
        ("processing", f"{PROCESSING}:claim"),
        ("claim",),
        json={
            "contract_version": "v1",
            "run_id": "run-7",
            "source_version_id": "version-1",
            "profile_hash": "h",
            "attempt": 1,
            "correlation_id": "corr-1",
        },
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/source-grant",
        ("processing", f"{PROCESSING}:source:read"),
        ("prepare_source_stream",),
        json={"tenant_id": "tenant-1"},
    ),
    RouteCase(
        "GET",
        "/internal/v1/document-processing/runs/{run_id}/source",
        ("processing", f"{PROCESSING}:source:read"),
        ("open_source_stream",),
        headers={"x-document-source-grant": "grant-1"},
        # The source grant alone binds the run.
        forwards_path_ids=False,
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/submitted",
        ("processing", f"{PROCESSING}:claim"),
        ("mark_submitted",),
        json={"external_task_id": "task-1"},
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/representations/{kind}/prepare",
        ("processing", f"{PROCESSING}:representation:write"),
        ("prepare_representation_transfer",),
        json={"expected_size_bytes": 1, "expected_sha256": "s"},
    ),
    RouteCase(
        "PUT",
        "/internal/v1/document-processing/transfers/{transfer_id}/content",
        ("processing", f"{PROCESSING}:representation:write"),
        ("upload_representation",),
        headers={"x-representation-upload-token": "upload-1"},
        content=b"representation",
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/parent-artifact/prepare",
        ("processing", f"{PROCESSING}:representation:write"),
        ("prepare_parent_artifact_transfer",),
        json={"expected_size_bytes": 1, "expected_sha256": "s"},
    ),
    RouteCase(
        "PUT",
        "/internal/v1/document-processing/parent-artifact-transfers/{transfer_id}/content",
        ("processing", f"{PROCESSING}:representation:write"),
        ("upload_parent_artifact",),
        headers={"x-parent-artifact-upload-token": "upload-1"},
        content=b"# parent",
    ),
    RouteCase(
        "GET",
        "/internal/v1/document-processing/runs/{run_id}/parent-artifact",
        ("processing", f"{PROCESSING}:source:read"),
        ("open_parent_artifact",),
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/picture-assets/prepare",
        ("processing", f"{PROCESSING}:representation:write"),
        ("prepare_picture_asset_transfer",),
        json={
            "normalized_sha256": "s",
            "media_type": "image/png",
            "original_width_pixels": 2,
            "original_height_pixels": 2,
            "width_pixels": 1,
            "height_pixels": 1,
            "normalization_transform": {"scale": 0.5},
            "size_bytes": 1,
        },
    ),
    RouteCase(
        "PUT",
        "/internal/v1/document-processing/picture-asset-transfers/{transfer_id}/content",
        ("processing", f"{PROCESSING}:representation:write"),
        ("upload_picture_asset",),
        headers={"x-picture-asset-upload-token": "upload-1", "content-type": "image/png"},
        content=b"png",
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/picture-occurrences",
        ("processing", f"{PROCESSING}:claim"),
        ("register_picture_occurrence",),
        json={
            "picture_asset_id": "asset-1",
            "occurrence_index": 0,
            "source_format": "DOCX",
            "picture_ref": "#/pictures/0",
            "parent_ref": "#/body",
            "parent_label": "body",
            "parent_ordinal": 0,
            "slide_no": None,
            "parent_bbox": None,
            "selection_status": "SELECTED",
        },
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/picture-items",
        ("processing", f"{PROCESSING}:claim"),
        ("register_picture_item",),
        json={
            "picture_asset_id": "asset-1",
            "occurrence_count": 1,
            "ocr_engine_code": "ocr",
            "model_revision": "r1",
            "model_digest": "d",
            "correlation_id": "corr-1",
        },
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/picture-items/{picture_item_id}/claim",
        ("processing", f"{PROCESSING}:claim"),
        ("claim_picture_item", "picture_item_context"),
        json={"claim_token": "claim-1", "claim_expires_at": "2099-01-01T00:00:00+00:00"},
    ),
    RouteCase(
        "GET",
        "/internal/v1/document-processing/picture-items/{picture_item_id}/asset",
        ("processing", f"{PROCESSING}:source:read"),
        ("open_picture_asset",),
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/picture-items/{picture_item_id}/submitted",
        ("processing", f"{PROCESSING}:claim"),
        ("mark_picture_submitted",),
        json={"external_task_id": "task-1"},
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/picture-items/{picture_item_id}/result/prepare",
        ("processing", f"{PROCESSING}:representation:write"),
        ("prepare_picture_result_transfer",),
        json={"expected_size_bytes": 1, "expected_sha256": "s"},
    ),
    RouteCase(
        "PUT",
        "/internal/v1/document-processing/picture-result-transfers/{transfer_id}/content",
        ("processing", f"{PROCESSING}:representation:write"),
        ("upload_picture_result",),
        headers={"x-picture-result-upload-token": "upload-1"},
        content=b"{}",
    ),
    RouteCase(
        "GET",
        "/internal/v1/document-processing/picture-items/{picture_item_id}/result",
        ("processing", f"{PROCESSING}:source:read"),
        ("open_picture_result",),
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/picture-items/{picture_item_id}/complete",
        ("processing", f"{PROCESSING}:complete"),
        ("complete_picture_item",),
        json={
            "status": "SUCCEEDED",
            "result_size_bytes": 1,
            "result_sha256": "s",
            "error_code": "",
            "correlation_id": "corr-1",
        },
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/picture-items/{picture_item_id}/retry",
        ("processing", f"{PROCESSING}:complete"),
        ("retry_picture_item",),
        json={"error_code": "ocr_timeout", "delay_seconds": 5},
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/parent-complete",
        ("processing", f"{PROCESSING}:complete"),
        ("complete_parent_parse",),
        json={"correlation_id": "corr-1"},
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/assembly/claim",
        ("processing", f"{PROCESSING}:claim"),
        ("claim_assembly",),
        json={"claim_token": "claim-1"},
    ),
    RouteCase(
        "GET",
        "/internal/v1/document-processing/runs/{run_id}/assembly/context",
        ("processing", f"{PROCESSING}:source:read"),
        ("assembly_context",),
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/assembly/finish",
        ("processing", f"{PROCESSING}:complete"),
        ("finish_assembly",),
        json={"succeeded": True},
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/assembly/retry",
        ("processing", f"{PROCESSING}:complete"),
        ("retry_assembly",),
        json={},
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/finalize",
        ("processing", f"{PROCESSING}:complete"),
        ("finalize",),
        json={"partial": False, "page_count": 1, "processing_time_ms": 10},
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/no-text",
        ("processing", f"{PROCESSING}:complete"),
        ("complete_without_text",),
        json={"page_count": 1, "processing_time_ms": 10},
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/retry",
        ("processing", f"{PROCESSING}:complete"),
        ("schedule_retry",),
        json={"error_code": "docling_timeout", "delay_seconds": 5},
    ),
    RouteCase(
        "POST",
        "/internal/v1/document-processing/runs/{run_id}/fail",
        ("processing", f"{PROCESSING}:complete"),
        ("fail",),
        json={"error_code": "docling_failed", "processing_time_ms": 10},
    ),
)


class _Database:
    def execute_one(self, query: str) -> dict[str, Any]:
        return {"version": 999} if "schema_migration" in query else {"ready": 1}

    def execute(self, _: str) -> list[dict[str, Any]]:
        return []


class _Ready:
    def assert_ready(self) -> None:
        return None

    def current(self) -> object:
        return object()


class _Unused:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"MCP dependency must not be used by internal routes: {name}")


class _Principal:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def _verify(self, kind: str, required_scope: str) -> dict[str, Any]:
        self.calls.append((kind, required_scope))
        return {"sub": "internal-worker"}

    def verify_service(self, token: str, *, required_scope: str) -> dict[str, Any]:
        return self._verify("service", required_scope)

    def verify_delivery(self, token: str, *, required_scope: str) -> dict[str, Any]:
        return self._verify("delivery", required_scope)

    def verify_processing(self, token: str, *, required_scope: str) -> dict[str, Any]:
        return self._verify("processing", required_scope)


async def _chunks() -> AsyncIterator[bytes]:
    yield b"content"


class _Streaming:
    def __init__(self, calls: list[tuple[str, dict[str, Any]]], *, deny: bool) -> None:
        self.calls = calls
        self.deny = deny

    def _record(self, name: str, values: dict[str, Any]) -> None:
        self.calls.append((name, values))
        if self.deny:
            raise _backend_denial()

    async def download_transfer(self, **values: Any) -> tuple[AsyncIterator[bytes], str]:
        self._record("download_transfer", values)
        return _chunks(), "application/octet-stream"

    async def upload_commit(self, **values: Any) -> dict[str, Any]:
        self._record("upload_commit", values)
        return {"status": "COMMITTED"}

    async def import_attachment(self, **values: Any) -> dict[str, Any]:
        self._record("import_attachment", values)
        return {"status": "READY"}

    async def run_maintenance(self, **values: Any) -> dict[str, Any]:
        self._record("run_maintenance", values)
        return {"deleted": 0}

    async def maintenance_metrics(self, **values: Any) -> dict[str, Any]:
        self._record("maintenance_metrics", values)
        return {"pending": 0}

    async def download_delivery(self, **values: Any) -> tuple[AsyncIterator[bytes], dict[str, Any]]:
        self._record("download_delivery", values)
        return _chunks(), {
            "media_type": "text/plain",
            "display_name": "报告.txt",
            "size_bytes": 7,
            "sha256": "s",
            "format_code": "TXT",
        }


class _DocumentProcessing:
    def __init__(
        self,
        calls: list[tuple[str, dict[str, Any]]],
        *,
        deny: bool,
        opened: list[io.BytesIO],
    ) -> None:
        self.calls = calls
        self.deny = deny
        self.opened = opened

    def __getattr__(self, name: str) -> Any:
        def operation(**values: Any) -> Any:
            self.calls.append((name, values))
            if self.deny:
                raise _backend_denial()
            if name.startswith("open_"):
                self.opened.append(io.BytesIO(b"content"))
                return self.opened[-1]
            if name in {"claim_picture_item", "claim_assembly"}:
                return dict(ROW), True
            if name == "finalize":
                return [dict(ROW)]
            return dict(ROW)

        return operation


def _client(
    *, deny: bool = False, opened: list[io.BytesIO] | None = None
) -> tuple[TestClient, _Principal, list[tuple[str, dict[str, Any]]]]:
    principal = _Principal()
    calls: list[tuple[str, dict[str, Any]]] = []
    processing = _DocumentProcessing(calls, deny=deny, opened=[] if opened is None else opened)
    app = create_app(
        principal=_Unused(),  # type: ignore[arg-type]
        service_principal=principal,  # type: ignore[arg-type]
        application=_Unused(),  # type: ignore[arg-type]
        streaming=_Streaming(calls, deny=deny),
        document_processing=processing,  # type: ignore[arg-type]
        database=_Database(),
        storage=_Ready(),
        jwks=_Ready(),  # type: ignore[arg-type]
    )
    return TestClient(app), principal, calls


def test_route_table_order_and_methods_are_the_published_contract() -> None:
    client, _principal, _calls = _client()
    routes = client.app.app.routes  # type: ignore[attr-defined]

    expected: list[tuple[str, tuple[str, ...]]] = [
        ("/health", ("GET", "HEAD")),
        ("/ready", ("GET", "HEAD")),
        ("/mcp", ()),
    ]
    for case in ROUTE_CASES:
        methods = ("GET", "HEAD") if case.method == "GET" else (case.method,)
        if (case.template, methods) not in expected:
            expected.append((case.template, methods))
    assert [(route.path, tuple(sorted(route.methods or ()))) for route in routes] == expected


@pytest.mark.parametrize("case", ROUTE_CASES, ids=lambda case: f"{case.method} {case.path}")
def test_internal_route_binds_scope_and_backend_operation(case: RouteCase) -> None:
    client, principal, calls = _client()

    response = client.request(
        case.method,
        case.path,
        headers={"authorization": "Bearer internal-token", **case.headers},
        json=case.json,
        content=case.content,
    )

    assert response.status_code == 200, response.text
    assert principal.calls == ([] if case.verifier is None else [case.verifier])
    assert [name for name, _values in calls] == list(case.operations)
    if case.forwards_path_ids:
        assert set(case.path_values) <= _scalar_values(calls[0][1])


@pytest.mark.parametrize(
    "case",
    [case for case in ROUTE_CASES if case.operations[0].startswith("open_")],
    ids=lambda case: f"{case.method} {case.path}",
)
def test_document_content_stream_is_closed_after_response(case: RouteCase) -> None:
    opened: list[io.BytesIO] = []
    client, _principal, _calls = _client(opened=opened)

    response = client.request(
        case.method,
        case.path,
        headers={"authorization": "Bearer internal-token", **case.headers},
    )

    assert response.status_code == 200
    assert response.content == b"content"
    assert len(opened) == 1
    assert opened[0].closed


@pytest.mark.parametrize("case", ROUTE_CASES, ids=lambda case: f"{case.method} {case.path}")
def test_internal_route_without_bearer_is_denied_before_backend(case: RouteCase) -> None:
    client, principal, calls = _client()

    response = client.request(
        case.method, case.path, headers=case.headers, json=case.json, content=case.content
    )

    assert response.status_code == 403
    assert response.json() == {
        "error": "平台文件身份凭证缺失",
        "error_code": "file_principal_token_missing",
    }
    assert principal.calls == []
    assert calls == []


@pytest.mark.parametrize("case", ROUTE_CASES, ids=lambda case: f"{case.method} {case.path}")
def test_internal_route_maps_backend_app_error_to_safe_denial(case: RouteCase) -> None:
    client, _principal, calls = _client(deny=True)

    response = client.request(
        case.method,
        case.path,
        headers={"authorization": "Bearer internal-token", **case.headers},
        json=case.json,
        content=case.content,
    )

    assert response.status_code == 403
    assert response.json() == BACKEND_DENIAL
    assert [name for name, _values in calls] == [case.operations[0]]


def _scalar_values(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(_scalar_values(item) for item in value.values()))
    return {str(value)}
