from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Final

from fastapi import FastAPI, Request
from fastapi.responses import Response


MAX_PROXY_RESPONSE_BYTES: Final = 2_200_000
RETRY_MARKER: Final = "[acceptance:retry-once]"
FORWARDED_HEADERS: Final = frozenset(
    {
        "accept",
        "authorization",
        "content-type",
        "x-correlation-id",
    }
)


def create_app() -> FastAPI:
    upstream = os.environ.get("RUNTIME_FAULT_PROXY_UPSTREAM", "").strip().rstrip("/")
    if upstream not in {
        "http://python-agent-runtime:8091",
        "http://typescript-agent-runtime:8090",
    }:
        raise RuntimeError("acceptance Runtime fault proxy upstream is invalid")

    app = FastAPI(title="Dual Runtime acceptance fault proxy")

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST"],
    )
    async def forward(path: str, request: Request) -> Response:
        body = await request.body()
        if _must_fail_first_job_attempt(path=path, method=request.method, body=body):
            return Response(
                content=b'{"error":"acceptance_runtime_temporarily_unavailable"}',
                status_code=503,
                media_type="application/json",
            )
        target = f"{upstream}/{path}"
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() in FORWARDED_HEADERS
        }
        outbound = urllib.request.Request(
            target,
            data=body if request.method == "POST" else None,
            headers=headers,
            method=request.method,
        )
        try:
            response = urllib.request.urlopen(outbound, timeout=330)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            content = response.read(MAX_PROXY_RESPONSE_BYTES + 1)
            if len(content) > MAX_PROXY_RESPONSE_BYTES:
                return Response(
                    content=b'{"error":"acceptance_proxy_response_too_large"}',
                    status_code=502,
                    media_type="application/json",
                )
            content_type = str(response.headers.get("content-type") or "")
            return Response(
                content=content,
                status_code=int(response.status),
                headers={"content-type": content_type} if content_type else None,
            )

    return app


def _must_fail_first_job_attempt(*, path: str, method: str, body: bytes) -> bool:
    if method != "POST" or path.rstrip("/") != "internal/v1/executions":
        return False
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    prompt = payload.get("prompt")
    question = prompt.get("user_question") if isinstance(prompt, dict) else ""
    invocation_id = str(payload.get("invocation_id") or "")
    return RETRY_MARKER in str(question) and invocation_id.endswith(".attempt-0")
