from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.request import urlopen

from fastapi import FastAPI

from app.shared.config import Settings, load_settings

from .loki_gateway import LokiGateway
from .routes import register_routes


def create_app(
    settings: Settings | None = None,
    *,
    urlopen_func: Callable[..., Any] = urlopen,
) -> FastAPI:
    settings = settings or load_settings()
    loki_gateway = LokiGateway(settings.loki, urlopen_func=urlopen_func)
    app = FastAPI(title="Local Internal API Platform", version="0.1.0")
    register_routes(app, settings=settings, loki_gateway=loki_gateway)
    return app
