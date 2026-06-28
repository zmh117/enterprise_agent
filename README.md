# 企业级只读诊断 Agent 平台 MVP

这是一个企业内部只读诊断 Agent 平台的 MVP。第一版目标不是做“大而全 Agent 平台”，而是先跑通 Claude Code Agent 的诊断执行链路：

```text
钉钉用户提问
  -> FastAPI Webhook
  -> 创建并持久化 Agent 任务
  -> RabbitMQ 异步投递
  -> Agent Worker 消费任务
  -> Claude Code Agent SDK 包装层执行
  -> 只读工具查询 ER 图 / 业务图 / Loki / Redis / 数据库
  -> 生成带证据的分析报告
  -> 回调钉钉
  -> 全链路审计、可重试、可扩展
```

## MVP 边界

第一版只做只读诊断：

- 钉钉企业机器人接入
- Agent 任务创建和状态流转
- PostgreSQL 16 持久化
- RabbitMQ 消息队列
- Python Claude Code Agent SDK 包装层
- Skill 加载
- 只读 MCP / SDK 工具注册
- 内部 API 平台调用
- 权限校验和审计记录
- 失败重试和死信处理
- 最终报告回调钉钉

第一版明确不做：

- 自动改代码
- 自动提交 PR
- 自动删 Redis key
- 自动执行 SQL 更新
- 自动重启服务
- 自动发版
- 复杂多 Agent 协作
- 完整沙盒执行器
- Web 管理后台

## 架构

```text
DingTalk 企业机器人
  -> api-server
  -> job 模块
  -> message_bus 模块
  -> RabbitMQ
  -> agent-worker
  -> agent 模块
  -> ClaudeCodeAgentClient
  -> readonly-tool-platform
  -> Internal API Platform
      -> ER Context
      -> Business Flow Context
      -> Loki
      -> Redis
      -> Database
  -> audit / permission
  -> DingTalk Callback
```

核心原则：

- `agent` 只负责执行 Agent 任务。
- `message_bus` 负责消息投递，不把 RabbitMQ 细节揉进 Agent 模块。
- `internal_tools` 只通过内部 API 平台访问数据源，不允许 Agent runtime 直连数据库、Redis、Loki。
- `audit` 记录用户请求、权限决策、任务状态、工具调用摘要、最终报告和失败原因。
- 不持久化模型私有推理链，只保存可审计步骤和证据摘要。

## 目录结构

```text
backend/
  app/
    main.py
    bootstrap.py
    shared/
      config.py
      database.py
      exceptions.py
      logging.py
    modules/
      agent/
      audit/
      dingding/
      internal_tools/
      job/
      message_bus/
      permission/
    workers/
      agent_job_worker.py
  migrations/
  seeds/
  tests/

.claude/
  skills/
    bug-analysis/
    sql-diagnosis/
    redis-diagnosis/
    loki-log-analysis/

openspec/
  changes/
    add-readonly-diagnostic-agent-mvp/
```

## 本地开发

创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

运行完整检查：

```bash
make check
```

`make check` 会执行：

- Python 编译检查
- Ruff 格式检查
- Ruff lint
- MyPy 类型检查
- Pytest 测试
- Unittest 测试
- OpenSpec 校验

## 启动服务

使用 Docker Compose 启动：

```bash
docker compose up --build
```

本地直接启动 API：

```bash
.venv/bin/python -m uvicorn app.main:create_app --factory --app-dir backend --host 0.0.0.0 --port 8000
```

启动 worker：

```bash
PYTHONPATH=backend .venv/bin/python -m app.workers.agent_job_worker
```

## 环境变量

常用配置：

- `DATABASE_DSN`：PostgreSQL 连接串
- `RABBITMQ_URL`：RabbitMQ 连接串
- `DINGTALK_SECRET`：钉钉机器人签名密钥
- `DINGTALK_CALLBACK_URL`：钉钉结果回调地址
- `DINGTALK_CALLBACK_HOST_ALLOWLIST`：允许回调的 host 白名单
- `INTERNAL_API_BASE_URL`：内部 API 平台地址
- `CLAUDE_MODEL`：Claude 模型名
- `FEATURE_REAL_CLAUDE`：是否启用真实 Claude 调用
- `AGENT_MAX_RETRY_COUNT`：最大重试次数，默认 3
- `AGENT_RETRY_DELAY_SECONDS`：重试延迟秒数
- `AGENT_TIMEOUT_SECONDS`：Agent 执行超时时间
- `MAX_TOOL_RESPONSE_CHARS`：工具响应摘要最大长度
- `MAX_LOKI_MINUTES`：Loki 查询最大时间范围
- `MAX_LOKI_LINES`：Loki 查询最大日志行数
- `REDIS_SCAN_LIMIT`：Redis scan 最大返回数量

## 队列

RabbitMQ 队列：

- `agent.job.queue`：正常 Agent 任务队列
- `agent.job.retry.queue`：延迟重试队列
- `agent.job.dead.queue`：死信队列

应用层只依赖 `MessagePublisher` / `MessageConsumer` 接口，RabbitMQ 实现在 `backend/app/modules/message_bus/infrastructure/`。

## 数据库表

执行链路表：

- `agent_session`
- `agent_job`
- `agent_message`
- `agent_step`
- `agent_tool_call`
- `agent_artifact`
- `audit_event`

配置表：

- `tool_definition`
- `integration_connector`
- `datasource_registry`
- `permission_policy`

迁移文件位于 [backend/migrations](/Users/mhz/Develop/enterprise_agent/backend/migrations)。

## 只读工具

MVP 工具：

- `get_er_context`
- `get_business_flow_context`
- `query_loki`
- `query_database`
- `query_redis_get`
- `query_redis_scan`

策略限制：

- SQL 只允许 `SELECT` / `WITH`。
- Redis 只允许 `get` 和有上限的 `scan`。
- Loki 必须限制服务、时间范围和返回行数。
- 所有工具调用都要经过权限检查、策略检查、审计记录和响应摘要。

## 当前验证状态

已通过：

```bash
make check
```

当前测试覆盖：

- 钉钉签名成功 / 失败
- 重复钉钉消息幂等
- 未授权用户拒绝
- 任务创建、状态流转、重复 worker claim
- 失败重试和死信路径
- 只读 SQL / Redis / Loki 策略
- 工具必须通过内部 API client
- Agent 上下文构造和报告产物持久化
- 不保存模型私有推理链
- 钉钉到 Agent 再到回调的端到端假链路

