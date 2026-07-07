## Why

当前真实工具平台的 topology、secret 引用、访问授权仍主要来自 YAML/env，现有 PostgreSQL 配置表也偏扁平，难以支撑后续 Web 配置平台、审计变更和拖拽式诊断流程编排。现在需要把配置模型提升为 DDD 风格的数据库持久化能力，让 Web 端可以安全管理环境、基地、车间、资源绑定、权限授权和 Agent 诊断流程模板。

第一版不做“大而全后台”，而是先建立稳定的数据模型、配置 API 和从 DB 生成 Internal API Platform 运行快照的链路。

## What Changes

- 新增 `platform_config` 领域模块，管理 Environment / Base / Workshop / ResourceBinding / SecretReference / AccessGrant 等配置聚合。
- 新增 PostgreSQL 表保存平台拓扑、资源绑定、密钥引用、平台访问授权和配置审计。
- 新增 `workflow` 领域模块，保存后续 Web 拖拽编排使用的只读诊断 Agent 流程模板、节点、边和发布快照。
- 新增平台配置 REST API，供后续 Web 服务管理环境、基地、车间、资源绑定、访问授权和工作流模板。
- 新增 YAML import/upsert 能力，把当前 `internal_platform_topology.example.yaml` 迁移为 DB 配置，保留 YAML 作为本地 bootstrap/import 来源。
- Internal API Platform 新增 DB-backed topology loader：优先读取 PostgreSQL 配置快照，缺配置时保留 YAML 本地回退路径。
- 明确密钥处理策略：PostgreSQL 只保存 `secret_ref`，不保存真实密钥明文；后续可接 Vault/KMS。
- 明确存储策略：第一版 Web 配置、聊天记录、任务审计放在同一个 PostgreSQL 数据库中，用表前缀/领域仓储隔离；暂不物理分库。后续通过分区、归档或独立库迁移拆出高增长运行数据。

非目标：

- 不实现前端 Web 页面。
- 不把真实密钥加密落库。
- 不实现复杂 DAG 调度引擎。
- 不改变只读诊断 MVP 的安全边界，不新增任何数据库写入、Redis 删除、服务重启或代码修改能力。
- 不删除现有 `tool_definition`、`integration_connector`、`datasource_registry`、`permission_policy`，本期以新增配置模型和兼容读取为主。

## Capabilities

### New Capabilities

- `platform-config-registry`: 平台拓扑、资源绑定、密钥引用、访问授权、配置审计的 DDD 聚合与 PostgreSQL 表设计。
- `platform-config-api`: Web 配置平台使用的后端 REST API、YAML import/upsert、DB-backed topology snapshot 和配置校验行为。
- `agent-workflow-template-config`: 后续拖拽编排使用的 Agent 诊断流程模板、节点、边、发布快照和校验规则。

### Modified Capabilities

- `agent-audit-permission`: 扩展配置持久化要求，使平台访问授权和配置变更审计可由 Web 后台管理。
- `readonly-tool-platform`: 扩展工具平台配置来源要求，使 Internal API Platform 可从 PostgreSQL 配置快照构造 topology 和资源绑定。

## Impact

- 数据库：新增平台配置、工作流模板、配置审计相关迁移；保留现有运行时聊天、job、audit 表。
- 代码：新增 `backend/app/modules/platform_config/` 与 `backend/app/modules/workflow/`；扩展 `internal_api_platform` 配置加载器；扩展 repository 和 API router。
- API：新增 `/api/platform/*` 和 `/api/agent/workflows/*` 配置管理接口。
- 文档：补充 DDD 模块边界、表设计、同库/分库策略、YAML 迁移方式和 Web 拖拽编排数据结构说明。
- 测试：覆盖表迁移、YAML import、DB snapshot、secret_ref 不泄露、访问授权生成、workflow graph 校验、API CRUD 和 OpenSpec 校验。
