from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field, replace

from app.shared.feature_configuration import (
    EffectiveFeatureConfiguration,
    default_feature_configuration,
    feature_configuration_from_values,
    resolve_feature_configuration,
)

logger = logging.getLogger(__name__)


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
    channel_queue: str = "agent.channel.dispatch.queue"
    channel_dead_queue: str = "agent.channel.dispatch.dead.queue"
    file_processing_queue: str = "agent.file.processing.queue"
    file_processing_retry_queue: str = "agent.file.processing.retry.queue"
    file_processing_dead_queue: str = "agent.file.processing.dead.queue"
    file_processing_max_attempts: int = 3
    file_processing_retry_base_seconds: int = 30
    max_retry_count: int = 3
    retry_delay_seconds: int = 30
    dispatch_outbox_max_attempts: int = 8
    dispatch_outbox_max_replays: int = 3
    dispatch_outbox_retry_base_seconds: int = 5
    dispatch_outbox_claim_timeout_seconds: int = 300
    dispatch_outbox_scan_seconds: int = 1
    consumer_heartbeat_seconds: int = 900
    consumer_reconnect_seconds: int = 5


@dataclass(frozen=True)
class ExecutionSettings:
    timeout_seconds: int = 300
    max_turns: int = 12
    max_tool_calls: int = 30
    max_tool_response_chars: int = 4000
    max_loki_minutes: int = 60
    max_loki_lines: int = 500
    redis_scan_limit: int = 200


@dataclass(frozen=True)
class DeliverySettings:
    chunk_max_chars: int = 3500
    timeout_seconds: int = 5
    outbox_max_attempts: int = 8
    outbox_max_replays: int = 3
    outbox_retry_base_seconds: int = 5
    outbox_claim_timeout_seconds: int = 300
    outbox_scan_seconds: int = 1


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
        ".pdf",
        ".md",
        ".markdown",
        ".txt",
        ".log",
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
    retention_days: int = 360
    credential_ttl_seconds: int = 900


@dataclass(frozen=True)
class IdentitySettings:
    enabled: bool = False
    web_admin_enabled: bool = False
    published_agent_runtime_enabled: bool = False
    test_identity_headers_enabled: bool = False
    session_cookie_name: str = "enterprise_agent_session"
    csrf_cookie_name: str = "enterprise_agent_csrf"
    session_idle_seconds: int = 8 * 60 * 60
    session_absolute_seconds: int = 7 * 24 * 60 * 60
    cookie_secure: bool = True
    allowed_origins: tuple[str, ...] = ()
    dingtalk_tenant_code: str = "default"
    default_agent_code: str = "default-diagnostic-agent"


@dataclass(frozen=True)
class OnesIdentitySettings:
    instance_code: str = "default"
    display_name: str = "ONES"
    base_url: str = ""
    allowed_hosts: tuple[str, ...] = ()
    timeout_seconds: int = 5
    max_response_bytes: int = 64 * 1024
    allow_insecure_local: bool = False
    challenge_ttl_seconds: int = 600


@dataclass(frozen=True)
class AgentRuntimeSettings:
    python_base_url: str = ""
    python_allowed_hosts: tuple[str, ...] = ()
    retired_configuration_keys: tuple[str, ...] = ()
    grant_private_key_file: str = ""
    model_probe_auth_token_file: str = ""
    allow_insecure_internal_http: bool = False


@dataclass(frozen=True)
class PrincipalJwtSettings:
    signing_private_key_file: str = ""
    public_jwks_file: str = ""
    ttl_seconds: int = 5 * 60


