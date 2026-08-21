#!/usr/bin/env python3
"""Probe the fixed Docling Office picture-bundle wire contract with synthetic data.

The probe prints only structural counts, schema keys, media types, and byte sizes.
It never prints credentials, task IDs, source names, extracted text, or image bytes.
"""

from __future__ import annotations

import argparse
import json
import stat
import time
import zipfile
from collections import Counter
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from PIL import Image


MAX_RESPONSE_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 512
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
ALLOWED_SUFFIXES = frozenset({".json", ".md", ".png", ".jpg", ".jpeg", ".webp"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def _safe_member_name(value: str) -> PurePosixPath:
    if not value or "\\" in value:
        raise RuntimeError("bundle_member_path_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError("bundle_member_path_invalid")
    return path


def _bounded_result(client: httpx.Client, base_url: str, task_id: str) -> bytes:
    with client.stream("GET", f"{base_url}/v1/result/{task_id}") as response:
        response.raise_for_status()
        if response.headers.get("content-type", "").split(";", 1)[0] != "application/zip":
            raise RuntimeError("bundle_media_type_invalid")
        content_length = response.headers.get("content-length")
        if content_length is not None and int(content_length) > MAX_RESPONSE_BYTES:
            raise RuntimeError("bundle_response_too_large")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise RuntimeError("bundle_response_too_large")
            chunks.append(chunk)
    return b"".join(chunks)


def _wait_for_result(client: httpx.Client, base_url: str, task_id: str) -> None:
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        response = client.get(f"{base_url}/v1/status/poll/{task_id}")
        response.raise_for_status()
        payload = response.json()
        state = str(payload.get("task_status") or "")
        if state == "success":
            return
        if state == "failure":
            raise RuntimeError("bundle_conversion_failed")
        if state not in {"pending", "started"}:
            raise RuntimeError("bundle_task_state_invalid")
        time.sleep(1)
    raise RuntimeError("bundle_probe_timeout")


def _read_json_member(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> dict[str, Any]:
    if member.file_size > MAX_RESPONSE_BYTES:
        raise RuntimeError("bundle_json_too_large")
    value = json.loads(archive.read(member))
    if not isinstance(value, dict):
        raise RuntimeError("bundle_json_schema_invalid")
    return value


def _resolve_json_ref(document: dict[str, Any], value: object) -> object | None:
    if not isinstance(value, str) or not value.startswith("#/"):
        return None
    current: object = document
    for raw_part in value[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _child_refs(value: object) -> set[str]:
    if not isinstance(value, dict) or not isinstance(value.get("children"), list):
        return set()
    refs: set[str] = set()
    for child in value["children"]:
        if isinstance(child, dict) and isinstance(child.get("$ref"), str):
            refs.add(child["$ref"])
    return refs


def _picture_summary(document: dict[str, Any], archive_paths: set[str]) -> dict[str, Any]:
    pictures = document.get("pictures")
    if not isinstance(pictures, list):
        raise RuntimeError("bundle_picture_collection_missing")
    picture_keys: set[str] = set()
    provenance_keys: set[str] = set()
    image_keys: set[str] = set()
    media_types: set[str] = set()
    self_ref_count = 0
    parent_ref_count = 0
    provenance_count = 0
    page_anchor_count = 0
    bbox_count = 0
    image_ref_count = 0
    resolved_image_ref_count = 0
    parent_resolved_count = 0
    parent_child_link_count = 0
    parent_labels: set[str] = set()
    for picture in pictures:
        if not isinstance(picture, dict):
            raise RuntimeError("bundle_picture_schema_invalid")
        picture_keys.update(str(key) for key in picture)
        if isinstance(picture.get("self_ref"), str):
            self_ref_count += 1
        parent = picture.get("parent")
        if isinstance(parent, dict) and isinstance(parent.get("$ref"), str):
            parent_ref_count += 1
            resolved_parent = _resolve_json_ref(document, parent["$ref"])
            if resolved_parent is not None:
                parent_resolved_count += 1
                if isinstance(resolved_parent, dict):
                    label = resolved_parent.get("label")
                    if isinstance(label, str):
                        parent_labels.add(label)
                    if picture.get("self_ref") in _child_refs(resolved_parent):
                        parent_child_link_count += 1
        provenance = picture.get("prov")
        if isinstance(provenance, list):
            provenance_count += len(provenance)
            for item in provenance:
                if not isinstance(item, dict):
                    continue
                provenance_keys.update(str(key) for key in item)
                if isinstance(item.get("page_no"), int):
                    page_anchor_count += 1
                if isinstance(item.get("bbox"), dict):
                    bbox_count += 1
        image = picture.get("image")
        if isinstance(image, dict):
            image_ref_count += 1
            image_keys.update(str(key) for key in image)
            mimetype = image.get("mimetype")
            if isinstance(mimetype, str):
                media_types.add(mimetype)
            uri = image.get("uri")
            if isinstance(uri, str) and not uri.startswith(("data:", "http:", "https:")):
                normalized = str(_safe_member_name(uri))
                if normalized in archive_paths:
                    resolved_image_ref_count += 1
    return {
        "picture_count": len(pictures),
        "picture_keys": sorted(picture_keys),
        "picture_self_ref_count": self_ref_count,
        "picture_parent_ref_count": parent_ref_count,
        "picture_parent_resolved_count": parent_resolved_count,
        "picture_parent_child_link_count": parent_child_link_count,
        "picture_parent_labels": sorted(parent_labels),
        "picture_provenance_count": provenance_count,
        "picture_page_anchor_count": page_anchor_count,
        "picture_bbox_count": bbox_count,
        "picture_image_ref_count": image_ref_count,
        "resolved_image_ref_count": resolved_image_ref_count,
        "picture_provenance_keys": sorted(provenance_keys),
        "picture_image_keys": sorted(image_keys),
        "picture_media_types": sorted(media_types),
    }


def _probe_case(
    *,
    client: httpx.Client,
    base_url: str,
    source: Path,
    format_code: str,
    media_type: str,
    include_page_images: bool = False,
) -> dict[str, Any]:
    with source.open("rb") as stream:
        response = client.post(
            f"{base_url}/v1/convert/file/async",
            data={
                "from_formats": format_code,
                "to_formats": ["md", "json"],
                "image_export_mode": "referenced",
                "include_images": "true",
                "include_page_images": "true" if include_page_images else "false",
                "do_ocr": "true",
                "force_ocr": "false",
                "do_table_structure": "true",
                "abort_on_error": "false",
                "do_picture_description": "false",
                "do_picture_classification": "false",
                "do_chart_extraction": "false",
                "do_code_enrichment": "false",
                "do_formula_enrichment": "false",
                "target_type": "zip",
            },
            files={"files": ("synthetic-input", stream, media_type)},
        )
    response.raise_for_status()
    task_id = str(response.json().get("task_id") or "")
    if not task_id or any(character in task_id for character in "/\\\r\n"):
        raise RuntimeError("bundle_task_identity_invalid")
    _wait_for_result(client, base_url, task_id)
    bundle = _bounded_result(client, base_url, task_id)

    with zipfile.ZipFile(BytesIO(bundle)) as archive:
        members = archive.infolist()
        if not 1 <= len(members) <= MAX_ARCHIVE_ENTRIES:
            raise RuntimeError("bundle_entry_count_invalid")
        normalized_names: list[str] = []
        total_uncompressed = 0
        suffix_counts: Counter[str] = Counter()
        json_members: list[zipfile.ZipInfo] = []
        image_members = 0
        image_dimensions: set[tuple[int, int]] = set()
        for member in members:
            path = _safe_member_name(member.filename.rstrip("/"))
            normalized = str(path)
            if normalized in normalized_names:
                raise RuntimeError("bundle_member_duplicate")
            normalized_names.append(normalized)
            if stat.S_ISLNK(member.external_attr >> 16):
                raise RuntimeError("bundle_member_symlink")
            if member.is_dir():
                continue
            suffix = path.suffix.lower()
            if suffix not in ALLOWED_SUFFIXES:
                raise RuntimeError("bundle_member_type_invalid")
            suffix_counts[suffix] += 1
            total_uncompressed += member.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise RuntimeError("bundle_uncompressed_size_exceeded")
            if suffix == ".json":
                json_members.append(member)
            if suffix in IMAGE_SUFFIXES:
                image_members += 1
                with Image.open(BytesIO(archive.read(member))) as image:
                    image_dimensions.add((int(image.width), int(image.height)))
        if len(json_members) != 1:
            raise RuntimeError("bundle_json_count_invalid")
        document = _read_json_member(archive, json_members[0])
        if document.get("schema_name") != "DoclingDocument":
            raise RuntimeError("bundle_docling_schema_invalid")
        summary = _picture_summary(document, set(normalized_names))
        if summary["picture_count"] < 1 or image_members < 1:
            raise RuntimeError("bundle_picture_artifact_missing")
        summary.update(
            {
                "format": format_code,
                "archive_media_type": "application/zip",
                "compressed_bytes": len(bundle),
                "entry_count": len(members),
                "entry_suffix_counts": dict(sorted(suffix_counts.items())),
                "image_entry_count": image_members,
                "image_dimensions": [list(item) for item in sorted(image_dimensions)],
                "uncompressed_bytes": total_uncompressed,
                "path_validation": "passed",
                "bounded_download": "passed",
            }
        )
        return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--docx", type=Path, required=True)
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--include-page-images", action="store_true")
    args = parser.parse_args()
    api_key = args.api_key_file.read_text(encoding="ascii").strip()
    if not api_key:
        raise RuntimeError("bundle_probe_api_key_missing")
    headers = {"Accept": "application/json, application/zip", "X-Api-Key": api_key}
    with httpx.Client(headers=headers, timeout=httpx.Timeout(30, read=30)) as client:
        results = [
            _probe_case(
                client=client,
                base_url=args.base_url.rstrip("/"),
                source=args.docx,
                format_code="docx",
                media_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                include_page_images=args.include_page_images,
            ),
            _probe_case(
                client=client,
                base_url=args.base_url.rstrip("/"),
                source=args.pptx,
                format_code="pptx",
                media_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "presentationml.presentation"
                ),
                include_page_images=args.include_page_images,
            ),
        ]
    print(json.dumps({"contract_probe": "passed", "cases": results}, sort_keys=True))


if __name__ == "__main__":
    main()
