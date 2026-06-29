## Why

The first version of the enterprise Agent platform needs a reliable Claude Code Agent execution chain before broader platform features are added. The immediate business value is a read-only diagnostic Agent that receives DingTalk questions, gathers internal evidence through controlled tools, and returns an auditable analysis report without modifying code, services, Redis, or databases.

## What Changes

- Add a DingTalk enterprise robot entrypoint that validates webhook requests, identifies the user/conversation, creates an Agent task, and acknowledges receipt quickly.
- Add a persisted Agent job lifecycle backed by PostgreSQL 16, with sessions, jobs, messages, status transitions, retry metadata, results, and failure reasons stored in one database.
- Add an independent message bus module for RabbitMQ publishing, consuming, retry, and dead-letter handling; Agent execution must depend on queue interfaces, not RabbitMQ details.
- Add an Agent worker that consumes job messages and invokes a Python Claude Code Agent SDK runtime through a focused wrapper.
- Add read-only MCP/SDK tools that call an internal API platform for ER context, business-flow context, Loki, Redis, and database queries instead of connecting to those systems directly.
- Add permission and audit boundaries for user allowlists, project/service/tool allowlists, read-only tool policy enforcement, tool-call records, step summaries, and report artifacts.
- Reserve module boundaries for later web configuration, sandbox execution, approvals, code-fix agents, and additional integration services without implementing mutation workflows in this MVP.

Non-goals for this change:

- Automatic code edits, PR creation, test execution, deployment, restarts, database updates, Redis deletion, or other write operations.
- Complex multi-Agent orchestration, full visual execution timelines, or a complete web administration UI.
- Direct database, Redis, or Loki access from Claude Code Agent runtime.

## Capabilities

### New Capabilities
- `dingtalk-agent-ingress`: DingTalk webhook intake, request verification, user/conversation parsing, immediate receipt acknowledgement, and final reply delivery.
- `agent-job-lifecycle`: PostgreSQL-backed Agent sessions, jobs, messages, status changes, retry metadata, RabbitMQ dispatch, retry queues, and dead-letter handling.
- `claude-diagnostic-runtime`: Python Claude Code Agent SDK execution wrapper, context construction, skill loading, tool registration, worker execution, and evidence-based final report generation.
- `readonly-tool-platform`: Read-only internal tool gateway for ER context, business-flow context, Loki, Redis, and database queries through internal APIs.
- `agent-audit-permission`: User/tool access checks, read-only risk policy, audit records, tool-call summaries, execution steps, report artifacts, and failure records.

### Modified Capabilities
- None.

## Impact

- New backend modules under the future FastAPI service: `dingding`, `job`, `message_bus`, `agent`, `internal_tools`, `permission`, and `audit`.
- New worker process for Agent job consumption and Claude Code Agent SDK execution.
- New PostgreSQL 16 schema for sessions, jobs, messages, tool calls, steps, artifacts, and audit records.
- New RabbitMQ queues: `agent.job.queue`, `agent.job.retry.queue`, and `agent.job.dead.queue`.
- New internal API platform endpoints or client contracts for ER context, business-flow context, Loki, Redis, and database read queries.
- New Skill assets for bug analysis, SQL diagnosis, Redis diagnosis, and Loki log analysis.
