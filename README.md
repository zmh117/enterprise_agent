# Enterprise Agent

企业内部受治理的多 Agent / Business Application 平台。当前主线使用 Python 控制面与 Worker、独立 TypeScript Claude Agent Runtime，以及 ONES/Data MCP Server。

```text
钉钉 / Webhook / Debug
→ Inbox / Outbox
→ RabbitMQ
→ Python Worker（Job、授权、retry、持久化）
→ TypeScript Agent Runtime（Claude Agent SDK）
→ ONES / Data MCP（DB、Redis、Loki）
→ Artifact / Delivery Outbox
→ 钉钉 / Webhook / Email
```

核心边界：

- PostgreSQL 是配置、Publication、身份、Job 和审计事实源；
- Agent Publication 冻结模型、Skill 和 MCP Tool 最大集合；
- Business Application 冻结 Agent Publication、MCP/Resource 子集、Trigger、Delivery 和环境 deployment；
- Agent 不接触数据库密码、模型 Key 或底层连接信息；
- Python Worker 没有 Master Key、Node/Claude CLI 或 Provider egress；
- API Capability、Handler/Connection 和 Internal API Platform 已彻底退役，不迁移、不备份、不恢复。

## 开发验证

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'

cd agent-runtime
npm ci
npm run preflight:static
npm run lint
npm run typecheck
npm test
npm run build

cd ../frontend
npm ci
npm run lint
npm run typecheck
npm test
npm run build

cd ..
.venv/bin/pytest
docker compose config --quiet
```

## 本地 Compose

首次启动前按 `.env.example` 准备仓库外 Master Key、Runtime Grant keypair、MCP signing key 和模型探针 Token：

```bash
docker compose up --build
```

不要在正在承载真实钉钉连接或 Job 的环境中直接 recreate；先按 Runbook 安排入口暂停、在途 Job 和观察窗口。

## 文档

- [当前系统架构](docs/chatgpt-context/02-system-architecture.md)
- [当前运行链路](docs/chatgpt-context/04-runtime-flows.md)
- [部署与运维](docs/chatgpt-context/06-deployment-and-operations.md)
- [TypeScript Runtime 切换与回滚](docs/typescript-agent-runtime-cutover.md)
- [MCP 不可恢复退役 Runbook](docs/mcp-cutover-runbook.md)
- [统一身份与 RBAC](docs/unified-identity-rbac-admin.md)
- [多 Application 路由](docs/multi-application-agent-worker-and-dingtalk-bot-routing.md)

当前 OpenSpec 变更为 `migrate-agent-runtime-to-typescript`。真实 canary、生产窗口、旧 Python Runtime 删除和归档仍需用户明确验收，不能由测试结果自动完成。
