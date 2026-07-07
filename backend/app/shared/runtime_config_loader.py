from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.modules.internal_api_platform.infrastructure.secrets import DbBackedSecretResolver
from app.modules.platform_config.application.runtime_config import RuntimeConfigRegistry
from app.modules.platform_config.application.runtime_config import RuntimeConfigSnapshotBuilder
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.config import Settings
from app.shared.database import Database, default_migrations_dir


def load_settings_with_db_overlay(
    settings: Settings,
    *,
    service_name: str,
    migrate: bool = True,
) -> Settings:
    try:
        database = Database(settings.database_dsn)
        try:
            if migrate:
                database.run_migrations(default_migrations_dir())
            return apply_runtime_config_overlay(settings, database, service_name=service_name)
        finally:
            database.close()
    except Exception as exc:
        return replace(
            settings,
            runtime_config_source="env-fallback",
            runtime_config_degraded=True,
            runtime_config_errors=(getattr(exc, "safe_message", str(exc)),),
        )


def apply_runtime_config_overlay(
    settings: Settings,
    database: Database,
    *,
    service_name: str,
) -> Settings:
    repository = PlatformConfigRepository(database)
    RuntimeConfigRegistry(repository).ensure_builtin_definitions()
    snapshot = RuntimeConfigSnapshotBuilder(repository).build_snapshot(service_name=service_name)
    effective = snapshot["effective"]
    errors = list(snapshot.get("errors") or [])
    resolver = DbBackedSecretResolver(repository, master_key=_bootstrap_master_key())

    def runtime_value(key: str) -> Any | None:
        item = effective.get(key) or {}
        if not str(item.get("source") or "").startswith("db:"):
            return None
        if item.get("secret_ref"):
            try:
                return resolver.resolve(str(item["secret_ref"]))
            except Exception as exc:
                errors.append(getattr(exc, "safe_message", str(exc)))
                return None
        return item.get("value")

    claude_model = runtime_value("CLAUDE_MODEL") or runtime_value("ANTHROPIC_MODEL")
    anthropic_api_key = runtime_value("ANTHROPIC_API_KEY") or runtime_value(
        "ANTHROPIC_AUTH_TOKEN"
    )
    updated = replace(
        settings,
        internal_api_base_url=_str(runtime_value("INTERNAL_API_BASE_URL"), settings.internal_api_base_url),
        internal_api_auth_token=_str(
            runtime_value("INTERNAL_API_AUTH_TOKEN"),
            settings.internal_api_auth_token,
        ),
        internal_api_timeout_seconds=_int(
            runtime_value("INTERNAL_API_TIMEOUT_SECONDS"),
            settings.internal_api_timeout_seconds,
        ),
        internal_api_max_response_chars=_int(
            runtime_value("INTERNAL_API_MAX_RESPONSE_CHARS"),
            settings.internal_api_max_response_chars,
        ),
        internal_platform_max_rows=_int(
            runtime_value("INTERNAL_PLATFORM_MAX_ROWS"),
            settings.internal_platform_max_rows,
        ),
        claude_model=_str(claude_model, settings.claude_model),
        anthropic_api_key=_str(anthropic_api_key, settings.anthropic_api_key),
        anthropic_base_url=_str(runtime_value("ANTHROPIC_BASE_URL"), settings.anthropic_base_url),
        feature_real_claude=_bool(runtime_value("FEATURE_REAL_CLAUDE"), settings.feature_real_claude),
        feature_real_internal_tools=_bool(
            runtime_value("FEATURE_REAL_INTERNAL_TOOLS"),
            settings.feature_real_internal_tools,
        ),
        runtime_config_source=str(snapshot["source"]),
        runtime_config_degraded=False,
        runtime_config_revision=int(snapshot.get("revision") or 0),
        runtime_config_hash=str(snapshot.get("config_hash") or ""),
        runtime_config_errors=(),
        dingtalk=replace(
            settings.dingtalk,
            client_id=_str(runtime_value("DINGTALK_CLIENT_ID"), settings.dingtalk.client_id),
            client_secret=_str(
                runtime_value("DINGTALK_CLIENT_SECRET"),
                settings.dingtalk.client_secret,
            ),
            stream_client_secret=_str(
                runtime_value("DINGTALK_CLIENT_SECRET"),
                settings.dingtalk.stream_client_secret,
            ),
            stream_enabled=_bool(
                runtime_value("DINGTALK_STREAM_ENABLED"),
                settings.dingtalk.stream_enabled,
            ),
            stream_connector_id=_str(
                runtime_value("DINGTALK_STREAM_CONNECTOR_ID"),
                settings.dingtalk.stream_connector_id,
            ),
            default_delivery_type=_str(
                runtime_value("DINGTALK_DEFAULT_DELIVERY_TYPE"),
                settings.dingtalk.default_delivery_type,
            ),
            default_delivery_connector_id=_str(
                runtime_value("DINGTALK_DEFAULT_DELIVERY_CONNECTOR_ID"),
                settings.dingtalk.default_delivery_connector_id,
            ),
            default_source_connector_id=_str(
                runtime_value("DINGTALK_DEFAULT_SOURCE_CONNECTOR_ID"),
                settings.dingtalk.default_source_connector_id,
            ),
            default_project_code=_str(
                runtime_value("DINGTALK_DEFAULT_PROJECT_CODE"),
                settings.dingtalk.default_project_code,
            ),
            default_environment=_str(
                runtime_value("DINGTALK_DEFAULT_ENVIRONMENT"),
                settings.dingtalk.default_environment,
            ),
            default_base=_str(
                runtime_value("DINGTALK_DEFAULT_BASE"),
                settings.dingtalk.default_base,
            ),
            default_workshop=_str(
                runtime_value("DINGTALK_DEFAULT_WORKSHOP"),
                settings.dingtalk.default_workshop,
            ),
            default_service=_str(
                runtime_value("DINGTALK_DEFAULT_SERVICE"),
                settings.dingtalk.default_service,
            ),
            default_open_conversation_id=_str(
                runtime_value("DINGTALK_DEFAULT_OPEN_CONVERSATION_ID"),
                settings.dingtalk.default_open_conversation_id,
            ),
            default_robot_code=_str(
                runtime_value("DINGTALK_DEFAULT_ROBOT_CODE"),
                settings.dingtalk.default_robot_code,
            ),
        ),
        loki=replace(
            settings.loki,
            base_url=_str(runtime_value("LOKI_BASE_URL"), settings.loki.base_url),
            max_minutes=_int(runtime_value("LOKI_MAX_MINUTES"), settings.loki.max_minutes),
            max_lines=_int(runtime_value("LOKI_MAX_LINES"), settings.loki.max_lines),
            max_response_chars=_int(
                runtime_value("LOKI_MAX_RESPONSE_CHARS"),
                settings.loki.max_response_chars,
            ),
            tenant_id=_str(runtime_value("LOKI_TENANT_ID"), settings.loki.tenant_id),
        ),
        queue=replace(
            settings.queue,
            max_retry_count=_int(
                runtime_value("AGENT_MAX_RETRY_COUNT"),
                settings.queue.max_retry_count,
            ),
            retry_delay_seconds=_int(
                runtime_value("AGENT_RETRY_DELAY_SECONDS"),
                settings.queue.retry_delay_seconds,
            ),
            consumer_heartbeat_seconds=_int(
                runtime_value("RABBITMQ_CONSUMER_HEARTBEAT_SECONDS"),
                settings.queue.consumer_heartbeat_seconds,
            ),
            consumer_reconnect_seconds=_int(
                runtime_value("RABBITMQ_CONSUMER_RECONNECT_SECONDS"),
                settings.queue.consumer_reconnect_seconds,
            ),
        ),
        execution=replace(
            settings.execution,
            timeout_seconds=_int(
                runtime_value("AGENT_TIMEOUT_SECONDS"),
                settings.execution.timeout_seconds,
            ),
            max_turns=_int(runtime_value("AGENT_MAX_TURNS"), settings.execution.max_turns),
            max_tool_response_chars=_int(
                runtime_value("MAX_TOOL_RESPONSE_CHARS"),
                settings.execution.max_tool_response_chars,
            ),
            max_loki_minutes=_int(
                runtime_value("MAX_LOKI_MINUTES"),
                settings.execution.max_loki_minutes,
            ),
            max_loki_lines=_int(
                runtime_value("MAX_LOKI_LINES"),
                settings.execution.max_loki_lines,
            ),
            redis_scan_limit=_int(
                runtime_value("REDIS_SCAN_LIMIT"),
                settings.execution.redis_scan_limit,
            ),
        ),
    )
    return replace(
        updated,
        runtime_config_degraded=bool(errors),
        runtime_config_errors=tuple(errors),
    )


def _bootstrap_master_key() -> str:
    import os

    return os.getenv("APP_CONFIG_MASTER_KEY", "")


def _str(value: Any | None, default: str) -> str:
    return default if value is None else str(value)


def _int(value: Any | None, default: int) -> int:
    return default if value is None else int(value)


def _bool(value: Any | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}
