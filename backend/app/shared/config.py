from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class QueueSettings:
    job_queue: str = "agent.job.queue"
    retry_queue: str = "agent.job.retry.delay.v1.queue"
    legacy_retry_queue: str = "agent.job.retry.queue"
    dead_queue: str = "agent.job.dead.queue"
    attachment_queue: str = "agent.attachment.queue"
    attachment_retry_queue: str = "agent.attachment.retry.queue"
    attachment_dead_queue: str = "agent.attachment.dead.queue"
    webhook_queue: str = "agent.webhook.dispatch.queue"
    webhook_dead_queue: str = "agent.webhook.dispatch.dead.queue"
    max_retry_count: int = 3
    retry_delay_seconds: int = 30
    consumer_heartbeat_seconds: int = 900
    consumer_reconnect_seconds: int = 5


@dataclass(frozen=True)
class ExecutionSettings:
    timeout_seconds: int = 300
    max_turns: int = 12
    max_tool_response_chars: int = 4000
    max_loki_minutes: int = 60
    max_loki_lines: int = 500
    redis_scan_limit: int = 200


@dataclass(frozen=True)
class DeliverySettings:
    chunk_max_chars: int = 3500
    timeout_seconds: int = 5


@dataclass(frozen=True)
class ConversationSettings:
    enabled: bool = False
    recent_message_limit: int = 20
    summary_trigger_messages: int = 30
    max_summary_chars: int = 4000
    max_context_chars: int = 12000
    max_attachment_context_chars: int = 4000


@dataclass(frozen=True)
class AttachmentSettings:
    enabled: bool = False
    allowed_extensions: tuple[str, ...] = (
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".docx",
        ".xlsx",
        ".pptx",
        ".md",
        ".markdown",
    )
    max_count: int = 10
    max_file_bytes: int = 25 * 1024 * 1024
    max_message_bytes: int = 100 * 1024 * 1024
    max_uncompressed_bytes: int = 100 * 1024 * 1024
    max_extract_chars: int = 50000
    max_image_pixels: int = 25_000_000
    max_spreadsheet_rows: int = 2000
    max_spreadsheet_columns: int = 100
    max_slides: int = 300
    timeout_seconds: int = 60
    retention_days: int = 180
    credential_ttl_seconds: int = 900


@dataclass(frozen=True)
class ObjectStorageSettings:
    endpoint_url: str = "http://minio:9000"
    access_key: str = "enterprise_agent"
    secret_key: str = "enterprise_agent_change_me"
    bucket: str = "agent-attachments"
    region: str = "us-east-1"
    secure: bool = False


@dataclass(frozen=True)
class IdentitySettings:
    enabled: bool = False
    web_admin_enabled: bool = False
    published_agent_runtime_enabled: bool = False
    test_identity_headers_enabled: bool = False
    permission_shadow_mode: bool = True
    session_cookie_name: str = "enterprise_agent_session"
    csrf_cookie_name: str = "enterprise_agent_csrf"
    session_idle_seconds: int = 8 * 60 * 60
    session_absolute_seconds: int = 7 * 24 * 60 * 60
    cookie_secure: bool = True
    allowed_origins: tuple[str, ...] = ()
    dingtalk_tenant_code: str = "default"
    default_agent_code: str = "default-diagnostic-agent"


@dataclass(frozen=True)
class WebhookSettings:
    enabled: bool = True
    max_body_bytes: int = 1024 * 1024
    max_json_depth: int = 20
    max_collection_items: int = 2000
    max_message_chars: int = 4000
    max_summary_chars: int = 4000
    default_hmac_window_seconds: int = 300
    event_retention_days: int = 30
    outbox_scan_seconds: int = 5
    outbox_max_attempts: int = 8
    outbox_retry_base_seconds: int = 5


