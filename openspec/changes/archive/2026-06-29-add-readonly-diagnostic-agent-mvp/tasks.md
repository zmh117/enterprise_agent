## 1. Backend Foundation

- [x] 1.1 Create the FastAPI backend package layout under `backend/app` with `shared`, `modules`, and `workers` boundaries.
- [x] 1.2 Add project configuration for PostgreSQL 16, RabbitMQ, DingTalk, Claude Code Agent SDK, internal API platform, execution limits, and feature flags.
- [x] 1.3 Add structured logging, request correlation IDs, and shared exception types for API and worker processes.
- [x] 1.4 Add local development orchestration for `api-server`, `agent-worker`, `postgres:16`, and `rabbitmq`.
- [x] 1.5 Add health and readiness endpoints that verify database and RabbitMQ connectivity without invoking Claude.

## 2. PostgreSQL Persistence

- [x] 2.1 Add database connection management and migration tooling for PostgreSQL 16.
- [x] 2.2 Create migrations for `agent_session`, `agent_job`, `agent_message`, `agent_step`, `agent_tool_call`, `agent_artifact`, and `audit_event`.
- [x] 2.3 Create migrations for persisted configuration tables including `tool_definition`, `integration_connector`, `datasource_registry`, and `permission_policy`.
- [x] 2.4 Implement repositories for Agent sessions, jobs, messages, steps, tool calls, artifacts, audit events, and configuration records.
- [x] 2.5 Add repository tests covering job creation, idempotency keys, status transitions, retry metadata, result persistence, and audit linkage.

## 3. Job Lifecycle and Message Bus

- [x] 3.1 Implement job domain models and status rules for PENDING, RUNNING, SUCCEEDED, FAILED, and TIMEOUT.
- [x] 3.2 Implement `CreateAgentJobService`, `JobStatusService`, and `JobRetryService` with idempotent job creation and controlled status transitions.
- [x] 3.3 Define message bus publisher and consumer interfaces that hide RabbitMQ-specific types from job and agent modules.
- [x] 3.4 Implement RabbitMQ publisher and consumer for `agent.job.queue`, `agent.job.retry.queue`, and `agent.job.dead.queue`.
- [x] 3.5 Implement retry classification for retryable and non-retryable failures with first execution plus three delayed retries.
- [x] 3.6 Implement worker job claiming so duplicate deliveries cannot execute the same job concurrently.
- [x] 3.7 Add tests for dispatch, retry, dead-letter routing, duplicate delivery handling, and non-retryable failure handling.

## 4. DingTalk Ingress and Callback

- [x] 4.1 Implement `POST /webhooks/dingding/agent` with DingTalk signature verification before persistence.
- [x] 4.2 Parse DingTalk conversation identity, user identity, message identity, source channel, and message content into application DTOs.
- [x] 4.3 Connect DingTalk ingress to permission checks, idempotent Agent session/job creation, user message persistence, and queue dispatch.
- [x] 4.4 Return an immediate DingTalk acknowledgement after the job is persisted and dispatched.
- [x] 4.5 Implement DingTalk callback delivery for final reports and safe failure notices.
- [x] 4.6 Add tests for valid webhook, invalid signature, duplicate delivery, unauthorized user, successful acknowledgement, and final callback formatting.

## 5. Permission and Audit

- [x] 5.1 Implement user allowlist, service or project allowlist, tool allowlist, and read-only risk policy checks backed by PostgreSQL configuration.
- [x] 5.2 Enforce permission checks before Agent job creation and before each tool execution.
- [x] 5.3 Implement audit service methods for webhook receipt, identity parsing, permission decisions, job creation, queue dispatch, worker claim, tool calls, retries, failures, result creation, and DingTalk callbacks.
- [x] 5.4 Implement safe request and response summary helpers that mask sensitive fields and bound stored payload sizes.
- [x] 5.5 Add tests proving denied users do not create jobs, denied tools do not execute, and successful jobs produce linked audit records.

## 6. Read-only Internal Tool Platform

- [x] 6.1 Implement internal API client contracts used by Agent tools for ER context, business-flow context, Loki, Redis, and database evidence.
- [x] 6.2 Implement MVP tool adapters for `get_er_context`, `get_business_flow_context`, `query_loki`, `query_database`, `query_redis_get`, and `query_redis_scan`.
- [x] 6.3 Implement compact context search responses that return only relevant ER tables, fields, enums, relationships, business-flow nodes, and flow edges.
- [x] 6.4 Enforce read-only SQL policy that accepts bounded safe read queries and rejects insert, update, delete, DDL, privileged, or unsafe statements.
- [x] 6.5 Enforce Redis policy that accepts get and bounded scan operations and rejects delete, set, expire, flush, or script execution.
- [x] 6.6 Enforce Loki policy for allowed tenant or service selectors, time ranges, query size, and result size.
- [x] 6.7 Persist tool-call summaries, policy decisions, durations, statuses, and audit links for every tool execution or rejection.
- [x] 6.8 Add tests proving tools route through internal API clients and never direct runtime connections to database, Redis, Loki, ER, or business-flow storage.

## 7. Claude Diagnostic Runtime

- [x] 7.1 Implement `AgentExecutor.execute(job_id)` to load persisted job context, mark jobs RUNNING, invoke runtime execution, persist outputs, and finish jobs.
- [x] 7.2 Implement `AgentContextBuilder` with system role, read-only safety rules, user question, service or project code, allowed tools, tool restrictions, retrieved context, and safe conversation summary.
- [x] 7.3 Implement `ClaudeCodeAgentClient` wrapper around the Python Claude Code Agent SDK with a narrow internal contract and test double support.
- [x] 7.4 Implement Skill loading for `bug-analysis`, `sql-diagnosis`, `redis-diagnosis`, and `loki-log-analysis`.
- [x] 7.5 Register only read-only MCP or SDK tools in the MVP runtime and reject unavailable mutating tool requests.
- [x] 7.6 Persist user-visible Agent steps, assistant messages, final report artifacts, and safe error information without storing private model reasoning.
- [x] 7.7 Add tests for successful diagnostic execution, SDK wrapper failure, timeout, mutating tool rejection, evidence-based report shape, and no chain-of-thought persistence.

## 8. Worker and End-to-End Verification

- [x] 8.1 Implement `workers/agent_job_worker.py` to consume message bus jobs, call AgentExecutor, ack successful messages, and route retry or dead-letter cases.
- [x] 8.2 Add seeded local configuration for allowlisted DingTalk users, tool definitions, connectors, data sources, and permission policies.
- [x] 8.3 Add integration tests using fake DingTalk requests, fake Claude client, fake internal tools, PostgreSQL, and RabbitMQ to verify the full accepted-job-to-callback path.
- [x] 8.4 Add integration tests for invalid signature, duplicate DingTalk delivery, unauthorized user, retryable tool timeout, non-retryable policy rejection, and duplicate RabbitMQ delivery.
- [x] 8.5 Document local run commands, required environment variables, queue names, database tables, and the MVP read-only boundary.
- [x] 8.6 Run formatting, linting, type checks, unit tests, integration tests, and OpenSpec validation before marking the change ready for archive.
