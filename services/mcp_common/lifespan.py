from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any


def install_sync_lifespan_hooks(
    app: Any,
    *,
    start: Callable[[], None],
    close: Callable[[], None],
) -> None:
    """Compose synchronous service hooks with an app's existing ASGI lifespan."""

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: Any):
        async with original_lifespan(application) as state:
            start()
            try:
                yield state
            finally:
                close()

    app.router.lifespan_context = lifespan
