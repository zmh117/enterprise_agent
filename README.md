# 企业级只读诊断 Agent 平台

这是一个面向企业内部诊断场景的 Agent 平台。平台保留身份、RBAC、应用发布、资源、Secret、审计和 Job 历史治理；工具协议统一为标准 MCP，不提供任意 URL、脚本、Shell 或写操作执行器。

```text
钉钉 / Webhook / Debug API
  -> FastAPI Control Plane
  -> PostgreSQL + RabbitMQ
  -> agent-worker
  -> Python Runtime 或 TypeScript Runtime
  -> tool-mcp 或 ones-mcp
  -> 已发布工具资源 / 当前用户加密 ONES 凭据
  -> Job / Tool Call / Delivery / Audit
```

旧 API Capability、Handler、API Connection、Application Resource Mapping 和 Internal API Platform 已永久退役。`tool-mcp` 使用代码 Manifest 暴露固定只读工具，Agent Publication 冻结 tool identifier 与 schema hash，Application Publication 只能选择其显式子集。

ONES 本人身份绑定属于统一身份体系，独立于旧 API Platform。绑定保存 ONES User ID、Team、默认 Team，以及用平台主密钥加密的登录材料和当前 Token；所有公开投影只返回凭据状态。Agent 只能通过短期 Ed25519 Principal JWT 调用独立 `ones-mcp`，JWT 不携带 ONES 身份或凭据。

## 当前边界

- 两个独立 Agent Runtime：`python-v1` 与 `typescript-v1`。
- 一个 Worker 负责调度，并按 Agent Publication 选择对应 Runtime。
- 标准 MCP Server：`tool-mcp` 继续无个人认证；`ones-mcp` 使用 MCP Python SDK 2.0 无状态 Streamable HTTP，仅发布 `ones_work_item_search` 并验证短期 Principal JWT；第一阶段不提供 Cursor/stdio 旁路。
- 只读工具：ER、业务流、数据库 schema/query、Redis、Loki。
- 工具资源：Draft、技术验证、Publish、Disable、Archive；运行时只解析已发布 Revision。
- 工具目标由 Agent 根据用户输入和发布 Skill 在每次 Tool Call 中显式提供，服务端实时复核角色、应用、数据范围和唯一资源。
- Runtime Grant、Model Probe Token 和配置 Master Key 是其它边界，不属于已退役的 MCP/平台签名密钥。

## 快速开始

已有数据库升级前先阅读 [Schema Baseline 升级手册](docs/operations/schema-baseline-upgrade.md)。`migrator` 是唯一 schema 写入入口；失败时必须修复迁移，不要绕过 `service_completed_successfully`。

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
make check
docker compose up --build
```

本地主 Compose 会同时启动内部 `ones-mock`，供 ONES 本人绑定、Token 刷新和
`ones_work_item_search` 验收使用；该服务不发布宿主端口。生产部署必须显式覆盖为
受信 HTTPS ONES Provider，`APP_ENV=production` 会拒绝仓库内 HTTP Mock 默认值。

查看服务状态：

```bash
docker compose ps
docker compose logs migrator tool-mcp ones-mcp agent-worker
```

Compose 的核心执行服务为：

- `api-server`、`admin-web`
- `postgres`、`rabbitmq`
- `agent-worker`
- `python-agent-runtime`、`typescript-agent-runtime`
- `tool-mcp`、`ones-mcp`、仅本地验收使用的内部 `ones-mock`
- 钉钉、Webhook、投递和附件 Worker

## 配置与 Secret

`.env` 只放 bootstrap 和部署连接参数，模板见 [.env.example](.env.example)。Secret 明文不写入 Git；平台 Secret 通过 `secret://platform/<code>` 引用。工具资源、模型连接和渠道配置在管理端分别维护。

常用保护性配置：

- `DATABASE_DSN`
- `APP_CONFIG_MASTER_KEY_FILE`
- `RUNTIME_GRANT_*`
- `PRINCIPAL_JWT_PRIVATE_KEY_FILE`、`PRINCIPAL_JWKS_FILE`
- `MODEL_PROBE_AUTH_TOKEN_FILE`
- 两个 Runtime 的固定服务 URL

仓库不再接受 `INTERNAL_API_*`、`RUNTIME_TOOL_MCP_*` 或旧 HS256 MCP signing key 配置。

## 测试数据与验证

本地 MySQL、SQL Server、Oracle、Redis 和 Loki 测试数据说明见 [Agent 测试数据](docs/guides/agent-test-data.md)：

```bash
scripts/agent_test_data.sh up
scripts/agent_test_data.sh verify
scripts/agent_test_data.sh reset --yes
```

资源连接验证成功后，仍需在管理端发布 Resource Revision，运行中的 `tool-mcp` 才会解析它。

常用质量检查：

```bash
make check
cd frontend && npm run build
openspec validate --all --strict
docker compose config --quiet
```

## 相关文档

- [文档总索引](docs/README.md)
- [统一身份、RBAC 与 Agent 管理端](docs/architecture/unified-identity-rbac-admin.md)
- [连续对话与多模态附件](docs/architecture/continuous-multimodal-conversations.md)
- [Admin Web MVP](docs/architecture/admin-web-mvp.md)
- [标准 MCP 工具服务](docs/architecture/tool-mcp.md)
- [统一身份 ONES MCP](docs/architecture/identity-aware-ones-mcp.md)
- [数据库备份与恢复](docs/operations/compose-postgres18-rabbitmq4-upgrade.md)
