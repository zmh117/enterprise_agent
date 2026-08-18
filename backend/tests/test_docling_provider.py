from __future__ import annotations

import io
from collections.abc import Callable

import httpx
import pytest

from app.modules.document_processing.profile import DOCLING_TEXT_V1
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
        profile=DOCLING_TEXT_V1,
    )
    assert task.task_id == "task-1"
    assert task.state is ProcessorTaskState.PENDING
    assert provider.poll(task.task_id).state is ProcessorTaskState.SUCCESS
    result = provider.fetch(task.task_id, profile=DOCLING_TEXT_V1)
    assert result.markdown == b"# Governed output\n"
    assert result.page_count == 1
    assert result.processing_time_ms == 1250
    assert not result.partial
    assert [item.url.path for item in requests] == [
        "/v1/convert/file/async",
        "/v1/status/poll/task-1",
        "/v1/result/task-1",
    ]


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
        provider.fetch("task-1", profile=DOCLING_TEXT_V1)
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
