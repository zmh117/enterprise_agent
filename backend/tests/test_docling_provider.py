from __future__ import annotations

import io
import json
import stat
import zipfile
from collections.abc import Callable

import httpx
import pytest

from app.modules.document_processing.profile import DOCLING_LAYOUT_OCR_V2
from app.modules.document_processing.provider import (
    DoclingServeProvider,
    DocumentProcessorFailure,
    ProcessorTaskState,
)


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> DoclingServeProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return DoclingServeProvider(
        base_url="http://docling-serve:5001",
        allowed_hosts=("docling-serve",),
        api_key="k" * 48,
        connect_timeout_seconds=5,
        max_response_bytes=80 * 1024 * 1024,
        client=client,
    )


def test_docling_provider_uses_only_async_multipart_poll_and_result_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/convert/file/async":
            body = request.read()
            assert request.headers["content-type"].startswith("multipart/form-data;")
            assert b'name="files"' in body
            assert b'name="to_formats"' in body
            assert b"md" in body and b"json" in body
            assert b'name="target_type"' in body and b"inbody" in body
            for forbidden in (
                b"callback",
                b"picture_description_api",
                b"vlm_pipeline",
                b"http://example",
            ):
                assert forbidden not in body
            return httpx.Response(
                200,
                json={
                    "task_id": "task-1",
                    "task_type": "convert",
                    "task_status": "pending",
                    "task_position": 1,
                    "task_meta": None,
                    "error_message": None,
                    "failure": None,
                },
            )
        if request.url.path == "/v1/status/poll/task-1":
            return httpx.Response(
                200,
                json={
                    "task_id": "task-1",
                    "task_type": "convert",
                    "task_status": "success",
                    "task_position": None,
                    "task_meta": None,
                    "error_message": None,
                    "failure": None,
                },
            )
        if request.url.path == "/v1/result/task-1":
            return httpx.Response(
                200,
                json={
                    "document": {
                        "filename": "sample.pdf",
                        "md_content": "# Governed output\n",
                        "json_content": {
                            "schema_name": "DoclingDocument",
                            "pages": {"1": {}},
                        },
                    },
                    "status": "success",
                    "processing_time": 1.25,
                    "timings": {},
                    "errors": [],
                    "confidence": None,
                },
            )
        raise AssertionError(request.url)

    provider = _provider(handler)
    task = provider.submit(
        stream=io.BytesIO(b"%PDF-1.7\n"),
        filename="sample.pdf",
        media_type="application/pdf",
        format_code="PDF",
        profile=DOCLING_LAYOUT_OCR_V2,
    )
    assert task.task_id == "task-1"
    assert task.state is ProcessorTaskState.PENDING
    assert provider.poll(task.task_id).state is ProcessorTaskState.SUCCESS
    result = provider.fetch(task.task_id, profile=DOCLING_LAYOUT_OCR_V2)
    assert result.markdown == b"# Governed output\n"
    assert result.page_count == 1
    assert result.processing_time_ms == 1250
    assert not result.partial
    assert [item.url.path for item in requests] == [
        "/v1/convert/file/async",
        "/v1/status/poll/task-1",
        "/v1/result/task-1",
    ]


def test_layout_v2_provider_accepts_unambiguous_successful_no_text_result() -> None:
    payload = {
        "document": {
            "filename": "picture-input",
            "md_content": "",
            "json_content": None,
        },
        "status": "success",
        "processing_time": 0.5,
        "timings": {},
        "errors": [],
        "confidence": None,
    }
    provider = _provider(lambda _: httpx.Response(200, json=payload))

    result = provider.fetch_picture("task-empty", profile=DOCLING_LAYOUT_OCR_V2)

    assert result.no_text is True
    assert result.partial is False
    assert result.markdown == b""
    assert result.docling_json == b"{}"


@pytest.mark.parametrize(
    ("response", "error_code", "retryable"),
    [
        (
            {
                "document": {
                    "md_content": "ok",
                    "json_content": {"schema_name": "WrongSchema"},
                },
                "status": "success",
                "processing_time": 1,
                "timings": {},
                "errors": [],
            },
            "docling_json_schema_invalid",
            True,
        ),
        (
            {
                "document": {
                    "md_content": "ok",
                    "json_content": {"schema_name": "DoclingDocument"},
                },
                "status": "success",
                "processing_time": 1,
                "timings": {},
                "errors": [],
                "unexpected": "rejected",
            },
            "docling_response_schema_invalid",
            True,
        ),
    ],
)
def test_docling_provider_rejects_malformed_or_schema_drifted_results(
    response: dict[str, object], error_code: str, retryable: bool
) -> None:
    provider = _provider(lambda _: httpx.Response(200, json=response))
    with pytest.raises(DocumentProcessorFailure) as captured:
        provider.fetch("task-1", profile=DOCLING_LAYOUT_OCR_V2)
    assert captured.value.error_code == error_code
    assert captured.value.retryable is retryable


def test_docling_provider_maps_rejection_timeout_and_service_failure_without_body_leak() -> None:
    cases = [
        (404, "docling_task_not_found", True),
        (413, "docling_source_size_exceeded", False),
        (422, "docling_format_rejected", False),
        (503, "docling_service_unavailable", True),
    ]
    for status, code, retryable in cases:
        provider = _provider(
            lambda _, status=status: httpx.Response(status, text="confidential upstream diagnostic")
        )
        with pytest.raises(DocumentProcessorFailure) as captured:
            provider.poll("task-1")
        assert captured.value.error_code == code
        assert captured.value.retryable is retryable
        assert "confidential" not in str(captured.value)


