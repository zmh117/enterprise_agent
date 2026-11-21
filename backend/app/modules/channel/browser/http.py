from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


def deny(code: str, status: int = 401) -> HTTPException:
    return HTTPException(status, {"code": code}, headers={"Cache-Control": "no-store"})


class BrowserRoute(APIRoute):
    """Return the public Error contract without reflecting submitted fields."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()

        async def request_handler(request: Request) -> Response:
            try:
                return await handle(request)
            except RequestValidationError:
                return JSONResponse({"code": "invalid_request"}, 422, {"Cache-Control": "no-store"})
            except HTTPException as exc:
                if isinstance(exc.detail, dict) and "code" in exc.detail:
                    body = exc.detail
                elif exc.status_code == 429:
                    body = {"code": "rate_limited"}
                else:
                    raise
                return JSONResponse(body, exc.status_code, {"Cache-Control": "no-store"})

        return request_handler
