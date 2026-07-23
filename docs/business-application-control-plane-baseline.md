# Business Application 控制面实施基线

记录日期：2026-07-23。

## 变更前边界

- Agent 使用 `agent_definition`、`agent_revision`、`agent_publication`。
- Workflow 使用 `agent_workflow_template` 和 `agent_workflow_publication`。
- Channel Connector 由 `integration_connector` 与 `ConnectorRegistry` 管理。
- Web 管理面使用 Web Session、CSRF、统一内部用户与 RBAC。
- 管理前端只有静态 Dashboard，业务应用来自 `frontend/src/mocks/dashboard.ts`。
- 钉钉、Webhook、RabbitMQ Worker、Agent Job 与 Delivery 均未读取
  `business_application`；本变更不得修改这些调用链。

## 自动化基线

- 后端 pytest：257 passed，10 skipped，4 subtests passed。
- Ruff：通过。
- mypy：已有 4 个非本变更错误，位于
  `admin/application/scope.py` 和 `admin/infrastructure/rabbitmq_status.py`。
- 前端：lint、typecheck、5 个测试和 production build 通过。

## 迁移顺序

仓库已有 `009_admin_web_read_models.sql` 和
`009_agent_job_retry_failure_delivery.sql`。迁移器按完整文件名字典序执行，
两者顺序保持不变；Business Application 使用 `010`。