@dataclass(frozen=True)
class DingTalkSettings:
    secret: str = ""
    callback_url: str = ""
    callback_host_allowlist: tuple[str, ...] = ()
    http_webhook_enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    stream_enabled: bool = False
    stream_client_id: str = ""
    stream_client_secret: str = ""
    stream_connector_id: str = "connector-dingtalk-stream-default"
    stream_reconnect_initial_seconds: int = 5
    stream_reconnect_max_seconds: int = 60
    stream_worker_id: str = "dingtalk-stream-ingress"
    webhook_robot_url: str = ""
    webhook_robot_secret: str = ""
    default_delivery_type: str = "dingtalk_enterprise_robot"
    default_delivery_connector_id: str = "connector-dingtalk-enterprise-default"
    default_source_connector_id: str = "connector-dingtalk-stream-default"
    default_project_code: str = "default"
    default_environment: str = ""
    default_base: str = ""
    default_workshop: str = ""
    default_service: str = ""
    default_open_conversation_id: str = ""
    default_robot_code: str = ""


@dataclass(frozen=True)
class LokiSettings:
    base_url: str = "http://host.docker.internal:3100"
    max_minutes: int = 60
    max_lines: int = 500
    max_response_chars: int = 4000
    tenant_id: str = ""


@dataclass(frozen=True)
class Settings:
    database_dsn: str = "sqlite:///./enterprise_agent.db"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    app_config_master_key: str = "test-master-key"
    internal_api_base_url: str = "http://internal-api-platform.local"
    internal_api_auth_token: str = ""
    internal_api_timeout_seconds: int = 10
    internal_api_max_response_chars: int = 4000
    internal_platform_max_rows: int = 100
    claude_model: str = "claude-sonnet-4-20250514"
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    environment: str = "local"
    feature_real_claude: bool = False
    feature_real_internal_tools: bool = False
    app_startup_migrate: bool = True
    seed_local_config: bool = False
    runtime_config_source: str = "env"
    runtime_config_degraded: bool = False
    runtime_config_revision: int = 0
    runtime_config_hash: str = ""
    runtime_config_errors: tuple[str, ...] = ()
    debug_agent_user_id: str = "local-user"
    dingtalk: DingTalkSettings = field(default_factory=DingTalkSettings)
    loki: LokiSettings = field(default_factory=LokiSettings)
    queue: QueueSettings = field(default_factory=QueueSettings)
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)
    delivery: DeliverySettings = field(default_factory=DeliverySettings)
    conversation: ConversationSettings = field(default_factory=ConversationSettings)
    attachments: AttachmentSettings = field(default_factory=AttachmentSettings)
    object_storage: ObjectStorageSettings = field(default_factory=ObjectStorageSettings)
    identity: IdentitySettings = field(default_factory=IdentitySettings)
    webhooks: WebhookSettings = field(default_factory=WebhookSettings)


