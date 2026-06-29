## Context

The repository is starting from an OpenSpec planning skeleton, so this change defines the first durable backend architecture for an enterprise Agent platform. The MVP is intentionally scoped to a read-only diagnostic path:

```text
DingTalk user question
  -> FastAPI webhook
  -> persisted Agent job
  -> RabbitMQ dispatch
  -> Agent worker
  -> Python Claude Code Agent SDK wrapper
  -> read-only MCP/SDK tools
  -> internal API platform
  -> ER/business-flow/Loki/Redis/database evidence
  -> auditable report
  -> DingTalk callback
```

The first deployment should use PostgreSQL 16 as the single system database, RabbitMQ as the asynchronous task bus, FastAPI for HTTP APIs, and a Python worker for Claude Code Agent SDK execution. The design must keep module boundaries clear because later versions will add web-based service configuration, more integration adapters, approval flows, sandboxed code execution, and Codex/Cursor-style code agents.

## Goals / Non-Goals

**Goals:**

- Provide an end-to-end read-only diagnostic Agent execution chain from DingTalk to final report.
- Persist task, message, tool-call, audit, permission, connector, and configuration records in PostgreSQL 16.
- Keep RabbitMQ in an independent `message_bus` module and expose only publisher/consumer interfaces to application services.
- Keep Agent execution focused on context construction, skill loading, tool registration, Claude Code Agent invocation, and result recording.
- Force database, Redis, Loki, ER, and business-flow access through internal API platform contracts with permission checks, audit, rate limiting, and result summarization.
- Return quick DingTalk acknowledgement before asynchronous analysis starts.
- Support retry, timeout, and dead-letter handling for transient execution failures.
- Reserve extension points for future sandbox, approval, code-agent, observability, and web configuration modules.

**Non-Goals:**

- No automatic code modification, PR creation, deployment, restart, database update, Redis delete, or other mutating operation.
- No direct Claude runtime access to production databases, Redis, Loki, or ER/business-flow storage.
- No complex multi-Agent collaboration, full visual trace UI, or web admin UI in this change.
- No storage of private model chain-of-thought; only user-visible steps, tool calls, evidence summaries, and final answers are persisted.

## Decisions

### 1. Use modular FastAPI plus worker processes first

MVP services:

```text
api-server
agent-worker
rabbitmq
postgres
internal-api-platform
```

The `internal-api-platform` can initially live in the same FastAPI codebase as separate routes and modules, but its contract must be treated as a platform boundary. Claude tools call internal API clients, not raw database/Redis/Loki clients.

Alternative considered: split every module into independent services immediately. That would increase deployment and operational cost before the execution chain is proven.

### 2. Keep domain modules separate from infrastructure details

Target backend layout:

```text
backend/app/
  modules/
    dingding/
    job/
    message_bus/
    agent/
    internal_tools/
    permission/
    audit/
    context/
    observability/
    approval/
    sandbox/
    code_agent/
  workers/
    agent_job_worker.py
  shared/
```

The first implementation should fill only MVP modules and create placeholder boundaries only when they prevent coupling. `approval`, `sandbox`, and `code_agent` are reserved for future changes and should not execute real behavior in MVP.

Alternative considered: place `rabbitmq_consumer.py`, retry policy, and worker code under `agent/`. This was rejected because message dispatch is infrastructure, not Agent domain logic, and would make future Kafka/NATS/Redis Stream migration harder.

### 3. Model Agent jobs as persisted domain state

Core tables:

- `agent_session`: DingTalk conversation/session identity, user, source, project/service code, timestamps.
- `agent_job`: one Agent execution request with status, priority, retry counters, result, error, timeout, timestamps.
- `agent_message`: user, assistant, system, and tool-facing messages that are safe to persist.
- `agent_step`: user-visible execution steps such as started, querying logs, querying database, final answer, and error.
- `agent_tool_call`: tool name, input summary, response summary, status, duration, risk, and audit linkage.
- `agent_artifact`: report and compact evidence artifacts.
- `audit_event`: normalized audit trail across webhook, job, permission, tool, result, and callback events.
- `tool_definition`, `integration_connector`, `datasource_registry`, and `permission_policy`: persisted configuration records that a later web UI can manage.

Status model:

```text
PENDING -> RUNNING -> SUCCEEDED
PENDING -> RUNNING -> FAILED
PENDING -> RUNNING -> TIMEOUT
```

`WAITING_APPROVAL` and `CANCELLED` should exist at the enum/domain level only if they do not complicate MVP behavior; otherwise introduce them with the approval feature.

Alternative considered: keep jobs only in RabbitMQ until completion. This was rejected because auditability, retries, idempotency, and DingTalk follow-up all require durable state independent of queue delivery.

### 4. Use RabbitMQ behind message bus interfaces

Application services depend on:

- `MessagePublisher.publish_agent_job(job_id, correlation_id)`
- `MessageConsumer.consume_agent_jobs(handler)`

RabbitMQ implementation owns:

- `agent.job.queue`
- `agent.job.retry.queue`
- `agent.job.dead.queue`
- ack/nack behavior
- retry delay routing
- dead-letter routing

Retry policy:

- First execution plus up to three delayed retries for retryable failures.
- Retryable: internal API timeout, Loki timeout, Claude timeout, transient RabbitMQ/database/network failure.
- Non-retryable: permission denied, unknown data source, rejected SQL policy, invalid tool arguments, unsupported user request.