@dataclass(frozen=True)
class ServicePrincipalSettings:
    enabled: bool = False
    file_worker_bootstrap_token_file: str = ""
    file_processing_worker_bootstrap_token_file: str = ""
    delivery_worker_bootstrap_token_file: str = ""
    identity_base_url: str = "http://api-server:8000"
    identity_allowed_hosts: tuple[str, ...] = ("api-server",)
    timeout_seconds: int = 5
    ttl_seconds: int = 5 * 60
    refresh_skew_seconds: int = 60

    def __post_init__(self) -> None:
        if not 1 <= self.ttl_seconds <= 5 * 60:
            raise ValueError("Service Principal TTL must be between 1 and 300 seconds")
        if not 0 <= self.refresh_skew_seconds < self.ttl_seconds:
            raise ValueError("Service Principal refresh skew must be below its TTL")
        if not 1 <= self.timeout_seconds <= 120:
            raise ValueError("Service identity timeout is invalid")


@dataclass(frozen=True)
class OnesMcpSettings:
    provider_base_url: str = ""
    provider_allowed_hosts: tuple[str, ...] = ()
    allow_insecure_local: bool = False
    timeout_seconds: int = 5
    max_request_bytes: int = 32 * 1024
    max_response_bytes: int = 256 * 1024
    audit_retention_days: int = 0


@dataclass(frozen=True)
class FileServiceSettings:
    internal_base_url: str = "http://file-service:9105"
    internal_allowed_hosts: tuple[str, ...] = ("file-service",)
    internal_timeout_seconds: int = 30
    endpoint_url: str = "http://minio:9000"
    bucket: str = "agent-files"
    legacy_attachment_bucket: str = "agent-attachments"
    access_key_ref: str = "secret://platform/minio-file-access-key"
    secret_key_ref: str = "secret://platform/minio-file-secret-key"
    region: str = "us-east-1"
    secure: bool = False
    max_mcp_request_bytes: int = 32 * 1024
    jwks_refresh_seconds: int = 60
    document_processor_version: str = ""
    document_processor_build_digest: str = ""

    def __post_init__(self) -> None:
        if not self.bucket or not self.legacy_attachment_bucket:
            raise ValueError("File storage bucket names are required")
        if self.bucket == self.legacy_attachment_bucket:
            raise ValueError("Managed files and legacy attachments require distinct buckets")
        if bool(self.document_processor_version) != bool(self.document_processor_build_digest):
            raise ValueError("Document processor version and digest must be configured together")
        if self.document_processor_build_digest and (
            len(self.document_processor_build_digest) != 71
            or not self.document_processor_build_digest.startswith("sha256:")
        ):
            raise ValueError("Document processor image digest is invalid")


@dataclass(frozen=True)
class DocumentProcessingWorkerSettings:
    docling_base_url: str = "http://docling-serve:5001"
    docling_allowed_hosts: tuple[str, ...] = ("docling-serve",)
    docling_api_key_file: str = ""
    readiness_host: str = "0.0.0.0"
    readiness_port: int = 9106
    internal_base_url: str = "http://file-processing-worker:9106"
    internal_allowed_hosts: tuple[str, ...] = ("file-processing-worker",)
    connect_timeout_seconds: int = 5
    poll_interval_seconds: float = 2.0
    total_timeout_seconds: int = 600
    max_response_bytes: int = 80 * 1024 * 1024
    concurrency: int = 1

    def __post_init__(self) -> None:
        if not self.docling_allowed_hosts:
            raise ValueError("Docling allowed hosts are required")
        if not self.readiness_host:
            raise ValueError("Document processing readiness host is required")
        if not 1 <= self.readiness_port <= 65535:
            raise ValueError("Document processing readiness port is invalid")
        if not self.internal_allowed_hosts:
            raise ValueError("Document processing worker allowed hosts are required")
        if not 1 <= self.connect_timeout_seconds <= 60:
            raise ValueError("Docling connect timeout is invalid")
        if not 0.1 <= self.poll_interval_seconds <= 30:
            raise ValueError("Docling poll interval is invalid")
        if not 1 <= self.total_timeout_seconds <= 600:
            raise ValueError("Docling total timeout is invalid")
        if not 1024 <= self.max_response_bytes <= 128 * 1024 * 1024:
            raise ValueError("Docling response size bound is invalid")
        if self.concurrency not in {1, 2}:
            raise ValueError("Document processing concurrency must be 1 or 2")