def _csv_tuple(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    return Settings(
        database_dsn=os.getenv("DATABASE_DSN", "sqlite:///./enterprise_agent.db"),
        rabbitmq_url=os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"),
        app_config_master_key=os.getenv("APP_CONFIG_MASTER_KEY", ""),
        internal_api_base_url=os.getenv(
            "INTERNAL_API_BASE_URL", "http://internal-api-platform.local"
        ),
        internal_api_auth_token=os.getenv("INTERNAL_API_AUTH_TOKEN", ""),
        internal_api_timeout_seconds=int(os.getenv("INTERNAL_API_TIMEOUT_SECONDS", "10")),
        internal_api_max_response_chars=int(os.getenv("INTERNAL_API_MAX_RESPONSE_CHARS", "4000")),
        internal_platform_max_rows=int(os.getenv("INTERNAL_PLATFORM_MAX_ROWS", "100")),
        claude_model=os.getenv(
            "CLAUDE_MODEL",
            os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        ),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_AUTH_TOKEN", "")),
        anthropic_base_url=os.getenv("ANTHROPIC_BASE_URL", ""),
        environment=os.getenv("APP_ENV", "local"),
        feature_real_claude=_env_bool("FEATURE_REAL_CLAUDE"),
        feature_real_internal_tools=_env_bool("FEATURE_REAL_INTERNAL_TOOLS"),
        app_startup_migrate=_env_bool("APP_STARTUP_MIGRATE", True),
        seed_local_config=_env_bool("SEED_LOCAL_CONFIG"),
        debug_agent_user_id=os.getenv("DEBUG_AGENT_USER_ID", "local-user"),
        dingtalk=DingTalkSettings(
            secret=os.getenv("DINGTALK_SECRET", ""),
            callback_url=os.getenv("DINGTALK_CALLBACK_URL", ""),
            callback_host_allowlist=_csv_tuple(os.getenv("DINGTALK_CALLBACK_HOST_ALLOWLIST", "")),
            http_webhook_enabled=_env_bool("DINGTALK_HTTP_WEBHOOK_ENABLED"),
            client_id=os.getenv("DINGTALK_CLIENT_ID", ""),
            client_secret=os.getenv("DINGTALK_CLIENT_SECRET", ""),
            stream_enabled=_env_bool("DINGTALK_STREAM_ENABLED"),
            stream_client_id=os.getenv(
                "DINGTALK_STREAM_CLIENT_ID",
                os.getenv("DINGTALK_CLIENT_ID", ""),
            ),
            stream_client_secret=os.getenv(
                "DINGTALK_STREAM_CLIENT_SECRET",
                os.getenv("DINGTALK_CLIENT_SECRET", ""),
            ),
            stream_connector_id=os.getenv(
                "DINGTALK_STREAM_CONNECTOR_ID",
                "connector-dingtalk-stream-default",
            ),
            stream_reconnect_initial_seconds=int(
                os.getenv("DINGTALK_STREAM_RECONNECT_INITIAL_SECONDS", "5")
            ),
            stream_reconnect_max_seconds=int(
                os.getenv("DINGTALK_STREAM_RECONNECT_MAX_SECONDS", "60")
            ),
            stream_worker_id=os.getenv("DINGTALK_STREAM_WORKER_ID", "dingtalk-stream-ingress"),
            webhook_robot_url=os.getenv("DINGTALK_WEBHOOK_ROBOT_URL", ""),
            webhook_robot_secret=os.getenv("DINGTALK_WEBHOOK_ROBOT_SECRET", ""),
            default_delivery_type=os.getenv(
                "DINGTALK_DEFAULT_DELIVERY_TYPE", "dingtalk_enterprise_robot"
            ),
            default_delivery_connector_id=os.getenv(
                "DINGTALK_DEFAULT_DELIVERY_CONNECTOR_ID",
                "connector-dingtalk-enterprise-default",
            ),
            default_source_connector_id=os.getenv(
                "DINGTALK_DEFAULT_SOURCE_CONNECTOR_ID",
                "connector-dingtalk-stream-default",
            ),
            default_project_code=os.getenv("DINGTALK_DEFAULT_PROJECT_CODE", "default"),
            default_environment=os.getenv("DINGTALK_DEFAULT_ENVIRONMENT", ""),
            default_base=os.getenv("DINGTALK_DEFAULT_BASE", ""),
            default_workshop=os.getenv("DINGTALK_DEFAULT_WORKSHOP", ""),
            default_service=os.getenv("DINGTALK_DEFAULT_SERVICE", ""),
            default_open_conversation_id=os.getenv("DINGTALK_DEFAULT_OPEN_CONVERSATION_ID", ""),
            default_robot_code=os.getenv("DINGTALK_DEFAULT_ROBOT_CODE", ""),
        ),
        loki=LokiSettings(
            base_url=os.getenv("LOKI_BASE_URL", "http://host.docker.internal:3100"),
            max_minutes=int(os.getenv("LOKI_MAX_MINUTES", "60")),
            max_lines=int(os.getenv("LOKI_MAX_LINES", "500")),
            max_response_chars=int(os.getenv("LOKI_MAX_RESPONSE_CHARS", "4000")),
            tenant_id=os.getenv("LOKI_TENANT_ID", ""),
        ),
        queue=QueueSettings(
            job_queue=os.getenv("AGENT_JOB_QUEUE", "agent.job.queue"),
            retry_queue=os.getenv("AGENT_RETRY_QUEUE", "agent.job.retry.delay.v1.queue"),
            legacy_retry_queue=os.getenv(
                "AGENT_LEGACY_RETRY_QUEUE", "agent.job.retry.queue"
            ),
            dead_queue=os.getenv("AGENT_DEAD_QUEUE", "agent.job.dead.queue"),
            attachment_queue=os.getenv("ATTACHMENT_QUEUE", "agent.attachment.queue"),
            attachment_retry_queue=os.getenv(
                "ATTACHMENT_RETRY_QUEUE", "agent.attachment.retry.queue"
            ),
            attachment_dead_queue=os.getenv(
                "ATTACHMENT_DEAD_QUEUE", "agent.attachment.dead.queue"
            ),
            webhook_queue=os.getenv(
                "WEBHOOK_DISPATCH_QUEUE", "agent.webhook.dispatch.queue"
            ),
            webhook_dead_queue=os.getenv(
                "WEBHOOK_DISPATCH_DEAD_QUEUE", "agent.webhook.dispatch.dead.queue"
            ),
            max_retry_count=int(os.getenv("AGENT_MAX_RETRY_COUNT", "3")),
            retry_delay_seconds=int(os.getenv("AGENT_RETRY_DELAY_SECONDS", "30")),
            consumer_heartbeat_seconds=int(os.getenv("RABBITMQ_CONSUMER_HEARTBEAT_SECONDS", "900")),
            consumer_reconnect_seconds=int(os.getenv("RABBITMQ_CONSUMER_RECONNECT_SECONDS", "5")),
        ),
        execution=ExecutionSettings(
            timeout_seconds=int(os.getenv("AGENT_TIMEOUT_SECONDS", "300")),
            max_turns=int(os.getenv("AGENT_MAX_TURNS", "12")),
            max_tool_response_chars=int(os.getenv("MAX_TOOL_RESPONSE_CHARS", "4000")),
            max_loki_minutes=int(os.getenv("MAX_LOKI_MINUTES", "60")),
            max_loki_lines=int(os.getenv("MAX_LOKI_LINES", "500")),
            redis_scan_limit=int(os.getenv("REDIS_SCAN_LIMIT", "200")),
        ),
        delivery=DeliverySettings(
            chunk_max_chars=int(os.getenv("DELIVERY_CHUNK_MAX_CHARS", "3500")),
            timeout_seconds=int(os.getenv("DELIVERY_TIMEOUT_SECONDS", "5")),
        ),
        conversation=ConversationSettings(
            enabled=_env_bool("FEATURE_CONTINUOUS_CONVERSATION"),
            recent_message_limit=int(os.getenv("CONVERSATION_RECENT_MESSAGE_LIMIT", "20")),
            summary_trigger_messages=int(os.getenv("CONVERSATION_SUMMARY_TRIGGER_MESSAGES", "30")),
            max_summary_chars=int(os.getenv("CONVERSATION_MAX_SUMMARY_CHARS", "4000")),
            max_context_chars=int(os.getenv("CONVERSATION_MAX_CONTEXT_CHARS", "12000")),
            max_attachment_context_chars=int(
                os.getenv("CONVERSATION_MAX_ATTACHMENT_CONTEXT_CHARS", "4000")
            ),
        ),
        attachments=AttachmentSettings(
            enabled=_env_bool("FEATURE_MESSAGE_ATTACHMENTS"),
            allowed_extensions=_csv_tuple(
                os.getenv(
                    "ATTACHMENT_ALLOWED_EXTENSIONS",
                    ".jpg,.jpeg,.png,.webp,.docx,.xlsx,.pptx,.md,.markdown",
                )
            ),
            max_count=int(os.getenv("ATTACHMENT_MAX_COUNT", "10")),
            max_file_bytes=int(os.getenv("ATTACHMENT_MAX_FILE_BYTES", str(25 * 1024 * 1024))),
            max_message_bytes=int(
                os.getenv("ATTACHMENT_MAX_MESSAGE_BYTES", str(100 * 1024 * 1024))
            ),
            max_uncompressed_bytes=int(
                os.getenv("ATTACHMENT_MAX_UNCOMPRESSED_BYTES", str(100 * 1024 * 1024))
            ),
            max_extract_chars=int(os.getenv("ATTACHMENT_MAX_EXTRACT_CHARS", "50000")),
            max_image_pixels=int(os.getenv("ATTACHMENT_MAX_IMAGE_PIXELS", "25000000")),
            max_spreadsheet_rows=int(os.getenv("ATTACHMENT_MAX_SPREADSHEET_ROWS", "2000")),
            max_spreadsheet_columns=int(
                os.getenv("ATTACHMENT_MAX_SPREADSHEET_COLUMNS", "100")
            ),
            max_slides=int(os.getenv("ATTACHMENT_MAX_SLIDES", "300")),
            timeout_seconds=int(os.getenv("ATTACHMENT_TIMEOUT_SECONDS", "60")),
            retention_days=int(os.getenv("ATTACHMENT_RETENTION_DAYS", "180")),
            credential_ttl_seconds=int(
                os.getenv("ATTACHMENT_CREDENTIAL_TTL_SECONDS", "900")
            ),
        ),
        object_storage=ObjectStorageSettings(
            endpoint_url=os.getenv("S3_ENDPOINT_URL", "http://minio:9000"),
            access_key=os.getenv("S3_ACCESS_KEY", "enterprise_agent"),
            secret_key=os.getenv("S3_SECRET_KEY", "enterprise_agent_change_me"),
            bucket=os.getenv("S3_BUCKET", "agent-attachments"),
            region=os.getenv("S3_REGION", "us-east-1"),
            secure=_env_bool("S3_SECURE"),
        ),
        identity=IdentitySettings(
            enabled=_env_bool("FEATURE_UNIFIED_IDENTITY"),
            web_admin_enabled=_env_bool("FEATURE_WEB_ADMIN"),
            published_agent_runtime_enabled=_env_bool("FEATURE_PUBLISHED_AGENT_RUNTIME"),
            test_identity_headers_enabled=_env_bool("FEATURE_TEST_IDENTITY_HEADERS"),
            permission_shadow_mode=_env_bool("FEATURE_PERMISSION_SHADOW_MODE", True),
            session_cookie_name=os.getenv(
                "WEB_SESSION_COOKIE_NAME", "enterprise_agent_session"
            ),
            csrf_cookie_name=os.getenv("WEB_CSRF_COOKIE_NAME", "enterprise_agent_csrf"),
            session_idle_seconds=int(os.getenv("WEB_SESSION_IDLE_SECONDS", "28800")),
            session_absolute_seconds=int(
                os.getenv("WEB_SESSION_ABSOLUTE_SECONDS", "604800")
            ),
            cookie_secure=_env_bool("WEB_COOKIE_SECURE", True),
            allowed_origins=_csv_tuple(os.getenv("WEB_ALLOWED_ORIGINS", "")),
            dingtalk_tenant_code=os.getenv("DINGTALK_TENANT_CODE", "default"),
            default_agent_code=os.getenv(
                "DEFAULT_AGENT_CODE", "default-diagnostic-agent"
            ),
        ),
        webhooks=WebhookSettings(
            enabled=_env_bool("FEATURE_WEBHOOK_TRIGGERS", True),
            max_body_bytes=int(os.getenv("WEBHOOK_MAX_BODY_BYTES", str(1024 * 1024))),
            max_json_depth=int(os.getenv("WEBHOOK_MAX_JSON_DEPTH", "20")),
            max_collection_items=int(os.getenv("WEBHOOK_MAX_COLLECTION_ITEMS", "2000")),
            max_message_chars=int(os.getenv("WEBHOOK_MAX_MESSAGE_CHARS", "4000")),
            max_summary_chars=int(os.getenv("WEBHOOK_MAX_SUMMARY_CHARS", "4000")),
            default_hmac_window_seconds=int(os.getenv("WEBHOOK_HMAC_WINDOW_SECONDS", "300")),
            event_retention_days=int(os.getenv("WEBHOOK_EVENT_RETENTION_DAYS", "30")),
            outbox_scan_seconds=int(os.getenv("WEBHOOK_OUTBOX_SCAN_SECONDS", "5")),
            outbox_max_attempts=int(os.getenv("WEBHOOK_OUTBOX_MAX_ATTEMPTS", "8")),
            outbox_retry_base_seconds=int(os.getenv("WEBHOOK_OUTBOX_RETRY_BASE_SECONDS", "5")),
        ),
    )
