from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class QueueSettings:
    job_queue: str = "agent.job.queue"
    retry_queue: str = "agent.job.retry.queue"
    dead_queue: str = "agent.job.dead.queue"
    max_retry_count: int = 3
    retry_delay_seconds: int = 30


@dataclass(frozen=True)
class ExecutionSettings:
    timeout_seconds: int = 300
    max_tool_response_chars: int = 4000
    max_loki_minutes: int = 60
    max_loki_lines: int = 500
    redis_scan_limit: int = 200


@dataclass(frozen=True)
class DingTalkSettings:
    secret: str = ""
    callback_url: str = ""
    callback_host_allowlist: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
    database_dsn: str = "sqlite:///./enterprise_agent.db"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    internal_api_base_url: str = "http://internal-api-platform.local"
    claude_model: str = "claude-sonnet-4-20250514"
    environment: str = "local"
    feature_real_claude: bool = False
    dingtalk: DingTalkSettings = field(default_factory=DingTalkSettings)
    queue: QueueSettings = field(default_factory=QueueSettings)
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)


def _csv_tuple(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def load_settings() -> Settings:
    return Settings(
        database_dsn=os.getenv("DATABASE_DSN", "sqlite:///./enterprise_agent.db"),
        rabbitmq_url=os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"),
        internal_api_base_url=os.getenv(
            "INTERNAL_API_BASE_URL", "http://internal-api-platform.local"
        ),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        environment=os.getenv("APP_ENV", "local"),
        feature_real_claude=os.getenv("FEATURE_REAL_CLAUDE", "false").lower() == "true",
        dingtalk=DingTalkSettings(
            secret=os.getenv("DINGTALK_SECRET", ""),
            callback_url=os.getenv("DINGTALK_CALLBACK_URL", ""),
            callback_host_allowlist=_csv_tuple(os.getenv("DINGTALK_CALLBACK_HOST_ALLOWLIST", "")),
        ),
        queue=QueueSettings(
            job_queue=os.getenv("AGENT_JOB_QUEUE", "agent.job.queue"),
            retry_queue=os.getenv("AGENT_RETRY_QUEUE", "agent.job.retry.queue"),
            dead_queue=os.getenv("AGENT_DEAD_QUEUE", "agent.job.dead.queue"),
            max_retry_count=int(os.getenv("AGENT_MAX_RETRY_COUNT", "3")),
            retry_delay_seconds=int(os.getenv("AGENT_RETRY_DELAY_SECONDS", "30")),
        ),
        execution=ExecutionSettings(
            timeout_seconds=int(os.getenv("AGENT_TIMEOUT_SECONDS", "300")),
            max_tool_response_chars=int(os.getenv("MAX_TOOL_RESPONSE_CHARS", "4000")),
            max_loki_minutes=int(os.getenv("MAX_LOKI_MINUTES", "60")),
            max_loki_lines=int(os.getenv("MAX_LOKI_LINES", "500")),
            redis_scan_limit=int(os.getenv("REDIS_SCAN_LIMIT", "200")),
        ),
    )
