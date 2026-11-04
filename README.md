# 企业级受治理 Agent 平台

这是一个面向企业内部诊断、查询、文件处理和受确认外部操作的 Agent 平台。平台保留身份、RBAC、应用发布、资源、Secret、审计和 Job 历史治理；工具协议统一为标准 MCP。DB/Redis/Loki保持只读，ONES与钉钉的代码固定mutation通过逐次确认和独立worker执行，不提供任意URL、脚本或Shell。

当前规范从 [10个领域主规格导航](openspec/specs/README.md) 进入；旧change和archive仅作显式历史追溯。规范与代码实现、真实环境验收分别判断。

```text
钉钉 / Webhook / Debug API
  -> FastAPI Control Plane
  -> PostgreSQL + RabbitMQ
  -> file-worker -> file-service -> MinIO
  -> agent-worker
  -> Python Runtime
  -> tool-mcp、ones-mcp、dingtalk-mcp、knowledge-mcp 或 File MCP 接口
  -> 已发布工具资源 / 当前用户业务身份 / 受治理文件版本
  -> 外部mutation: Action Intent -> 用户确认 -> external-action-worker
  -> Job / Tool Call / Delivery / Audit
```

旧 API Capability、Handler、API Connection、Application Resource Mapping 和 Internal API Platform 已永久退役。`tool-mcp` 使用代码 Manifest 暴露固定只读工具，Agent Publication 冻结 tool identifier 与 schema hash，Application Publication 只能选择其显式子集。

ONES 本人身份绑定属于统一身份体系，独立于旧 API Platform。绑定保存 ONES User ID、Team、默认 Team，以及用平台主密钥加密的登录材料和当前 Token；所有公开投影只返回凭据状态。Agent 只能通过短期 Ed25519 Principal JWT 调用独立 `ones-mcp`，JWT 不携带 ONES 身份或凭据。

## 当前边界

- 唯一 Agent Runtime：`python-v1`；数据库所有 runtime kind 列只允许该值。
- 当前Runtime协议为1.5，代码仍支持1.4；Job、重试与Publication保持各自冻结事实。
- 标准MCP：`tool-mcp`复核私有Job上下文；`ones-mcp`与`dingtalk-mcp`验证各自audience的短期Principal JWT，按固定目录提供查询和受确认mutation。完整工具合同见相关canonical领域与代码Manifest。
- 任务文件：File Service内置File MCP与内部流式API，是唯一业务对象存储入口；TXT/Markdown可读写，LOG只读。PDF、DOCX、PPTX、XLSX、PNG、JPEG、WebP使用固定Docling/OCR Profile派生Markdown，原件不进入Job Sandbox。
- 文档处理：两个Processing Worker各单并发，一个Docling容器含两个执行器；全局两个槽位由PostgreSQL经File Service协调。
- 只读资源工具：资源目录、数据库 schema/query、Redis、Loki 查询与标签诊断。
- 知识能力：受限离线导入、本地 BGE-M3 向量与混合召回、BGE 重排、Knowledge MCP，以及文档级增量采集和日期补采。全部知识服务默认纳入主 Compose，通过 Web 和 `knowledge.sh` 共用运维队列。检索只返回本人 ONES 可读引用，最新正文通过 ONES 详情工具读取；普通同步不重新发布知识资源。
- 工具资源：Draft、技术验证、Publish、Disable、Archive；运行时只解析已发布 Revision。
- 工具目标由 Agent 根据用户输入和发布 Skill 在每次 Tool Call 中显式提供，服务端实时复核角色、应用、数据范围和唯一资源。
- Runtime Grant、Model Probe Token 和配置 Master Key 是其它边界，不属于已退役的 MCP/平台签名密钥。

## 快速开始

已有数据库升级前先阅读 [Schema Baseline 升级手册](docs/operations/schema-baseline-upgrade.md)。`migrator` 是唯一 schema 写入入口；失败时必须修复迁移，不要绕过 `service_completed_successfully`。

```bash
test -e .env || cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
make check
docker compose up --build
```

Windows Docker Desktop 部署同样使用上述命令。仓库通过 `.gitattributes` 强制所有
Shell 脚本使用 LF，避免 Linux 镜像把 CRLF shebang 解析为 `bash\r`。Windows 文件共享
无法稳定表达 Unix Secret 权限时，后端镜像只把白名单文件复制到容器自己的
`${TMPDIR:-/tmp}/ea-secrets`，收紧为目录 `0700`、文件 `0400` 后再启动应用；原始宿主机
Secret 不会被修改。具体安全边界见[平台固定 Master Key](docs/operations/platform-master-key.md)。