@dataclass(frozen=True)
class WebhookSettings:
    enabled: bool = True
    max_body_bytes: int = 1024 * 1024
    max_json_depth: int = 20
    max_collection_items: int = 2000
    max_message_chars: int = 4000
    max_summary_chars: int = 4000
    event_retention_days: int = 30
    outbox_scan_seconds: int = 5
    outbox_max_attempts: int = 8
    outbox_retry_base_seconds: int = 5


@dataclass(frozen=True)
class ManagedChannelSettings:
    runtime_auth_token: str = ""
    runtime_auth_token_file: str = ""
    lease_ttl_seconds: int = 15
    stale_seconds: int = 30
    max_event_bytes: int = 256 * 1024
    outbox_max_attempts: int = 8
    outbox_retry_base_seconds: int = 5
    internal_requests_per_minute: int = 600


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
    app_config_master_key: str = field(default="", repr=False)
    app_config_master_key_file: str = ""
    master_key_file_required: bool = False
    claude_model: str = "claude-sonnet-4-20250514"
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    model_provider_host_allowlist: tuple[str, ...] = ("api.deepseek.com",)
    environment: str = "local"
    feature_real_claude: bool = False
    feature_business_application_control_plane: bool = False
    feature_configuration: EffectiveFeatureConfiguration = field(
        default_factory=default_feature_configuration
    )
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
    identity: IdentitySettings = field(default_factory=IdentitySettings)
    ones_identity: OnesIdentitySettings = field(default_factory=OnesIdentitySettings)
    agent_runtime: AgentRuntimeSettings = field(default_factory=AgentRuntimeSettings)
    principal_jwt: PrincipalJwtSettings = field(default_factory=PrincipalJwtSettings)
    service_principal: ServicePrincipalSettings = field(default_factory=ServicePrincipalSettings)
    ones_mcp: OnesMcpSettings = field(default_factory=OnesMcpSettings)
    file_service: FileServiceSettings = field(default_factory=FileServiceSettings)
    document_processing_worker: DocumentProcessingWorkerSettings = field(
        default_factory=DocumentProcessingWorkerSettings
    )
    webhooks: WebhookSettings = field(default_factory=WebhookSettings)
    managed_channels: ManagedChannelSettings = field(default_factory=ManagedChannelSettings)