Alternative considered: synchronous DingTalk webhook execution. This was rejected because Claude/tool calls can exceed webhook response expectations and must not block ingress.

### 5. Wrap Claude Code Agent SDK behind `ClaudeCodeAgentClient`

`AgentExecutor.execute(job_id)` owns the use case:

```text
load job/session/messages
mark RUNNING
build execution context
load allowed skills
register read-only tools
call ClaudeCodeAgentClient.run(...)
record steps/tool calls/artifacts
mark SUCCEEDED or FAILED/TIMEOUT
send DingTalk callback
```

The SDK wrapper isolates concrete Claude Code Agent SDK APIs from domain code. The rest of the system should depend on a small internal contract:

- `prompt`
- `system_rules`
- `conversation_summary`
- `available_tools`
- `skills`
- `execution_limits`
- `final_answer`
- structured tool call events

Alternative considered: let FastAPI controllers call the SDK directly. This was rejected because it collapses ingress, job lifecycle, runtime execution, and callback concerns into one path.

### 6. Retrieve graph/business context before broad evidence queries

The Agent prompt should require an early context search for most business questions:

```text
context_search
  -> relevant ER tables/fields/enums
  -> relevant business-flow nodes/lanes/transitions
  -> compact context bundle
```

Only relevant context should be passed to Claude. The Agent must not load all ER tables or all business flows into a single prompt.

Alternative considered: pass complete graph exports to Claude. This was rejected because it wastes context, increases cost, and reduces answer quality.

### 7. Enforce read-only tools through internal API platform contracts

MVP tool names:

- `get_er_context`
- `get_business_flow_context`
- `query_loki`
- `query_database`
- `query_redis_get`
- `query_redis_scan`

Each tool call should flow through:

```text
Claude Code Agent
  -> MCP/SDK tool adapter
  -> InternalApiClient
  -> internal API endpoint
  -> permission/policy/audit/rate limit/desensitization
  -> actual gateway
```

Database policy must allow only safe read operations. Redis policy allows get/scan-style reads only. Loki policy limits tenant/service selectors, time ranges, and result sizes.

Alternative considered: register Python functions that directly open database, Redis, or Loki clients. This was rejected because credentials, policy, rate limits, and audit would be scattered across Agent runtime code.

### 8. Persist audit without storing private reasoning

The system persists:

- incoming user request
- identity and permission decisions
- job lifecycle events
- tool name and sanitized parameters
- response summary, row/log counts, time windows, and hashes or object keys for large payloads
- user-visible execution steps
- final report
- callback delivery result

The system must not persist hidden model chain-of-thought. If detailed raw tool outputs are too large or sensitive, store a compact summary in PostgreSQL and an object reference for future storage integration.

Alternative considered: store full raw tool responses in `agent_tool_call`. This was rejected because logs and query results may contain sensitive data and can quickly bloat the system database.

## Risks / Trade-offs

- SDK instability or API changes -> isolate the Claude Code Agent SDK behind `ClaudeCodeAgentClient` and test the wrapper separately.
- Agent tries to perform mutating actions -> expose only read-only tools in MVP, enforce tool policy server-side, and reject SQL/Redis/write-like operations before execution.
- DingTalk retries create duplicate jobs -> use a webhook idempotency key derived from DingTalk message identifiers and persist duplicate handling.
- Long-running analysis exceeds user expectations -> send immediate acknowledgement and optional progress messages while worker runs asynchronously.
- Tool results leak sensitive data -> summarize, mask configured fields, limit rows/log lines, and record audit metadata.
- RabbitMQ message is delivered twice -> make job state transitions idempotent and let workers lock/claim jobs before execution.
- Context search misses relevant ER/business-flow data -> record the context query and returned context bundle, and allow the Agent to perform targeted follow-up searches.
- One database becomes a bottleneck later -> keep schemas modular and prepare service boundaries, but use one PostgreSQL 16 database for MVP simplicity.

## Migration Plan

1. Create backend module skeleton and configuration loading.
2. Add PostgreSQL migrations for MVP tables and enums.
3. Add RabbitMQ publisher/consumer implementations behind message bus interfaces.
4. Add DingTalk webhook route with signature verification, idempotent job creation, and immediate acknowledgement.
5. Add Agent worker and `AgentExecutor` with a fake/stub Claude client for integration testing.
6. Add Claude Code Agent SDK wrapper and read-only tool registry.
7. Add internal API platform client/contracts and MVP read-only tool endpoints or adapters.
8. Add audit and permission checks around ingress, job execution, tool calls, and callback.
9. Verify the full local flow with PostgreSQL, RabbitMQ, fake tool responses, then with configured internal tools.

Rollback strategy: disable DingTalk webhook routing or worker consumption, keep existing persisted jobs, and stop publishing new messages. Failed/incomplete jobs remain auditable and can be retried after rollback is lifted.

## Open Questions

- Exact DingTalk robot security mode and callback mechanism to use in the deployment environment.
- Whether `project_code` should be named `service_code`, `tenant_code`, or a more general `workspace_code` before web configuration is introduced.
- Which internal systems already expose ER/business-flow context APIs and which need to be implemented in this repository.
- Whether raw tool payload object storage is required in MVP or can be deferred with PostgreSQL summaries only.
