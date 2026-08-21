#!/usr/bin/env python3
"""Benchmark synthetic Office picture extraction and per-picture OCR.

Output contains only aggregate sizes, counts, and timings. It excludes task IDs,
source/member names, image bytes, OCR text, coordinates, and credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from PIL import Image


MAX_RESULT_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 512
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
OFFICE_MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _wait(client: httpx.Client, base_url: str, task_id: str, deadline: float) -> None:
    while time.monotonic() < deadline:
        response = client.get(f"{base_url}/v1/status/poll/{task_id}")
        response.raise_for_status()
        state = str(response.json().get("task_status") or "")
        if state == "success":
            return
        if state == "failure":
            raise RuntimeError("layout_benchmark_conversion_failed")
        if state not in {"pending", "started"}:
            raise RuntimeError("layout_benchmark_task_state_invalid")
        time.sleep(0.25)
    raise RuntimeError("layout_benchmark_timeout")


def _submit(
    client: httpx.Client,
    base_url: str,
    *,
    content: bytes,
    media_type: str,
    form: dict[str, str | list[str]],
    timeout_seconds: int,
) -> tuple[str, float]:
    started = time.monotonic()
    response = client.post(
        f"{base_url}/v1/convert/file/async",
        data=form,
        files={"files": ("synthetic-input", BytesIO(content), media_type)},
    )
    response.raise_for_status()
    task_id = str(response.json().get("task_id") or "")
    if not task_id or any(character in task_id for character in "/\\\r\n"):
        raise RuntimeError("layout_benchmark_task_identity_invalid")
    _wait(client, base_url, task_id, time.monotonic() + timeout_seconds)
    return task_id, started


def _bounded_body(response: httpx.Response) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None and int(content_length) > MAX_RESULT_BYTES:
        raise RuntimeError("layout_benchmark_result_too_large")
    body = response.content
    if len(body) > MAX_RESULT_BYTES:
        raise RuntimeError("layout_benchmark_result_too_large")
    return body


def _office_bundle(
    client: httpx.Client,
    base_url: str,
    path: Path,
) -> tuple[dict[str, int | float | str], list[bytes]]:
    source = path.read_bytes()
    format_code = path.suffix.lower().lstrip(".")
    task_id, started = _submit(
        client,
        base_url,
        content=source,
        media_type=OFFICE_MEDIA_TYPES[path.suffix.lower()],
        form={
            "from_formats": format_code,
            "to_formats": ["md", "json"],
            "target_type": "zip",
            "image_export_mode": "referenced",
            "include_images": "true",
            "include_page_images": "false",
            "do_ocr": "true",
            "force_ocr": "false",
            "do_table_structure": "true",
            "do_picture_description": "false",
            "do_picture_classification": "false",
            "do_chart_extraction": "false",
            "do_code_enrichment": "false",
            "do_formula_enrichment": "false",
            "abort_on_error": "false",
        },
        timeout_seconds=600,
    )
    response = client.get(f"{base_url}/v1/result/{task_id}")
    response.raise_for_status()
    if response.headers.get("content-type", "").split(";", 1)[0] != "application/zip":
        raise RuntimeError("layout_benchmark_bundle_media_type_invalid")
    bundle = _bounded_body(response)
    image_contents: list[bytes] = []
    total_uncompressed = 0
    markdown_bytes = 0
    docling_json_bytes = 0
    with zipfile.ZipFile(BytesIO(bundle)) as archive:
        members = archive.infolist()
        if not 1 <= len(members) <= MAX_ARCHIVE_ENTRIES:
            raise RuntimeError("layout_benchmark_entry_count_invalid")
        seen: set[str] = set()
        for member in members:
            normalized = str(PurePosixPath(member.filename.rstrip("/")))
            parts = PurePosixPath(normalized).parts
            if (
                not normalized
                or "\\" in member.filename
                or PurePosixPath(normalized).is_absolute()
                or any(part in {"", ".", ".."} for part in parts)
                or normalized in seen
            ):
                raise RuntimeError("layout_benchmark_member_path_invalid")
            seen.add(normalized)
            if member.is_dir():
                continue
            total_uncompressed += member.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise RuntimeError("layout_benchmark_uncompressed_size_exceeded")
            suffix = PurePosixPath(normalized).suffix.lower()
            if suffix in IMAGE_SUFFIXES:
                image_contents.append(archive.read(member))
            elif suffix == ".md":
                markdown_bytes += member.file_size
            elif suffix == ".json":
                docling_json_bytes += member.file_size
            else:
                raise RuntimeError("layout_benchmark_member_type_invalid")
    return (
        {
            "format": format_code,
            "source_bytes": len(source),
            "parent_wall_seconds": round(time.monotonic() - started, 3),
            "bundle_bytes": len(bundle),
            "bundle_uncompressed_bytes": total_uncompressed,
            "parent_markdown_bytes": markdown_bytes,
            "parent_docling_json_bytes": docling_json_bytes,
            "picture_occurrences": len(image_contents),
        },
        image_contents,
    )


def _text_metrics(document: dict[str, Any]) -> tuple[int, int, int, int]:
    texts = document.get("texts")
    if not isinstance(texts, list):
        return 0, 0, 0, 0
    blocks = 0
    words = 0
    characters = 0
    bbox_count = 0
    for item in texts:
        if not isinstance(item, dict):
            continue
        value = item.get("text")
        if isinstance(value, str) and value:
            blocks += 1
            words += len(value.split())
            characters += len(value)
        provenance = item.get("prov")
        if isinstance(provenance, list):
            bbox_count += sum(
                1 for entry in provenance if isinstance(entry, dict) and isinstance(entry.get("bbox"), dict)
            )
    return blocks, words, characters, bbox_count


def _ocr_picture(
    client: httpx.Client,
    base_url: str,
    content: bytes,
) -> dict[str, int | float]:
    with Image.open(BytesIO(content)) as image:
        image.verify()
        width, height = image.size
    task_id, started = _submit(
        client,
        base_url,
        content=content,
        media_type="image/png",
        form={
            "from_formats": "image",
            "to_formats": ["md", "json"],
            "target_type": "inbody",
            "image_export_mode": "placeholder",
            "include_images": "false",
            "include_page_images": "false",
            "do_ocr": "true",
            "force_ocr": "false",
            "ocr_preset": "rapidocr",
            "do_table_structure": "false",
            "do_picture_description": "false",
            "do_picture_classification": "false",
            "do_chart_extraction": "false",
            "do_code_enrichment": "false",
            "do_formula_enrichment": "false",
            "abort_on_error": "true",
        },
        timeout_seconds=180,
    )
    response = client.get(f"{base_url}/v1/result/{task_id}")
    response.raise_for_status()
    if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise RuntimeError("layout_benchmark_ocr_media_type_invalid")
    body = _bounded_body(response)
    payload = json.loads(body)
    document = payload.get("document")
    if not isinstance(document, dict) or not isinstance(document.get("json_content"), dict):
        raise RuntimeError("layout_benchmark_ocr_schema_invalid")
    markdown = document.get("md_content")
    if markdown is not None and not isinstance(markdown, str):
        raise RuntimeError("layout_benchmark_ocr_schema_invalid")
    docling_json = document["json_content"]
    blocks, words, characters, bbox_count = _text_metrics(docling_json)
    return {
        "wall_seconds": round(time.monotonic() - started, 3),
        "pixels": width * height,
        "compressed_bytes": len(content),
        "markdown_bytes": len((markdown or "").encode("utf-8")),
        "json_bytes": len(json.dumps(docling_json, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
        "blocks": blocks,
        "tokenized_words": words,
        "characters": characters,
        "bbox_count": bbox_count,
    }


def _case(
    client: httpx.Client,
    base_url: str,
    label: str,
    path: Path,
) -> dict[str, Any]:
    parent, occurrences = _office_bundle(client, base_url, path)
    unique: dict[str, bytes] = {}
    for content in occurrences:
        unique.setdefault(hashlib.sha256(content).hexdigest(), content)
    picture_results = [_ocr_picture(client, base_url, content) for content in unique.values()]
    wall_times = [float(item["wall_seconds"]) for item in picture_results]
    aggregate_keys = (
        "pixels",
        "compressed_bytes",
        "markdown_bytes",
        "json_bytes",
        "blocks",
        "tokenized_words",
        "characters",
        "bbox_count",
    )
    aggregate = {
        key: sum(int(item[key]) for item in picture_results) for key in aggregate_keys
    }
    result: dict[str, Any] = dict(parent)
    result.update(
        {
            "case": label,
            "unique_picture_assets": len(unique),
            "picture_ocr_wall_seconds_total": round(sum(wall_times), 3),
            "picture_ocr_wall_seconds_max": round(max(wall_times, default=0.0), 3),
            "picture_ocr_wall_seconds_median": round(
                statistics.median(wall_times) if wall_times else 0.0,
                3,
            ),
            "aggregate": aggregate,
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    args = parser.parse_args()
    api_key = args.api_key_file.read_text(encoding="ascii").strip()
    if not api_key:
        raise RuntimeError("layout_benchmark_api_key_missing")
    base_url = args.base_url.rstrip("/")
    cases = (
        ("typical-docx", args.samples / "typical.docx"),
        ("typical-pptx", args.samples / "typical.pptx"),
        ("boundary-docx", args.samples / "boundary.docx"),
        ("boundary-pptx", args.samples / "boundary.pptx"),
    )
    started = time.monotonic()
    with httpx.Client(
        headers={"Accept": "application/json, application/zip", "X-Api-Key": api_key},
        timeout=httpx.Timeout(30, read=30),
    ) as client:
        results = [_case(client, base_url, label, path) for label, path in cases]
    print(
        json.dumps(
            {
                "benchmark": "passed",
                "total_wall_seconds": round(time.monotonic() - started, 3),
                "cases": results,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
