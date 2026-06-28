from __future__ import annotations

from typing import Any

from app.shared.config import Settings, load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.logging import configure_logging, set_correlation_id


class FallbackApp:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes


def _build_health(settings: Settings) -> dict[str, Any]:
    database = Database(settings.database_dsn)
    return {
        "status": "ok",
        "database": database.ping(),
        "rabbitmq": _check_rabbitmq(settings.rabbitmq_url),
        "claude_invoked": False,
    }


def _check_rabbitmq(rabbitmq_url: str) -> bool:
    try:
        import pika
    except ModuleNotFoundError:
        return False
    try:
        connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        connection.close()
        return True
    except Exception:
        return False


def create_app(settings: Settings | None = None) -> Any:
    settings = settings or load_settings()
    configure_logging()

    try:
        from fastapi import FastAPI, HTTPException, Request
    except ModuleNotFoundError:
        return FallbackApp(
            routes={
                "GET /api/health": lambda: _build_health(settings),
                "GET /api/ready": lambda: _build_health(settings),
            }
        )

    app = FastAPI(title="Enterprise Agent", version="0.1.0")

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next: Any) -> Any:
        correlation_id = request.headers.get("x-correlation-id")
        set_correlation_id(correlation_id)
        response = await call_next(request)
        response.headers["x-correlation-id"] = correlation_id or "-"
        return response

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "claude_invoked": False}

    @app.get("/api/ready")
    def ready() -> dict[str, Any]:
        status = _build_health(settings)
        if not status["database"] or not status["rabbitmq"]:
            raise HTTPException(status_code=503, detail=status)
        return status

    try:
        from app.modules.dingding.api.dingding_webhook_controller import (
            build_dingding_router,
        )

        app.include_router(build_dingding_router(settings))
    except Exception:
        # Optional route construction depends on migrations/config during early bootstrap.
        pass

    @app.post("/api/admin/migrate")
    def migrate() -> dict[str, Any]:
        Database(settings.database_dsn).run_migrations(default_migrations_dir())
        return {"status": "migrated"}

    return app
