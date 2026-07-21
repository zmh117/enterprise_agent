from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.bootstrap import Container, ContainerFactory, build_api_container
from app.modules.agent.infrastructure.claude_code_agent_client import is_claude_cli_available
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
        **_claude_runtime_status(settings),
        **_internal_tools_status(settings),
        **_runtime_config_status(settings),
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


def _claude_runtime_status(settings: Settings) -> dict[str, Any]:
    return {
        "feature_real_claude": settings.feature_real_claude,
        "anthropic_api_key_configured": bool(settings.anthropic_api_key),
        "claude_cli_available": is_claude_cli_available(),
    }


def _internal_tools_status(settings: Settings) -> dict[str, Any]:
    return {
        "feature_real_internal_tools": settings.feature_real_internal_tools,
        "internal_api_base_url_configured": bool(settings.internal_api_base_url),
        "internal_api_auth_token_configured": bool(settings.internal_api_auth_token),
    }


def _runtime_config_status(settings: Settings) -> dict[str, Any]:
    return {
        "runtime_config": {
            "source": settings.runtime_config_source,
            "degraded": settings.runtime_config_degraded,
            "revision": settings.runtime_config_revision,
            "config_hash": settings.runtime_config_hash,
            "errors": list(settings.runtime_config_errors),
        }
    }


def _build_api_runtime(settings: Settings) -> Container:
    return build_api_container(
        settings,
        migrate=settings.app_startup_migrate,
        seed=settings.seed_local_config,
    )


def _app_container(app: Any) -> Container:
    container = getattr(app.state, "container", None)
    if not isinstance(container, Container):
        raise RuntimeError("Application container is not initialized")
    return container


def create_app(
    settings: Settings | None = None,
    container_factory: ContainerFactory | None = None,
) -> Any:
    settings = settings or load_settings()
    configure_logging()

    try:
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse
    except ModuleNotFoundError:
        return FallbackApp(
            routes={
                "GET /api/health": lambda: _build_health(settings),
                "GET /api/ready": lambda: _build_health(settings),
            }
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        factory = container_factory or _build_api_runtime
        container = factory(settings)
        app.state.container = container
        try:
            yield
        finally:
            container.database.close()

    app = FastAPI(title="Enterprise Agent", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", "-")
        field_errors = [
            {
                "field": ".".join(str(item) for item in (error.get("loc") or ())[1:]),
                "message": str(error.get("msg") or "Invalid value"),
            }
            for error in exc.errors()
        ]
        if request.url.path.startswith("/api/admin"):
            return JSONResponse(
                status_code=422,
                content={
                    "detail": {
                        "code": "validation_failed",
                        "message": "Request validation failed",
                        "field_errors": field_errors,
                        "correlation_id": correlation_id,
                    }
                },
                headers={"x-correlation-id": correlation_id},
            )
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {
                        "loc": list(error.get("loc") or ()),
                        "msg": str(error.get("msg") or "Invalid value"),
                        "type": str(error.get("type") or "value_error"),
                    }
                    for error in exc.errors()
                ]
            },
        )

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next: Any) -> Any:
        correlation_id = set_correlation_id(request.headers.get("x-correlation-id"))
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["x-correlation-id"] = correlation_id
        return response

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "claude_invoked": False}

    @app.get("/api/ready")
    def ready() -> dict[str, Any]:
        container = _app_container(app)
        runtime_settings = container.settings
        status = {
            "status": "ok",
            "database": container.database.ping(),
            "rabbitmq": _check_rabbitmq(runtime_settings.rabbitmq_url),
            "claude_invoked": False,
            **_claude_runtime_status(runtime_settings),
            **_internal_tools_status(runtime_settings),
            **_runtime_config_status(runtime_settings),
        }
        if not status["database"] or not status["rabbitmq"]:
            raise HTTPException(status_code=503, detail=status)
        return status

    from app.modules.channel.api.channel_webhook_controller import build_channel_router
    from app.modules.admin.api import build_admin_router
    from app.modules.agent_config.api import build_agent_config_router
    from app.modules.dingding.api.dingding_webhook_controller import build_dingding_router
    from app.modules.identity.api import build_auth_router, build_identity_admin_router
    from app.modules.job.api.agent_job_debug_controller import build_agent_job_debug_router
    from app.modules.platform_config.api import build_platform_config_router
    from app.modules.workflow.api import build_workflow_router
    from app.modules.webhook.api import (
        build_public_webhook_router,
        build_webhook_admin_router,
    )

    app.include_router(build_channel_router())
    app.include_router(build_admin_router())
    app.include_router(build_agent_config_router())
    app.include_router(build_dingding_router())
    app.include_router(build_agent_job_debug_router())
    app.include_router(build_auth_router())
    app.include_router(build_identity_admin_router())
    app.include_router(build_platform_config_router())
    app.include_router(build_workflow_router())
    app.include_router(build_public_webhook_router())
    app.include_router(build_webhook_admin_router())

    @app.post("/api/admin/migrate")
    def migrate(request: Request) -> dict[str, Any]:
        from app.modules.identity.api.dependencies import require_action

        require_action(
            request,
            resource_type="platform_config",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        _app_container(app).database.run_migrations(default_migrations_dir())
        return {"status": "migrated"}

    return app
