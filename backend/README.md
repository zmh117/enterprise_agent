# Enterprise Agent 后端

后端实现身份与 RBAC、Agent/Application 发布、Job 调度、渠道投递、标准 MCP 工具服务和审计。

```text
Ingress -> API/Dispatcher -> RabbitMQ -> Worker
       -> Python Agent Runtime -> tool-mcp / ones-mcp / dingtalk-mcp / optional knowledge-mcp / File MCP
       -> Published Resource / current business identity / governed file version
       -> external mutation: intent -> confirmation -> external-action-worker
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
- `external_action`：外部操作意图、确认、固定Provider分派与结果卡片。
- `file_workspace`、`document_processing`：文件事实、准入、Docling处理与生命周期。
- `knowledge`：统一来源与版本、知识库收录、受限 ONES 离线导入、分块/Embedding/Qdrant 索引、受管同步及在线目录/检索授权。平台治理与可配置内容存储分别管理；线上 MCP 是可选扩展，不自动发布资源或授予读取权限。

当前协议为 Runtime 1.5（代码支持 1.4），Agent Runtime 仅为 `python-v1`。截至 2026-10-04，迁移目录为 `100..146`；实际目标 head 以部署镜像的 migration catalog 为准。规范入口为[领域导航](../openspec/specs/README.md)，代码存在不等于目标环境验收通过。

API Capability、Handler、API Connection、Resource Mapping、Tool Release 生命周期和 Internal API Platform 不属于当前后端。

## 只读工具边界

`tool-mcp`的资源工具目录包含：

- `get_schema_directory`
- `query_database`
- `query_redis_get`
- `query_redis_scan`
- `diagnose_loki_labels`
- `diagnose_loki_label_values`
- `diagnose_loki_probe`
- `query_loki`
- `list_available_tool_resources`

约束：

- SQL 只允许有界 `SELECT` / `WITH`，并按已发布资源的 schema/表范围限制。
- Redis 只允许有界 GET/SCAN 和已配置前缀。
- Loki 强制 selector、时间窗口、返回行数和响应大小限制。
- 资源工具不提供更新SQL、Redis mutation、部署、任意HTTP或动态MCP Server URL。文件Sandbox内的受限Write/Edit与File MCP提交，以及ONES/钉钉逐次确认mutation，分别属于独立治理边界；不能把资源工具只读限制扩展成全平台没有任何写能力。
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
- 活动 schema 从 baseline `100` 开始；后续 migration 单调递增，禁止重用旧版本号。
- 空库执行 `100` 后继续当前 forward catalog；精确 legacy `042` 必须先用仅含 `100` 的独立 artifact 完成 adoption，当前含 `101+` 的 checkout 不能直接完成 adoption；部分 legacy head 失败关闭。
- Compose 先执行 Docling Profile preflight，再迁移、受控文件存储初始化、初始管理员和 Agent bootstrap，最后应用 Runtime grants。
- API、Worker、Runtime 相关服务在迁移成功后启动并只读校验 schema head/checksum。
- 破坏性迁移先检查活动旧引用；已有库升级前必须完成可恢复备份。
- ONES 身份、Team、验证事实与用途绑定的加密 Credential 按当前生命周期治理，不得把旧 API Platform Credential 当作当前个人身份凭据。

操作手册见 [空库 Baseline 与管理员](../docs/operations/schema-baseline-bootstrap.md) 和 [Legacy 042 Adoption](../docs/operations/schema-baseline-upgrade.md)。

## ONES 身份

ONES 绑定由当前用户本人发起。服务端保存外部 User ID、显示名称、Team、默认 Team、验证时间，以及用途绑定加密的登录材料和当前 Token，用于同一主体的受控刷新；公开投影只返回凭据状态，不返回认证材料。管理员只能查看和停用，不能输入密码、代为验证或代为解绑。

## 配置

模板见仓库根目录 [.env.example](../.env.example)。数据库驱动由 `database-deps` 层安装，当前 `api-server` 及其派生 `tool-mcp` 镜像包含该层；API 负责资源技术验证，`tool-mcp` 负责受治理工具查询，Agent Worker 不执行数据库资源工具。

保留：

- Runtime Grant：Worker 与唯一 Python Agent Runtime 间的独立调用边界。
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

Python Runtime 工具链验收必须通过目标 MCP 产生 Tool Call、Runtime Event 与最终 Delivery 证据，不能只以容器健康或配置存在作为成功依据。知识能力的部署、配置和真实 ONES/模型验收边界见[知识扩展说明](../knowledge/README.md)和[知识治理手册](../docs/runbooks/knowledge-governance.md)。
