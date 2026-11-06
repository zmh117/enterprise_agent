"""Metadata-only Runtime source authorization; never serves source or file bytes."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.modules.knowledge.infrastructure.code_source_grant import CODE_SOURCE_GRANT_PATH
from app.modules.knowledge.domain.code_package import parse_json
from app.modules.knowledge.api.readability_controller import _bearer
from app.shared.exceptions import AppError


def build_code_runtime_router() -> APIRouter:
    router = APIRouter()

    @router.post(CODE_SOURCE_GRANT_PATH)
    async def source_grant(request: Request) -> JSONResponse:
        runtime = request.app.state.container
        verifier = getattr(runtime, "code_runtime_verifier", None)
        grant = getattr(runtime, "code_source_grant", None)
        headers = {"Cache-Control": "no-store"}
        if verifier is None or grant is None:
            return JSONResponse({"error_code": "code_runtime_unavailable"}, 503, headers=headers)
        try:
            if (
                request.headers.getlist("host") not in (["api-server"], ["api-server:8000"])
                or "origin" in request.headers
                or "cookie" in request.headers
                or request.url.query
            ):
                raise ValueError
            await run_in_threadpool(verifier.verify, _bearer(request, "authorization"))
            if request.headers.getlist("content-type") != ["application/json"]:
                raise ValueError
            body = bytearray()
            async for part in request.stream():
                if len(body) + len(part) > 1024:
                    raise ValueError
                body.extend(part)
            value = parse_json(body.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError
            result = await run_in_threadpool(grant.check_invocation, value)
            return JSONResponse(result, headers=headers)
        except (ValueError, AppError):
            return JSONResponse({"error_code": "code_source_denied"}, 403, headers=headers)
        except Exception:
            return JSONResponse({"error_code": "code_runtime_unavailable"}, 503, headers=headers)

    return router
