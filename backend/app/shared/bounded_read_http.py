"""知识只读调用内的 HTTP 总超时；固定目标、认证和业务解析仍由原客户端拥有。"""

import asyncio
from contextvars import ContextVar
import logging

import httpx

from app.shared.database import assert_external_io_allowed
from app.shared.ones_io_budget import ones_io_timeout
from app.shared.bounded_dns import ResolverEventLoop
from app.shared.io_deadline import POLL_SECONDS, current_io_deadline, io_wait_timeout

_QUIET: ContextVar[bool] = ContextVar("bounded_read_quiet_http", default=False)


class _QuietReadFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # httpx INFO 会记录完整 URL；httpcore DEBUG 还可能记录连接细节。
        # 只抑制本次有界读取的库日志，保留调用者的安全结果审计，不影响其他调用。
        return not _QUIET.get()


_FILTER = _QuietReadFilter()


def _quiet_library_logs() -> None:
    for name in ("httpx", *tuple(logging.Logger.manager.loggerDict)):
        if name == "httpx" or name == "httpcore" or name.startswith("httpcore."):
            logging.getLogger(name).addFilter(_FILTER)


def request_bytes(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    content: bytes | None,
    timeout: float,
    max_bytes: int,
) -> tuple[int, bytes]:
    """同步服务线程入口；超时取消网络协程并关闭连接，不放弃仍在运行的 HTTP 线程。"""
    assert_external_io_allowed("bounded_knowledge_read")
    seconds = io_wait_timeout(ones_io_timeout(timeout))

    async def run() -> tuple[int, bytes]:
        async with asyncio.timeout(seconds):
            async with httpx.AsyncClient(
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(seconds, connect=min(seconds, 3)),
            ) as client:
                _quiet_library_logs()
                async with client.stream(
                    method,
                    url,
                    content=content,
                    headers={**headers, "Accept-Encoding": "identity"},
                ) as response:
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise ValueError("bounded_response_encoding_invalid")
                    body = bytearray()
                    async for part in response.aiter_raw():
                        body.extend(part)
                        if len(body) > max_bytes:
                            raise ValueError("bounded_response_too_large")
                    return response.status_code, bytes(body)

    async def cancellable() -> tuple[int, bytes]:
        budget = current_io_deadline()

        async def cancelled() -> None:
            while True:
                await asyncio.sleep(POLL_SECONDS)
                if budget is not None:
                    budget.check()

        request = asyncio.create_task(run())
        monitor = asyncio.create_task(cancelled())
        try:
            done, _ = await asyncio.wait({request, monitor}, return_when=asyncio.FIRST_COMPLETED)
            if monitor in done:
                await monitor
            result = await request
            if budget is not None:
                budget.check()
            return result
        finally:
            request.cancel()
            monitor.cancel()
            await asyncio.gather(request, monitor, return_exceptions=True)

    token = _QUIET.set(True)
    try:
        with asyncio.Runner(loop_factory=ResolverEventLoop) as runner:
            return runner.run(cancellable())
    except TimeoutError:
        raise TimeoutError("bounded_read_timeout") from None
    except httpx.TransportError:
        raise OSError("bounded_read_unavailable") from None
    finally:
        _QUIET.reset(token)
