## Context

当前后端已经具备 Web-managed secret、DB-backed runtime config、RabbitMQ worker、Claude/DeepSeek runtime 和 Internal API Platform 的代码能力，并且单元测试已经覆盖核心逻辑。但真实本地闭环仍然依赖 Docker Compose 的服务环境、PostgreSQL migration、容器启动顺序、服务重启读取配置、RabbitMQ 消费和 curl 调试路径。

这次 change 的重点不是新增业务功能，而是把这些能力串成一个可重复的 smoke 验证流程：

```text
docker compose
  ├─ postgres
  ├─ rabbitmq
  ├─ api-server
  └─ agent-worker

curl:
  POST /api/platform/secrets
  POST /api/platform/runtime-config/values
  restart api-server / agent-worker
  GET  /api/ready
  POST /api/agent/jobs
  GET  /api/agent/jobs/{job_id}
  GET  /api/agent/jobs/{job_id}/steps
  GET  /api/agent/jobs/{job_id}/tool-calls
```

## Goals / Non-Goals

**Goals:**

- 提供一份中文 smoke 文档，能从空的本地 Docker Compose 环境开始验证 DB-backed config。
- 覆盖 Web-managed secret 创建、runtime config 写入、服务重启生效、ready/source 检查、Agent job 执行和 debug API 查询。
- 默认使用 synthetic 问题，避免把真实业务数据发给外部模型。
- 提供可选脚本或 Make target，自动执行主要 curl 步骤并输出关键断言。
- 明确失败排查路径：PostgreSQL、RabbitMQ、api-server、agent-worker、runtime_config degraded、job status、worker logs。

**Non-Goals:**

- 不新增 Web 页面。
- 不改变 Agent 业务执行逻辑。
- 不引入真实写操作、代码修改、删 Redis、更新数据库或重启业务服务能力。
- 不强制调用真实 DeepSeek；真实模型 smoke 只能作为显式可选路径。
- 不把 `.env` 中的 bootstrap-only 配置迁入 DB。

## Decisions

### 1. Smoke 默认使用 stub Claude + fake/internal tool 低风险路径

默认 smoke 应验证配置链路和 job worker 闭环，而不是验证外部模型质量：

```text
FEATURE_REAL_CLAUDE=false
FEATURE_REAL_INTERNAL_TOOLS=false 或 mock/local tool profile
```

这样能稳定验证：

```text
DB secret -> DB runtime config -> service overlay -> job -> worker -> SUCCEEDED
```

真实 DeepSeek 作为单独可选段落，并要求使用合成输入。

### 2. curl 文档是主交付物，脚本只是辅助

脚本可以减少手工错误，但不能替代文档。文档必须保留每个 curl 命令和预期 JSON 字段，因为后续排查容器问题时，开发者需要能停在任意一步检查。

### 3. 服务重启是第一版生效语义

DB-backed runtime config 当前是启动时 overlay。smoke 流程在写入 runtime config 后必须重启：

```bash
docker compose restart api-server agent-worker
```

后续如果做 reload endpoint，再单独提 change。

### 4. 明文检查必须成为 smoke 断言

secret 创建和 runtime config snapshot 的响应中不得包含 DeepSeek key。脚本如果存在，只能打印 `secret_ref`、`configured`、`runtime_config.source`、`job_id` 和 job 状态，不得 echo 原始 key。

## Risks / Trade-offs

- [Risk] 使用真实 DeepSeek 会把 prompt/tool summary 发到外部 API。  
  Mitigation: 默认 smoke 使用 stub；真实模型段落必须标记为可选，并要求 synthetic/sanitized 输入。

- [Risk] Compose 环境里 api-server 和 agent-worker 读取配置时机不同。  
  Mitigation: 文档要求写入 runtime config 后重启两个服务，并检查 `/api/ready` 的 `runtime_config.source`。

- [Risk] curl 命令过多导致用户手动复制出错。  
  Mitigation: 保留逐步 curl，同时提供可选脚本或 Make target 作为快速路径。

- [Risk] local-tools/real-tools profile 引入 Loki/DB 上游依赖，导致 smoke 不稳定。  
  Mitigation: 主 smoke 不依赖真实上游；real-tools 作为扩展验证。

## Migration Plan

1. 新增 smoke 文档，先覆盖默认 stub/fake 工具闭环。
2. 如需要，新增脚本或 Make target 执行主要 curl。
3. 在文档中补充真实 DeepSeek 可选段落和安全提示。
4. 运行 Docker Compose smoke，记录一次成功输出样例。
5. 保持 `openspec validate` 和现有测试通过。