def test_docling_provider_rejects_invalid_content_length_without_leaking_response() -> None:
    provider = _provider(
        lambda _: httpx.Response(
            200,
            headers={"content-length": "not-an-integer"},
            text="confidential upstream diagnostic",
        )
    )
    with pytest.raises(DocumentProcessorFailure) as captured:
        provider.poll("task-1")
    assert captured.value.error_code == "docling_response_schema_invalid"
    assert captured.value.retryable is True
    assert "confidential" not in str(captured.value)


def _office_bundle(*, source_format: str, extra_name: str | None = None) -> bytes:
    picture: dict[str, object] = {
        "self_ref": "#/pictures/0",
        "parent": {"$ref": "#/body"},
        "image": {"uri": "pictures/picture.png", "mimetype": "image/png"},
    }
    if source_format == "PPTX":
        picture["prov"] = [
            {
                "page_no": 4,
                "bbox": {
                    "l": 10.0,
                    "t": 80.0,
                    "r": 90.0,
                    "b": 20.0,
                    "coord_origin": "BOTTOMLEFT",
                },
            }
        ]
    document = {
        "schema_name": "DoclingDocument",
        "body": {
            "label": "chapter" if source_format == "PPTX" else "section_header",
            "children": [{"$ref": "#/pictures/0"}],
        },
        "pictures": [picture],
        "pages": {
            "4" if source_format == "PPTX" else "1": {
                "size": {"width": 100, "height": 100}
            }
        },
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("document.md", "# Parent text\n")
        archive.writestr("document.json", json.dumps(document))
        archive.writestr("pictures/picture.png", b"safe-synthetic-png")
        if extra_name is not None:
            archive.writestr(extra_name, b"unexpected")
    return output.getvalue()


@pytest.mark.parametrize("source_format", ["DOCX", "PPTX"])
def test_layout_provider_uses_fixed_upload_name_and_validates_picture_bundle(
    source_format: str,
) -> None:
    bundle = _office_bundle(source_format=source_format)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            body = request.read()
            assert b"confidential-customer-name" not in body
            assert b"document-input." in body
            assert b'name="target_type"' in body and b"zip" in body
            assert b'name="include_images"' in body and b"true" in body
            return httpx.Response(200, json={"task_id": "task-layout", "task_status": "pending"})
        return httpx.Response(200, content=bundle, headers={"content-type": "application/zip"})

    provider = _provider(handler)
    task = provider.submit(
        stream=io.BytesIO(b"synthetic-office"),
        filename=f"confidential-customer-name.{source_format.lower()}",
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if source_format == "DOCX"
            else "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        format_code=source_format,
        profile=DOCLING_LAYOUT_OCR_V2,
    )
    result = provider.fetch_bundle(
        task.task_id,
        profile=DOCLING_LAYOUT_OCR_V2,
        source_format=source_format,
    )
    assert result.markdown == b"# Parent text\n"
    assert len(result.pictures) == 1
    assert result.pictures[0].picture_ref == "#/pictures/0"
    assert result.pictures[0].parent_ref == "#/body"
    assert result.pictures[0].parent_ordinal == 0
    if source_format == "PPTX":
        assert result.pictures[0].slide_no == 4
        assert result.pictures[0].parent_bbox is not None
    else:
        assert result.pictures[0].slide_no is None
        assert result.pictures[0].parent_bbox is None


@pytest.mark.parametrize(
    ("bundle", "error_code"),
    [
        (_office_bundle(source_format="DOCX", extra_name="../escape.png"), "docling_bundle_path_invalid"),
        (_office_bundle(source_format="DOCX", extra_name="unknown.bin"), "docling_bundle_entry_unknown"),
    ],
)
def test_layout_bundle_rejects_path_traversal_and_unknown_entries(
    bundle: bytes,
    error_code: str,
) -> None:
    provider = _provider(
        lambda _: httpx.Response(
            200,
            content=bundle,
            headers={"content-type": "application/zip"},
        )
    )
    with pytest.raises(DocumentProcessorFailure) as captured:
        provider.fetch_bundle(
            "task-layout",
            profile=DOCLING_LAYOUT_OCR_V2,
            source_format="DOCX",
        )
    assert captured.value.error_code == error_code
    assert captured.value.retryable is False


def test_layout_bundle_rejects_symlink_entry() -> None:
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as archive:
        link = zipfile.ZipInfo("document.md")
        link.create_system = 3
        link.external_attr = stat.S_IFLNK << 16
        archive.writestr(link, "target")
        archive.writestr("document.json", '{"schema_name":"DoclingDocument","pictures":[]}')
    provider = _provider(
        lambda _: httpx.Response(
            200,
            content=body.getvalue(),
            headers={"content-type": "application/zip"},
        )
    )
    with pytest.raises(DocumentProcessorFailure) as captured:
        provider.fetch_bundle(
            "task-layout",
            profile=DOCLING_LAYOUT_OCR_V2,
            source_format="DOCX",
        )
    assert captured.value.error_code == "docling_bundle_entry_unsafe"
