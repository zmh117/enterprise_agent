from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.bootstrap import Container, ContainerFactory, build_api_container
from app.modules.agent.infrastructure.claude_code_agent_client import is_claude_cli_available
from app.modules.agent.infrastructure.typescript_runtime_client import (
    RuntimeClientSettings,
    probe_runtime_readiness,
)
from app.shared.config import Settings, load_settings, synchronize_feature_configuration
from app.shared.database import Database
from app.shared.database import default_migrations_dir
from app.shared.logging import configure_logging, set_correlation_id
from app.shared.migrations import SchemaHeadError, SchemaHeadValidator
from app.modules.platform_config.infrastructure.runtime_generation_repository import (
    RuntimeGenerationRepository,
)


class FallbackApp:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes


def _build_health(settings: Settings) -> dict[str, Any]:
    return {
        "status": "ok",
        "claude_invoked": False,
    }


def _build_readiness(
    settings: Settings,
    *,
    database: Database | None = None,
) -> dict[str, Any]:
    owned_database = database is None
    database = database or Database(settings.database_dsn)
    database_ready = database.ping()
    schema_ready = False
    schema_head = ""
    if database_ready:
        try:
            schema_head = SchemaHeadValidator(
                database,
                default_migrations_dir(),
            ).require_current()
            schema_ready = True
        except SchemaHeadError:
            schema_ready = False
    rabbitmq_ready = _check_rabbitmq(settings.rabbitmq_url)
    master_key_ready = bool(settings.app_config_master_key)
    token_required = settings.feature_real_internal_tools
    token_ready = (
        not token_required
        or bool(settings.internal_api_auth_token_file)
    )
    agent_runtime = _check_agent_runtime(settings)
    typescript_environment = settings.environment.strip().lower() in {
        item.strip().lower()
        for item in settings.agent_runtime.typescript_environments
        if item.strip()
    }
    typescript_required = typescript_environment or bool(
        settings.agent_runtime.typescript_application_publication_ids
    )
    core_ready = all(
        (
            database_ready,
            schema_ready,
            rabbitmq_ready,
            master_key_ready,
            token_ready,
            (not typescript_required or agent_runtime["ready"]),
        )
    )
    try:
        governed_runtime = RuntimeGenerationRepository(
            database
        ).public_status()
    except Exception:
        governed_runtime = {
            "status": "UNAVAILABLE",
            "resources": [],
            "applications": [],
        }
    result = {
        "status": "ready" if core_ready else "not_ready",
        "core": {
            "database": database_ready,
            "schema": schema_ready,
            "schema_head": schema_head,
            "rabbitmq": rabbitmq_ready,
            "internal_api_token": token_ready,
            "master_key": master_key_ready,
            "runtime_assembly": True,
            "agent_runtime": agent_runtime,
        },
        "resources": governed_runtime,
        "claude_invoked": False,
        "mcp_invoked": False,
        "runtime_selection": {
            "default_runtime": "typescript-v1" if typescript_environment else "python-v1",
            "typescript_required": typescript_required,
            "typescript_canary_publication_count": len(
                settings.agent_runtime.typescript_application_publication_ids
            ),
            "protocol_version": "1.0",
        },
        **_runtime_config_status(settings),
    }
    if owned_database:
        database.close()
    return result


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


def _check_agent_runtime(settings: Settings) -> dict[str, Any]:
    if not settings.agent_runtime.base_url:
        return {
            "configured": False,
            "ready": False,
            "identity": "not_configured",
            "database": "unavailable",
            "master_key": "unavailable",
            "runtime_version": "",
            "protocol_version": "",
            "sdk_version": "",
            "cli_version": "",
            "model_invoked": False,
            "mcp_invoked": False,
        }
    return probe_runtime_readiness(
        RuntimeClientSettings(
            base_url=settings.agent_runtime.base_url,
            tool_mcp_url=settings.runtime_tool_mcp.server_url,
            allowed_runtime_hosts=settings.agent_runtime.allowed_hosts,
            allow_insecure_internal_http=(
                settings.agent_runtime.allow_insecure_internal_http
            ),
        )
    )


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
        "internal_api_auth_token_file_configured": bool(
            settings.internal_api_auth_token_file
        ),
    }