def _csv_tuple(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    environment = os.getenv("APP_ENV", "local")
    features = resolve_feature_configuration(environment, os.environ)
    for diagnostic in features.diagnostics:
        logger.warning(
            "%s keys=%s removal_version=%s",
            diagnostic.message,
            ",".join(diagnostic.keys),
            "0.3.0",
        )
    settings = Settings(
        database_dsn=os.getenv("DATABASE_DSN", "sqlite:///./enterprise_agent.db"),
        rabbitmq_url=os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"),
        app_config_master_key_file=os.getenv(
            "APP_CONFIG_MASTER_KEY_FILE",
            "",
        ),
        master_key_file_required=environment not in {"test", "testing"},
        claude_model=os.getenv(
            "CLAUDE_MODEL",
            os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        ),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_AUTH_TOKEN", "")),
        anthropic_base_url=os.getenv("ANTHROPIC_BASE_URL", ""),
        model_provider_host_allowlist=_csv_tuple(
            os.getenv("MODEL_PROVIDER_HOST_ALLOWLIST", "api.deepseek.com")
        ),
        environment=environment,
        feature_real_claude=features.real_claude_enabled,
        feature_business_application_control_plane=(
            features.business_application_control_plane_enabled
        ),
        feature_configuration=features,
        seed_local_config=_env_bool("SEED_LOCAL_CONFIG"),
        debug_agent_user_id=os.getenv("DEBUG_AGENT_USER_ID", "local-user"),
        agent_runtime=AgentRuntimeSettings(
            python_base_url=os.getenv("PYTHON_AGENT_RUNTIME_URL", ""),
            python_allowed_hosts=_csv_tuple(os.getenv("PYTHON_AGENT_RUNTIME_ALLOWED_HOSTS", "")),
            retired_configuration_keys=tuple(
                key
                for key in (
                    "TYPESCRIPT_AGENT_RUNTIME_URL",
                    "TYPESCRIPT_AGENT_RUNTIME_ALLOWED_HOSTS",
                )
                if os.getenv(key, "").strip()
            ),
            grant_private_key_file=os.getenv("RUNTIME_GRANT_PRIVATE_KEY_FILE", ""),
            model_probe_auth_token_file=os.getenv("MODEL_PROBE_AUTH_TOKEN_FILE", ""),
            allow_insecure_internal_http=_env_bool("AGENT_RUNTIME_ALLOW_INSECURE_INTERNAL_HTTP"),
        ),
        principal_jwt=PrincipalJwtSettings(
            signing_private_key_file=os.getenv("PRINCIPAL_JWT_PRIVATE_KEY_FILE", ""),
            public_jwks_file=os.getenv("PRINCIPAL_JWKS_FILE", ""),
            ttl_seconds=int(os.getenv("PRINCIPAL_JWT_TTL_SECONDS", "300")),
        ),
        service_principal=ServicePrincipalSettings(
            enabled=_env_bool("SERVICE_PRINCIPAL_ENABLED"),
            file_worker_bootstrap_token_file=os.getenv("FILE_WORKER_BOOTSTRAP_TOKEN_FILE", ""),
            file_processing_worker_bootstrap_token_file=os.getenv(
                "FILE_PROCESSING_WORKER_BOOTSTRAP_TOKEN_FILE", ""
            ),
            delivery_worker_bootstrap_token_file=os.getenv(
                "DELIVERY_WORKER_BOOTSTRAP_TOKEN_FILE", ""
            ),
            identity_base_url=os.getenv(
                "SERVICE_IDENTITY_INTERNAL_BASE_URL", "http://api-server:8000"
            ),
            identity_allowed_hosts=_csv_tuple(
                os.getenv("SERVICE_IDENTITY_INTERNAL_ALLOWED_HOSTS", "api-server")
            ),
            timeout_seconds=int(os.getenv("SERVICE_IDENTITY_TIMEOUT_SECONDS", "5")),
            ttl_seconds=int(os.getenv("SERVICE_PRINCIPAL_TTL_SECONDS", "300")),
            refresh_skew_seconds=int(os.getenv("SERVICE_PRINCIPAL_REFRESH_SKEW_SECONDS", "60")),
        ),
        ones_mcp=OnesMcpSettings(
            provider_base_url=os.getenv("ONES_MCP_PROVIDER_BASE_URL", ""),
            provider_allowed_hosts=_csv_tuple(os.getenv("ONES_MCP_PROVIDER_ALLOWED_HOSTS", "")),
            allow_insecure_local=_env_bool("ONES_MCP_PROVIDER_ALLOW_INSECURE_LOCAL"),
            timeout_seconds=int(os.getenv("ONES_MCP_PROVIDER_TIMEOUT_SECONDS", "5")),
            max_request_bytes=int(os.getenv("ONES_MCP_MAX_REQUEST_BYTES", str(32 * 1024))),
            max_response_bytes=int(
                os.getenv("ONES_MCP_PROVIDER_MAX_RESPONSE_BYTES", str(256 * 1024))
            ),
            audit_retention_days=int(os.getenv("MCP_OPERATION_AUDIT_RETENTION_DAYS", "0")),
        ),
        file_service=FileServiceSettings(
            internal_base_url=os.getenv(
                "FILE_SERVICE_INTERNAL_BASE_URL", "http://file-service:9105"
            ),
            internal_allowed_hosts=_csv_tuple(
                os.getenv("FILE_SERVICE_INTERNAL_ALLOWED_HOSTS", "file-service")
            ),
            internal_timeout_seconds=int(os.getenv("FILE_SERVICE_INTERNAL_TIMEOUT_SECONDS", "30")),
            endpoint_url=os.getenv("FILE_STORAGE_ENDPOINT_URL", "http://minio:9000"),
            bucket=os.getenv("FILE_STORAGE_BUCKET", "agent-files"),
            legacy_attachment_bucket=os.getenv(
                "FILE_STORAGE_LEGACY_ATTACHMENT_BUCKET", "agent-attachments"
            ),
            access_key_ref=os.getenv(
                "FILE_STORAGE_ACCESS_KEY_REF",
                "secret://platform/minio-file-access-key",
            ),
            secret_key_ref=os.getenv(
                "FILE_STORAGE_SECRET_KEY_REF",
                "secret://platform/minio-file-secret-key",
            ),
            region=os.getenv("FILE_STORAGE_REGION", "us-east-1"),
            secure=_env_bool("FILE_STORAGE_SECURE"),
            max_mcp_request_bytes=int(os.getenv("FILE_MCP_MAX_REQUEST_BYTES", str(32 * 1024))),
            jwks_refresh_seconds=int(os.getenv("FILE_JWKS_REFRESH_SECONDS", "60")),
            document_processor_version=os.getenv("DOCUMENT_PROCESSOR_VERSION", ""),
            document_processor_build_digest=os.getenv("DOCUMENT_PROCESSOR_BUILD_DIGEST", ""),
        ),
        document_processing_worker=DocumentProcessingWorkerSettings(
            docling_base_url=os.getenv(
                "DOCLING_SERVE_INTERNAL_BASE_URL", "http://docling-serve:5001"
            ),
            docling_allowed_hosts=_csv_tuple(
                os.getenv("DOCLING_SERVE_INTERNAL_ALLOWED_HOSTS", "docling-serve")
            ),
            docling_api_key_file=os.getenv("DOCLING_SERVE_API_KEY_FILE", ""),
            readiness_host=os.getenv("FILE_PROCESSING_WORKER_READINESS_HOST", "0.0.0.0"),
            readiness_port=int(os.getenv("FILE_PROCESSING_WORKER_READINESS_PORT", "9106")),
            internal_base_url=os.getenv(
                "FILE_PROCESSING_WORKER_INTERNAL_BASE_URL",
                "http://file-processing-worker:9106",
            ),
            internal_allowed_hosts=_csv_tuple(
                os.getenv(
                    "FILE_PROCESSING_WORKER_INTERNAL_ALLOWED_HOSTS",
                    "file-processing-worker",
                )
            ),
            connect_timeout_seconds=int(os.getenv("DOCLING_SERVE_CONNECT_TIMEOUT_SECONDS", "5")),
            poll_interval_seconds=float(os.getenv("DOCLING_SERVE_POLL_INTERVAL_SECONDS", "2")),
            total_timeout_seconds=int(os.getenv("DOCLING_SERVE_TOTAL_TIMEOUT_SECONDS", "600")),
            max_response_bytes=int(
                os.getenv("DOCLING_SERVE_MAX_RESPONSE_BYTES", str(80 * 1024 * 1024))
            ),
            concurrency=int(os.getenv("FILE_PROCESSING_WORKER_CONCURRENCY", "1")),
        ),
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
            legacy_retry_queue=os.getenv("AGENT_LEGACY_RETRY_QUEUE", "agent.job.retry.queue"),
            dead_queue=os.getenv("AGENT_DEAD_QUEUE", "agent.job.dead.queue"),
            attachment_queue=os.getenv("ATTACHMENT_QUEUE", "agent.attachment.queue"),
            attachment_retry_queue=os.getenv(
                "ATTACHMENT_RETRY_QUEUE", "agent.attachment.retry.queue"
            ),
            attachment_dead_queue=os.getenv("ATTACHMENT_DEAD_QUEUE", "agent.attachment.dead.queue"),
            webhook_queue=os.getenv("WEBHOOK_DISPATCH_QUEUE", "agent.webhook.dispatch.queue"),
            webhook_dead_queue=os.getenv(
                "WEBHOOK_DISPATCH_DEAD_QUEUE", "agent.webhook.dispatch.dead.queue"
            ),
            channel_queue=os.getenv("CHANNEL_DISPATCH_QUEUE", "agent.channel.dispatch.queue"),
            channel_dead_queue=os.getenv(
                "CHANNEL_DISPATCH_DEAD_QUEUE", "agent.channel.dispatch.dead.queue"
            ),
            file_processing_queue=os.getenv("FILE_PROCESSING_QUEUE", "agent.file.processing.queue"),
            file_processing_retry_queue=os.getenv(
                "FILE_PROCESSING_RETRY_QUEUE", "agent.file.processing.retry.queue"
            ),
            file_processing_dead_queue=os.getenv(
                "FILE_PROCESSING_DEAD_QUEUE", "agent.file.processing.dead.queue"
            ),
            file_processing_max_attempts=int(os.getenv("FILE_PROCESSING_MAX_ATTEMPTS", "3")),
            file_processing_retry_base_seconds=int(
                os.getenv("FILE_PROCESSING_RETRY_BASE_SECONDS", "30")
            ),
            max_retry_count=int(os.getenv("AGENT_MAX_RETRY_COUNT", "3")),
            retry_delay_seconds=int(os.getenv("AGENT_RETRY_DELAY_SECONDS", "30")),
            dispatch_outbox_max_attempts=int(os.getenv("JOB_DISPATCH_OUTBOX_MAX_ATTEMPTS", "8")),
            dispatch_outbox_max_replays=int(os.getenv("JOB_DISPATCH_OUTBOX_MAX_REPLAYS", "3")),
            dispatch_outbox_retry_base_seconds=int(
                os.getenv("JOB_DISPATCH_OUTBOX_RETRY_BASE_SECONDS", "5")
            ),
            dispatch_outbox_claim_timeout_seconds=int(
                os.getenv("JOB_DISPATCH_OUTBOX_CLAIM_TIMEOUT_SECONDS", "300")
            ),
            dispatch_outbox_scan_seconds=int(os.getenv("JOB_DISPATCH_OUTBOX_SCAN_SECONDS", "1")),
            consumer_heartbeat_seconds=int(os.getenv("RABBITMQ_CONSUMER_HEARTBEAT_SECONDS", "900")),
            consumer_reconnect_seconds=int(os.getenv("RABBITMQ_CONSUMER_RECONNECT_SECONDS", "5")),
        ),
        execution=ExecutionSettings(
            timeout_seconds=int(os.getenv("AGENT_TIMEOUT_SECONDS", "300")),
            max_turns=int(os.getenv("AGENT_MAX_TURNS", "12")),
            max_tool_calls=int(os.getenv("AGENT_MAX_TOOL_CALLS", "30")),
            max_tool_response_chars=int(os.getenv("MAX_TOOL_RESPONSE_CHARS", "4000")),
            max_loki_minutes=int(os.getenv("MAX_LOKI_MINUTES", "60")),
            max_loki_lines=int(os.getenv("MAX_LOKI_LINES", "500")),
            redis_scan_limit=int(os.getenv("REDIS_SCAN_LIMIT", "200")),
        ),
        delivery=DeliverySettings(
            chunk_max_chars=int(os.getenv("DELIVERY_CHUNK_MAX_CHARS", "3500")),
            timeout_seconds=int(os.getenv("DELIVERY_TIMEOUT_SECONDS", "5")),
            outbox_max_attempts=int(os.getenv("DELIVERY_OUTBOX_MAX_ATTEMPTS", "8")),
            outbox_max_replays=int(os.getenv("DELIVERY_OUTBOX_MAX_REPLAYS", "3")),
            outbox_retry_base_seconds=int(os.getenv("DELIVERY_OUTBOX_RETRY_BASE_SECONDS", "5")),
            outbox_claim_timeout_seconds=int(
                os.getenv("DELIVERY_OUTBOX_CLAIM_TIMEOUT_SECONDS", "300")
            ),
            outbox_scan_seconds=int(os.getenv("DELIVERY_OUTBOX_SCAN_SECONDS", "1")),
        ),
        conversation=ConversationSettings(
            enabled=features.continuous_conversation_compatibility_enabled,
            recent_message_limit=int(os.getenv("CONVERSATION_RECENT_MESSAGE_LIMIT", "20")),
            summary_trigger_messages=int(os.getenv("CONVERSATION_SUMMARY_TRIGGER_MESSAGES", "30")),
            max_summary_chars=int(os.getenv("CONVERSATION_MAX_SUMMARY_CHARS", "4000")),
            max_context_chars=int(os.getenv("CONVERSATION_MAX_CONTEXT_CHARS", "12000")),
            max_attachment_context_chars=int(
                os.getenv("CONVERSATION_MAX_ATTACHMENT_CONTEXT_CHARS", "4000")
            ),
        ),
        attachments=AttachmentSettings(
            enabled=features.message_attachments_compatibility_enabled,
            allowed_extensions=_csv_tuple(
                os.getenv(
                    "ATTACHMENT_ALLOWED_EXTENSIONS",
                    ".jpg,.jpeg,.png,.webp,.docx,.xlsx,.pptx,.pdf,.md,.markdown,.txt,.log",
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
            max_spreadsheet_columns=int(os.getenv("ATTACHMENT_MAX_SPREADSHEET_COLUMNS", "100")),
            max_slides=int(os.getenv("ATTACHMENT_MAX_SLIDES", "300")),
            timeout_seconds=int(os.getenv("ATTACHMENT_TIMEOUT_SECONDS", "60")),
            retention_days=int(os.getenv("ATTACHMENT_RETENTION_DAYS", "360")),
            credential_ttl_seconds=int(os.getenv("ATTACHMENT_CREDENTIAL_TTL_SECONDS", "900")),
        ),
        identity=IdentitySettings(
            enabled=features.unified_identity_enabled,
            web_admin_enabled=features.web_admin_enabled,
            published_agent_runtime_enabled=(features.published_agent_runtime_enabled),
            test_identity_headers_enabled=features.test_identity_headers_enabled,
            session_cookie_name=os.getenv("WEB_SESSION_COOKIE_NAME", "enterprise_agent_session"),
            csrf_cookie_name=os.getenv("WEB_CSRF_COOKIE_NAME", "enterprise_agent_csrf"),
            session_idle_seconds=int(os.getenv("WEB_SESSION_IDLE_SECONDS", "28800")),
            session_absolute_seconds=int(os.getenv("WEB_SESSION_ABSOLUTE_SECONDS", "604800")),
            cookie_secure=_env_bool("WEB_COOKIE_SECURE", True),
            allowed_origins=_csv_tuple(os.getenv("WEB_ALLOWED_ORIGINS", "")),
            dingtalk_tenant_code=os.getenv("DINGTALK_TENANT_CODE", "default"),
            default_agent_code=os.getenv("DEFAULT_AGENT_CODE", "default-diagnostic-agent"),
        ),
        ones_identity=OnesIdentitySettings(
            instance_code=os.getenv("ONES_IDENTITY_INSTANCE_CODE", "default"),
            display_name=os.getenv("ONES_IDENTITY_DISPLAY_NAME", "ONES"),
            base_url=os.getenv("ONES_IDENTITY_BASE_URL", ""),
            allowed_hosts=_csv_tuple(os.getenv("ONES_IDENTITY_ALLOWED_HOSTS", "")),
            timeout_seconds=int(os.getenv("ONES_IDENTITY_TIMEOUT_SECONDS", "5")),
            max_response_bytes=int(os.getenv("ONES_IDENTITY_MAX_RESPONSE_BYTES", str(64 * 1024))),
            allow_insecure_local=_env_bool("ONES_IDENTITY_ALLOW_INSECURE_LOCAL"),
            challenge_ttl_seconds=int(os.getenv("ONES_IDENTITY_CHALLENGE_TTL_SECONDS", "600")),
        ),
        webhooks=WebhookSettings(
            enabled=features.webhook_ingress_compatibility_enabled,
            max_body_bytes=int(os.getenv("WEBHOOK_MAX_BODY_BYTES", str(1024 * 1024))),
            max_json_depth=int(os.getenv("WEBHOOK_MAX_JSON_DEPTH", "20")),
            max_collection_items=int(os.getenv("WEBHOOK_MAX_COLLECTION_ITEMS", "2000")),
            max_message_chars=int(os.getenv("WEBHOOK_MAX_MESSAGE_CHARS", "4000")),
            max_summary_chars=int(os.getenv("WEBHOOK_MAX_SUMMARY_CHARS", "4000")),
            event_retention_days=int(os.getenv("WEBHOOK_EVENT_RETENTION_DAYS", "30")),
            outbox_scan_seconds=int(os.getenv("WEBHOOK_OUTBOX_SCAN_SECONDS", "5")),
            outbox_max_attempts=int(os.getenv("WEBHOOK_OUTBOX_MAX_ATTEMPTS", "8")),
            outbox_retry_base_seconds=int(os.getenv("WEBHOOK_OUTBOX_RETRY_BASE_SECONDS", "5")),
        ),
        managed_channels=ManagedChannelSettings(
            runtime_auth_token=os.getenv("DINGTALK_RUNTIME_AUTH_TOKEN", ""),
            runtime_auth_token_file=os.getenv("DINGTALK_RUNTIME_AUTH_TOKEN_FILE", ""),
            lease_ttl_seconds=int(os.getenv("DINGTALK_RUNTIME_LEASE_TTL_SECONDS", "15")),
            stale_seconds=int(os.getenv("DINGTALK_RUNTIME_STALE_SECONDS", "30")),
            max_event_bytes=int(os.getenv("DINGTALK_RUNTIME_MAX_EVENT_BYTES", str(256 * 1024))),
            outbox_max_attempts=int(os.getenv("CHANNEL_OUTBOX_MAX_ATTEMPTS", "8")),
            outbox_retry_base_seconds=int(os.getenv("CHANNEL_OUTBOX_RETRY_BASE_SECONDS", "5")),
            internal_requests_per_minute=int(
                os.getenv("DINGTALK_RUNTIME_REQUESTS_PER_MINUTE", "600")
            ),
        ),
    )
    return settings


def synchronize_feature_configuration(settings: Settings) -> Settings:
    """Keep programmatically constructed Settings aligned with the unified model."""
    features = settings.feature_configuration
    expected = (
        settings.identity.web_admin_enabled,
        settings.identity.published_agent_runtime_enabled,
        settings.feature_real_claude,
        settings.identity.enabled,
        settings.feature_business_application_control_plane,
        settings.identity.test_identity_headers_enabled,
        settings.webhooks.enabled,
        settings.conversation.enabled,
        settings.attachments.enabled,
    )
    actual = (
        features.web_admin_enabled,
        features.published_agent_runtime_enabled,
        features.real_claude_enabled,
        features.unified_identity_enabled,
        features.business_application_control_plane_enabled,
        features.test_identity_headers_enabled,
        features.webhook_ingress_compatibility_enabled,
        features.continuous_conversation_compatibility_enabled,
        features.message_attachments_compatibility_enabled,
    )
    if actual == expected:
        return settings
    synchronized = feature_configuration_from_values(
        web_admin=settings.identity.web_admin_enabled,
        published_agent_runtime=settings.identity.published_agent_runtime_enabled,
        real_claude=settings.feature_real_claude,
        unified_identity=settings.identity.enabled,
        business_application_control_plane=(settings.feature_business_application_control_plane),
        test_identity_headers=settings.identity.test_identity_headers_enabled,
        webhook_ingress=settings.webhooks.enabled,
        continuous_conversation=settings.conversation.enabled,
        message_attachments=settings.attachments.enabled,
        source="programmatic-settings",
    )
    return replace(settings, feature_configuration=synchronized)
