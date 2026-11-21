"""Bounded internal recording transport with fixed service endpoints."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.modules.channel.browser.http import deny
from app.shared.database import assert_external_io_allowed


def internal_request(
    base: str,
    hosts: tuple[str, ...],
    path: str,
    token: str,
    *,
    body: bytes,
    media: str,
    timeout: int,
    method: str = "POST",
) -> dict[str, Any]:
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in hosts
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise deny("application_unavailable", 503)
    assert_external_io_allowed("browser_recording.internal_request")
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=timeout) as client:
            with client.stream(
                method,
                base.rstrip("/") + path,
                content=body,
                headers={
                    "Authorization": "Bearer " + token,
                    "Content-Type": media,
                    "Accept-Encoding": "identity",
                },
            ) as result:
                if result.status_code in (401, 403, 404, 409, 410):
                    raise deny("access_denied", 403)
                if (
                    result.status_code != 200
                    or result.headers.get("content-encoding", "identity") != "identity"
                ):
                    raise deny("application_unavailable", 503)
                data = bytearray()
                for chunk in result.iter_bytes(32768):
                    if len(data) + len(chunk) > 1024 * 1024 + 4096:
                        raise deny("application_unavailable", 503)
                    data.extend(chunk)
                value = json.loads(data)
                if not isinstance(value, dict):
                    raise ValueError
                return value
    except (httpx.HTTPError, ValueError):
        raise deny("application_unavailable", 503) from None


def write_part(c: Any, rec: dict[str, Any], part: dict[str, Any], raw: bytes) -> None:
    issuer = c.service_principal_token_issuer
    if not issuer:
        raise deny("application_unavailable", 503)
    rid, number, digest = rec["id"], part["part_number"], part["sha256"]
    token = issuer.recording_write(
        scope=rec["scope_ref"], recording=rid, part=number, digest=digest
    )
    cfg = c.settings.file_service
    reply = internal_request(
        cfg.internal_base_url,
        cfg.internal_allowed_hosts,
        f"/internal/v1/browser-recordings/{rid}/parts/{number}",
        token,
        body=raw,
        media="application/x-ndjson",
        timeout=cfg.internal_timeout_seconds,
        method="PUT",
    )
    if reply != {"recording_id": rid, "number": number, "sha256": digest}:
        raise deny("application_unavailable", 503)
