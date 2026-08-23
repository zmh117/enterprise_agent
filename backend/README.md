# Enterprise Agent 后端

后端实现身份与 RBAC、Agent/Application 发布、Job 调度、渠道投递、标准 MCP 工具服务和审计。

```text
Ingress -> API/Dispatcher -> RabbitMQ -> Worker
       -> Python/TypeScript Agent Runtime -> tool-mcp
       -> Published Resource Revision -> bounded readonly adapter
       -> result/delivery/audit
```

## 模块边界

- `identity`、`authorization_center`：统一用户、外部身份、角色、管理能力、应用/MCP Tool/数据范围授权。
- `agent_config`：Agent Draft、Revision、Publication、Runtime kind、MCP Tool Envelope。
- `business_application`：Agent Publication 选择、MCP Tool 显式子集、渠道与执行策略、发布和激活。
- `job`：Job、Session、Outbox、Runtime invocation、Tool Call、Artifact 与 Delivery 历史。
- `mcp_tool_runtime`：固定 MCP Tool Manifest、Job 快照复核、资源解析和只读执行。
- `platform_config`：工具资源、Secret Ref、业务数据范围拓扑和配置审计。
- `managed_channel`、`webhook`、`dingding`：渠道入口、身份解析和结果投递。

API Capability、Handler、API Connection、Resource Mapping、Tool Release 生命周期和 Internal API Platform 不属于当前后端。

## 只读工具边界

代码 Manifest 当前包含：

- `get_schema_directory`
- `query_database`
- `query_redis_get`
- `query_redis_scan`
- `diagnose_loki_labels`
- `diagnose_loki_label_values`
- `diagnose_loki_probe`
- `query_loki`

约束：

- SQL 只允许有界 `SELECT` / `WITH`，并按已发布资源的 schema/表范围限制。
- Redis 只允许有界 GET/SCAN 和已配置前缀。
- Loki 强制 selector、时间窗口、返回行数和响应大小限制。
- 不提供 Bash、Shell、文件写入、更新 SQL、部署、任意 HTTP 或动态 MCP Server URL。
- Secret 不进入 Prompt、Runtime Event、Tool Call 摘要、错误或审计载荷。

## 本地命令

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
PYTHONPATH=backend .venv/bin/python -m app.cli.migrate
APP_ENV=local PYTHONPATH=backend .venv/bin/python -m app.cli.bootstrap_admin --non-interactive
PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

启动 Worker：

```bash
PYTHONPATH=backend .venv/bin/python -m app.workers.agent_job_worker
```

启动标准 MCP 工具服务：

```bash
PYTHONPATH=backend .venv/bin/python -m app.services.tool_mcp
```

完整环境优先使用：

```bash
docker compose up --build
```

## 数据库迁移

- `migrator` 是唯一 schema writer。
- 活动 schema 从 baseline `100` 开始；未来 migration 从 `101` 单调递增，禁止重用旧版本号。
- 空库执行 `100`；精确 legacy `042` 通过不可变 manifest 验证后只追加等价 marker，部分 legacy head 失败关闭。
- Compose 顺序固定为 `migrate -> bootstrap initial admin -> apply runtime grants`。
- API、Worker、Runtime 相关服务在迁移成功后启动并只读校验 schema head/checksum。
- 破坏性迁移先检查活动旧引用；已有库升级前必须完成可恢复备份。
- ONES 身份表和 Team/验证事实必须保留；旧长期个人 API Credential 必须删除。

操作手册见 [空库 Baseline 与管理员](../docs/operations/schema-baseline-bootstrap.md) 和 [Legacy 042 Adoption](../docs/operations/schema-baseline-upgrade.md)。

## ONES 身份

ONES 绑定由当前用户本人发起。邮箱和密码仅存在于验证请求内；服务端保存外部 User ID、显示名称、Team、默认 Team 和验证时间。管理员只能查看和停用，不能输入密码、代为验证或代为解绑。

## 配置

模板见仓库根目录 [.env.example](../.env.example)。数据库驱动只安装在 `tool-mcp` 所在镜像；API、Worker 不承载数据库工具执行器。

保留：

- Runtime Grant：Worker 与两个 Runtime 间的独立调用边界。
- Model Probe Token：模型连接测试边界。
- Master Key：平台 Secret 静态加密根。

禁止恢复：

- `INTERNAL_API_*`
- `RUNTIME_TOOL_MCP_*`
- MCP 专用 HS256 issuer/verifier/signing key
- 旧 Internal API server/client Token

## 验证

```bash
.venv/bin/python -m compileall -q backend/app
.venv/bin/pytest -q backend/tests
.venv/bin/python scripts/check_markdown_links.py
docker compose config --quiet
```

双 Runtime Compose 验收脚本必须通过 `tool-mcp` 产生真实 Tool Call 与 Runtime Event 证据，不能只以容器健康或配置存在作为成功依据。