可部署的 ONES Mock 已删除。`ones_mock/ones` 保留现场接口文档；测试替身位于
`backend/tests/support`，不启动网络服务。`ones-mcp` 的启动方式和连接配置保持不变。
`ones_mock/docker-compose.ones-mock.yml` 保留原数据库/Redis 测试服务及数据卷，
不再包含 `ones-mock` 服务。真实 ONES 验收需要单独安排。

查看服务状态：

```bash
docker compose ps
docker compose logs migrator tool-mcp ones-mcp file-service file-worker agent-worker
```

Compose 的核心执行服务为：

- `api-server`、`admin-web`
- `postgres`、`rabbitmq`
- `agent-worker`（默认两个副本）
- `python-agent-runtime-a`、`python-agent-runtime-b`（固定节点，每个节点一个执行槽）
- `tool-mcp`、`ones-mcp`、`dingtalk-mcp`、`external-action-worker`（无可部署ONES Mock）
- `file-service` 和替代旧附件消费者的 `file-worker`；无独立 `file-mcp`
- `file-processing-worker`、`file-processing-worker-2` 和内部 `docling-serve`
- 钉钉、Webhook 和独立投递 Worker

## 配置与 Secret

`.env` 只放 bootstrap 和部署连接参数，模板见 [.env.example](.env.example)。Secret 明文不写入 Git；平台 Secret 通过 `secret://platform/<code>` 引用。工具资源、模型连接和渠道配置在管理端分别维护。

常用保护性配置：

- `DATABASE_DSN`
- `APP_CONFIG_MASTER_KEY_FILE`
- `RUNTIME_GRANT_*`
- `PRINCIPAL_JWT_PRIVATE_KEY_FILE`、`PRINCIPAL_JWKS_FILE`
- `MODEL_PROBE_AUTH_TOKEN_FILE`
- `PYTHON_AGENT_RUNTIME_NODES` 固定节点映射及 URL 主机白名单

仓库不再接受 `INTERNAL_API_*`、`RUNTIME_TOOL_MCP_*` 或旧 HS256 MCP signing key 配置。

Runtime 池的升级、排空和故障处理见 [Runtime 多副本池运维](docs/operations/runtime-replica-pool.md)。

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
- [受治理任务文件工作区](docs/architecture/task-file-workspaces.md)
- [数据库备份与恢复](docs/operations/compose-postgres18-rabbitmq4-upgrade.md)

## 知识库部署与运维

主程序和全部知识服务统一使用根 `docker-compose.yml`。完成配置、Secret 和外部持久卷准备后，执行 `docker compose up -d --build` 即可启动；首次安装及旧项目迁移见[知识库网页运维手册](knowledge/OPERATIONS.md)，服务用途见[知识库部署说明](knowledge/README.md)。

控制器安装后，在仓库根目录操作：

```sh
./knowledge.sh build
./knowledge.sh up
./knowledge.sh status
./knowledge.sh logs
./knowledge.sh sync --binding-code your-plan-code
./knowledge.sh backfill 2026-10-10 2026-10-29 --binding-code your-plan-code
./knowledge.sh stop
```

构建、启停、同步和补采返回持久任务 ID，进度可在“工具资源 → 知识库”查看。构建成功后需执行 `up` 应用版本；`stop` 保留数据、模型、采集断点和主程序侧执行器。同步命令要求计划已配置并启用；首次启用立即调度全量，之后每小时扫描最近七个北京时间创建日，更早日期使用显式补采。

日常同步仅处理新增或变化文档，重启复用已完成步骤，不全库重新分块、编码或发布。旧索引接入增量模式仍需按[同步手册](docs/runbooks/knowledge-ones-hourly-sync.md)执行一次性转换；模型、分块或运行架构变化另行维护。

平台与知识服务统一使用根 `docker-compose.yml`，默认包括知识模型、Qdrant、MCP、同步和运维执行器。首次部署和旧项目迁移见[知识库运维手册](knowledge/OPERATIONS.md)。

知识检索 v2 改变了工具 Schema；升级镜像后还需按正式流程更新 Agent、应用发布并激活，以免新消息被 `mcp_tool_schema_drift` 拒绝。知识内容同步无需这项重发布。实现与主规格的预算差异见[知识治理手册](docs/runbooks/knowledge-governance.md#实现与主规格差异)。