def _runtime_config_status(settings: Settings) -> dict[str, Any]:
    return {
        "runtime_config": {
            "source": settings.runtime_config_source,
            "degraded": settings.runtime_config_degraded,
            "revision": settings.runtime_config_revision,
            "config_hash": settings.runtime_config_hash,
            "errors": list(settings.runtime_config_errors),
        },
        "feature_configuration": settings.feature_configuration.to_snapshot(
            revision=settings.runtime_config_revision,
            config_hash=settings.runtime_config_hash,
            source=settings.runtime_config_source,
        ),
    }


def _build_api_runtime(settings: Settings) -> Container:
    return build_api_container(
        settings,
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
    settings = synchronize_feature_configuration(settings or load_settings())
    configure_logging()

    try:
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse
    except ModuleNotFoundError:
        return FallbackApp(
            routes={
                "GET /api/health": lambda: _build_health(settings),
                "GET /api/ready": lambda: _build_readiness(settings),
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
                "message": _request_validation_message(error),
            }
            for error in exc.errors()
        ]
        if request.url.path.startswith("/api/admin"):
            return JSONResponse(
                status_code=422,
                content={
                    "detail": {
                        "code": "validation_failed",
                        "message": "请求参数校验失败",
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
                        "msg": _request_validation_message(error),
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
        status = _build_readiness(
            runtime_settings,
            database=container.database,
        )
        if status["status"] != "ready":
            raise HTTPException(status_code=503, detail=status)
        return status

    from app.modules.business_application.api import build_business_application_router
    from app.modules.authorization_center.api import build_authorization_center_router
    from app.modules.admin.api import build_admin_router
    from app.modules.agent_config.api import build_agent_config_router
    from app.modules.model_connection.api import build_model_connection_router
    from app.modules.api_capability.api import (
        build_api_capability_router,
        build_api_connection_router,
    )
    from app.modules.dingding.api.dingding_webhook_controller import build_dingding_router
    from app.modules.identity.api import (
        build_auth_router,
        build_external_credential_router,
        build_identity_admin_router,
    )
    from app.modules.identity_discovery.api import build_identity_discovery_router
    from app.modules.job.api.agent_job_debug_controller import build_agent_job_debug_router
    from app.modules.platform_config.api import build_platform_config_router
    from app.modules.workflow.api import build_workflow_router
    from app.modules.webhook.api import (
        build_public_webhook_router,
        build_webhook_admin_router,
    )
    from app.modules.managed_channel.api import (
        build_managed_channel_router,
        build_runtime_control_router,
    )

    app.include_router(build_dingding_router())
    app.include_router(build_agent_job_debug_router())
    app.include_router(build_platform_config_router())
    app.include_router(build_workflow_router())
    app.include_router(build_public_webhook_router())
    app.include_router(build_runtime_control_router())

    management_surface_enabled = any(
        (
            settings.feature_configuration.web_admin_enabled,
            settings.feature_configuration.unified_identity_enabled,
            settings.feature_configuration.business_application_control_plane_enabled,
        )
    )
    if management_surface_enabled:
        app.include_router(build_business_application_router())
        app.include_router(build_authorization_center_router())
        app.include_router(build_admin_router())
        app.include_router(build_agent_config_router())
        app.include_router(build_model_connection_router())
        app.include_router(build_api_connection_router())
        app.include_router(build_api_capability_router())
        app.include_router(build_auth_router())
        app.include_router(build_external_credential_router())
        app.include_router(build_identity_admin_router())
        app.include_router(build_identity_discovery_router())
        app.include_router(build_webhook_admin_router())
        app.include_router(build_managed_channel_router())

    return app


def _request_validation_message(error: dict[str, Any]) -> str:
    messages = {
        "missing": "此字段为必填项",
        "string_type": "必须填写文本",
        "string_too_short": "文本长度不足",
        "string_too_long": "文本长度超出限制",
        "int_type": "必须填写整数",
        "int_parsing": "必须填写整数",
        "float_type": "必须填写数字",
        "float_parsing": "必须填写数字",
        "bool_type": "必须填写布尔值",
        "bool_parsing": "必须填写布尔值",
        "list_type": "必须填写列表",
        "dict_type": "必须填写对象",
        "json_invalid": "不是有效的 JSON",
        "literal_error": "字段值不在允许范围内",
        "enum": "字段值不在允许范围内",
        "greater_than": "字段值过小",
        "greater_than_equal": "字段值过小",
        "less_than": "字段值过大",
        "less_than_equal": "字段值过大",
    }
    return messages.get(str(error.get("type") or ""), "字段值无效")
