"""OS resolver isolation for deadline-bound reads; no executor DNS threads."""

import asyncio
import json
from pathlib import Path
import socket
import sys
from typing import Any

from app.shared.io_deadline import CLEANUP_SECONDS, POLL_SECONDS, current_io_deadline


async def resolve(
    host: str | bytes,
    port: str | int | None,
    family: int = 0,
    kind: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> list[Any]:
    name = host.decode("ascii") if isinstance(host, bytes) else host
    # Numeric addresses never need a child, nor any OS name-service lookup.
    try:
        return socket.getaddrinfo(name, port, family, kind, proto, flags | socket.AI_NUMERICHOST)
    except socket.gaierror:
        pass
    worker = str(Path(__file__).with_name("dns_worker.py"))
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-S",
        worker,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={},
        limit=32768,
    )
    communication = asyncio.create_task(
        child.communicate(json.dumps([name, port, family, kind, proto, flags]).encode())
    )
    try:
        budget = current_io_deadline()
        while not communication.done():
            if budget is not None:
                budget.check()
            await asyncio.wait({communication}, timeout=POLL_SECONDS)
        raw, _ = await communication
        if child.returncode != 0 or len(raw) > 32768:
            raise OSError("bounded_dns_unavailable")
        return [(*row[:4], tuple(row[4])) for row in json.loads(raw)]
    finally:
        if child.returncode is None:
            child.kill()
            # Reap before returning: no abandoned resolver executor at loop shutdown.
            await asyncio.wait_for(child.wait(), CLEANUP_SECONDS)
        communication.cancel()
        await asyncio.gather(communication, return_exceptions=True)


class ResolverEventLoop(asyncio.SelectorEventLoop):
    async def getaddrinfo(
        self,
        host: Any,
        port: Any,
        *,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[Any]:
        return await resolve(host, port, family, type, proto, flags)
