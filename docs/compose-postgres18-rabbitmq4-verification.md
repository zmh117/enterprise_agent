# PostgreSQL 18 / RabbitMQ 4 实际验证记录

验证日期：2026-07-12（Asia/Shanghai）

## 1. 升级前状态

```text
PostgreSQL: 16.14
PostgreSQL image: postgres:16
PostgreSQL old volume: 9f83d2df1639092764839b9ce4cbb98439b84322d1d2db3dd22898acb62d06a8

RabbitMQ: 3.13.7
RabbitMQ image: rabbitmq:3-management
RabbitMQ old volume: d8f3306dc326be6614a3468b8315da91c6e0e7a60b2e7c296047c811304df4c6
```

升级前 `agent.job.queue` 的 ready/unacked 均为 0，retry/dead queue 尚未声明。旧卷未删除。

逻辑备份目录：

```text
.local/compose-infra-upgrade/20260712T072029Z
```

该目录不进入 Git，包含数据库 custom dump、globals、迁移前指标、preflight 和校验信息。

## 2. 升级后状态

```text
PostgreSQL: 18.4
PostgreSQL data_directory: /var/lib/postgresql/18/docker
PostgreSQL image digest: postgres@sha256:22c89fe0d0f507606260237fd55e51f6137f58b2d5bcf6152242b96d9fe8f9a4
PostgreSQL volume: enterprise_agent_postgres18_data

RabbitMQ: 4.3.2
RabbitMQ image digest: rabbitmq@sha256:76412b1ed2865b88ed01b4a504f72e888842f2089a7527743d325ce7c9d3a43b
RabbitMQ volume: enterprise_agent_rabbitmq4_data
```

迁移前后关键业务表记录数一致。`platform_runtime_config_definition` revision 从 86 前进到 87，原因是恢复后 migration/seed 补齐 builtin definition；其余配置 revision 未回退。

## 3. RabbitMQ 4 队列兼容性

执行：

```bash
RUN_RABBITMQ4_INTEGRATION=1 \
  .venv/bin/python -m pytest backend/tests/test_rabbitmq4_integration.py -q
```

结果：`1 passed`。隔离临时 durable queue 上的 job、retry、dead-letter 消息均为 persistent delivery mode，重复声明成功，消息可读取并 ack，测试后临时队列已删除。

## 4. Agent Job 成功闭环

执行：

```bash
SMOKE_BUILD=false scripts/smoke_rabbitmq4.sh
```

实际链路：

```text
POST /api/agent/jobs
  -> PostgreSQL 18 持久化
  -> RabbitMQ 4 agent.job.queue
  -> agent-worker 消费并 ack
  -> job SUCCEEDED
  -> steps/tool-calls 可查询
```

验证 job：

```text
job_id: job_69bec89cc511488b8a6a573eeaabe3fc
status: SUCCEEDED
tool_calls: 2
```

本次使用 stub Claude，仅验证基础设施和任务执行闭环，不调用外部模型。

验证后已将运行时配置恢复为升级前的真实模式，且新版 `smoke_rabbitmq4.sh` 不再调用会改写 DB runtime config 的旧 smoke。当前 `/api/ready` 已确认：

```text
feature_real_claude: true
feature_real_internal_tools: true
anthropic_api_key_configured: true
runtime_config.source: database
runtime_config.degraded: false
```

`internal-api-platform`、`dingtalk-stream-ingress`、`api-server` 和 `agent-worker` 均已重新启动；DeepSeek secret 通过容器部署环境安全 rotate 回数据库，过程中未输出 secret 明文。

## 5. Retry / Dead-letter 一致性

执行真实 PostgreSQL 18 + RabbitMQ 4 隔离队列集成测试：

```bash
RUN_RABBITMQ4_FAILURE_INTEGRATION=1 \
  .venv/bin/python -m pytest \
  backend/tests/test_rabbitmq4_job_failure_integration.py -q
```

结果：`1 passed`。

```text
job_273f155ec0e64125ab9631bd39f06f4c
  job status: PENDING
  retry_count: 1
  audit: job.failure.retry / RETRYING
  RabbitMQ: retry message published and ack verified

job_d93196cbae5344e584e65a7e938bb41e
  job status: FAILED
  retry_count: 0
  audit: job.failure.dead / FAILED
  RabbitMQ: dead-letter message published and ack verified
```

测试使用唯一临时队列，完成后已删除；正式 `agent.job.queue` 最终状态为 ready=0、unacked=0、consumer=1。

## 6. 保留与回滚

升级验收完成，但旧匿名卷和 `.local` 逻辑备份仍保留。当前未执行 `docker compose down -v`、`docker volume prune` 或任何旧卷清理操作。回滚方法见 [升级手册](compose-postgres18-rabbitmq4-upgrade.md)。

## 7. 自动化测试结果

本次变更相关检查：

```text
RabbitMQ 4 broker integration: 1 passed
RabbitMQ 4 retry/dead + PostgreSQL audit integration: 1 passed
Compose/runtime/worker focused tests: 18 passed
ruff: passed
shell bash -n: passed
docker compose config --quiet: passed
OpenSpec strict validation: passed
```

全量 `backend/tests` 结果：

```text
180 passed, 8 skipped, 5 failed, 4 subtests passed
```

剩余 5 项均在既有 `backend/tests/test_platform_config.py`：当前 example topology 实际生成 20 个 resource，但测试常量 `_EXAMPLE_RESOURCE_COUNT` 为 18；另有一个 DB-backed snapshot 因相同拓扑/资源校验问题返回 `database-invalid`。这些失败不涉及 Compose 镜像、PostgreSQL 迁移、RabbitMQ publisher/consumer 或本次新增脚本，未在本 change 中修改。
