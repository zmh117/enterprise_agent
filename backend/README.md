# Enterprise Agent MVP

This backend implements the read-only diagnostic Agent MVP from the OpenSpec change
`add-readonly-diagnostic-agent-mvp`.

## Scope

The MVP supports this chain:

```text
DingTalk webhook
  -> Agent session/job persisted in PostgreSQL 16
  -> RabbitMQ-backed message bus interface
  -> Agent worker
  -> Claude Code Agent SDK wrapper
  -> read-only internal tools
  -> audit records and final report callback
```

The implementation keeps RabbitMQ, DingTalk, tools, permissions, audit, and Agent
runtime as separate modules. The Agent module only executes a job and uses registered
read-only tools through `InternalApiClient`.

## Read-only Boundary

MVP tools:

- `get_er_context`
- `get_business_flow_context`
- `query_loki`
- `query_database`
- `query_redis_get`
- `query_redis_scan`

The runtime does not expose code editing, PR creation, deployment, restart, database
mutation, Redis mutation, or sandbox execution tools. SQL policy only accepts `SELECT`
or `WITH` statements and rejects DML/DDL/privileged operations. Redis policy only allows
`get` and bounded `scan`. Loki policy enforces service, time range, and line limits.

## Local Commands

Install dev dependencies once:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Run local checks without external services:

```bash
make check
```

Equivalent commands:

```bash
python3 -m compileall backend
PYTHONPATH=backend python3 -m unittest discover -s backend/tests -t .
openspec validate add-readonly-diagnostic-agent-mvp
```

Run the service stack after installing dependencies:

```bash
docker compose up --build
```

API server:

```bash
python -m uvicorn app.main:create_app --factory --app-dir backend --host 0.0.0.0 --port 8000
```

Worker:

```bash
PYTHONPATH=backend python -m app.workers.agent_job_worker
```

## Environment Variables

- `DATABASE_DSN`: PostgreSQL DSN, for example `postgresql://enterprise_agent:enterprise_agent@postgres:5432/enterprise_agent`.
- `RABBITMQ_URL`: RabbitMQ URL, for example `amqp://guest:guest@rabbitmq:5672/`.
- `DINGTALK_SECRET`: DingTalk robot signing secret.
- `DINGTALK_CALLBACK_URL`: optional callback endpoint for final reports.
- `DINGTALK_CALLBACK_HOST_ALLOWLIST`: comma-separated allowed callback hostnames.
- `INTERNAL_API_BASE_URL`: internal API platform base URL.
- `CLAUDE_MODEL`: Claude model identifier used by the real SDK wrapper.
- `FEATURE_REAL_CLAUDE`: enables real Claude wrapper path when dependencies and credentials are configured.
- `AGENT_MAX_RETRY_COUNT`: delayed retries after first execution, default `3`.
- `AGENT_RETRY_DELAY_SECONDS`: retry delay, default `30`.
- `AGENT_TIMEOUT_SECONDS`: runtime execution timeout budget, default `300`.
- `MAX_TOOL_RESPONSE_CHARS`: maximum persisted payload summary size.
- `MAX_LOKI_MINUTES`, `MAX_LOKI_LINES`, `REDIS_SCAN_LIMIT`: read-only tool bounds.

## Queues

- `agent.job.queue`: normal Agent job execution.
- `agent.job.retry.queue`: delayed retry path for retryable failures.
- `agent.job.dead.queue`: dead-letter path after retry exhaustion or terminal failure.

Application services depend on `MessagePublisher` and `MessageConsumer`; RabbitMQ is
hidden in `modules/message_bus/infrastructure`.

## Database Tables

Core execution tables:

- `agent_session`
- `agent_job`
- `agent_message`
- `agent_step`
- `agent_tool_call`
- `agent_artifact`
- `audit_event`

Configuration tables for later web management:

- `tool_definition`
- `integration_connector`
- `datasource_registry`
- `permission_policy`

Migrations are under `backend/migrations`. `backend/seeds/local_seed.sql` provides local
allowlists, tools, connector metadata, and data source metadata for tests/dev.

## Testing Notes

The current environment does not have FastAPI, psycopg, pika, pytest, ruff, or mypy
installed until the dev environment is created. The committed production dependency list
is in `pyproject.toml`, while the checked test suite can use SQLite-compatible migrations
and an in-memory message bus to verify the business path without external services.

The tests cover:

- DingTalk signature success/failure and duplicate delivery.
- Unauthorized user rejection.
- Job persistence, status transition, and duplicate worker claim behavior.
- Read-only database/Redis/Loki policy rejection.
- Tool calls routed through `InternalApiClient` and recorded in audit/tool-call tables.
- Agent execution with compact context search, report artifact persistence, and no
  private reasoning persistence.
- End-to-end fake DingTalk -> job -> worker -> Agent -> report path.
