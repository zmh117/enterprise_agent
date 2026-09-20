"""Deadline and disconnect handling for the two internal knowledge HTTP hops."""

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
import threading
import time

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Message

from app.modules.knowledge.application.retrieval_budget import (
    DEADLINE_HEADER,
    MAX_RETRIEVAL_SECONDS,
    deadline_from_headers,
    entry_budget,
)
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.shared.io_deadline import IODeadlineExceeded, io_deadline


def bounded_knowledge_request(
    handler: Callable[[Request], Awaitable[JSONResponse]],
) -> Callable[[Request], Awaitable[JSONResponse]]:
    @wraps(handler)
    async def wrapped(request: Request) -> JSONResponse:
        try:
            incoming = deadline_from_headers(request.headers.getlist(DEADLINE_HEADER))
        except KnowledgeGovernanceError:
            return JSONResponse(
                {"error_code": "knowledge_input_invalid", "message": "知识请求格式无效"},
                status_code=400,
                headers={"Cache-Control": "no-store"},
            )
        seconds = (
            min(MAX_RETRIEVAL_SECONDS, incoming / 1000 - time.time())
            if incoming is not None
            else MAX_RETRIEVAL_SECONDS
        )
        cancelled = threading.Event()
        messages: asyncio.Queue[Message] = asyncio.Queue(maxsize=1)

        async def receive() -> None:
            while True:
                message = await request.receive()
                if message["type"] == "http.disconnect":
                    cancelled.set()
                await messages.put(message)
                if message["type"] == "http.disconnect":
                    return

        reader = asyncio.create_task(receive())
        try:
            with entry_budget(incoming), io_deadline(seconds, cancelled=cancelled.is_set):
                async with asyncio.timeout(max(0, seconds)):
                    return await handler(Request(request.scope, receive=messages.get))
        except (TimeoutError, IODeadlineExceeded):
            return JSONResponse(
                {
                    "error_code": "knowledge_search_budget_exhausted",
                    "message": "知识读取超时或已取消，请重试",
                },
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        except KnowledgeGovernanceError as exc:
            if exc.error_code != "knowledge_search_budget_exhausted":
                raise
            return JSONResponse(
                {"error_code": exc.error_code, "message": exc.safe_message},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        finally:
            cancelled.set()
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)

    return wrapped
