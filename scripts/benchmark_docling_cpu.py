#!/usr/bin/env python3
"""Run bounded Docling CPU conversions without emitting extracted content."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from app.modules.document_processing.profile import DOCLING_LAYOUT_OCR_V2
from app.modules.document_processing.provider import (
    DoclingServeProvider,
    DocumentProcessorFailure,
    ProcessorTaskState,
)


MEDIA_TYPES = {
    ".pdf": ("application/pdf", "PDF"),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "DOCX",
    ),
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "PPTX",
    ),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "XLSX",
    ),
    ".png": ("image/png", "PNG"),
    ".jpg": ("image/jpeg", "JPEG"),
    ".jpeg": ("image/jpeg", "JPEG"),
    ".webp": ("image/webp", "WEBP"),
}


def _run(path: Path, *, poll_seconds: float, timeout_seconds: int) -> dict[str, object]:
    media_type, format_code = MEDIA_TYPES[path.suffix.lower()]
    api_key_path = Path(
        os.getenv("DOCLING_SERVE_API_KEY_FILE", "/run/secrets/docling_api_key")
    )
    provider = DoclingServeProvider(
        base_url=os.getenv(
            "DOCLING_SERVE_INTERNAL_BASE_URL", "http://docling-serve:5001"
        ),
        allowed_hosts=("docling-serve",),
        api_key=api_key_path.read_text(encoding="utf-8").strip(),
        connect_timeout_seconds=5,
        max_response_bytes=80 * 1024 * 1024,
    )
    started = time.monotonic()
    with path.open("rb") as stream:
        task = provider.submit(
            stream=stream,
            filename=path.name,
            media_type=media_type,
            format_code=format_code,
            profile=DOCLING_LAYOUT_OCR_V2,
        )
    while task.state not in {ProcessorTaskState.SUCCESS, ProcessorTaskState.FAILURE}:
        elapsed = time.monotonic() - started
        if elapsed >= timeout_seconds:
            raise TimeoutError("document_processing_timeout")
        time.sleep(poll_seconds)
        task = provider.poll(task.task_id)
    if task.state is ProcessorTaskState.FAILURE:
        raise DocumentProcessorFailure("docling_conversion_failed", retryable=False)
    result = provider.fetch(task.task_id, profile=DOCLING_LAYOUT_OCR_V2)
    elapsed = time.monotonic() - started
    return {
        "sample": path.name,
        "format": format_code,
        "input_bytes": path.stat().st_size,
        "wall_time_seconds": round(elapsed, 3),
        "throughput_files_per_minute": round(60.0 / elapsed, 3),
        "page_count": result.page_count,
        "processor_time_ms": result.processing_time_ms,
        "markdown_bytes": len(result.markdown),
        "docling_json_bytes": len(result.docling_json),
        "partial": result.partial,
        "no_text": result.no_text,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 600:
        raise SystemExit("timeout must be between 1 and 600 seconds")
    for path in args.paths:
        try:
            print(
                json.dumps(
                    _run(
                        path,
                        poll_seconds=args.poll_seconds,
                        timeout_seconds=args.timeout_seconds,
                    ),
                    sort_keys=True,
                ),
                flush=True,
            )
        except DocumentProcessorFailure as exc:
            print(
                json.dumps(
                    {
                        "sample": path.name,
                        "error_code": exc.error_code,
                        "retryable": exc.retryable,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
