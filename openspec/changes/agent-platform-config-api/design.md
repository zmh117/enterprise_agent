## Context

当前系统已经具备 Agent job、RabbitMQ worker、Claude/DeepSeek runtime、Internal API Platform、本地 Loki 工具链和基础审计链路。配置侧仍然有两个问题：

1. 真实工具平台 topology 主要来自 YAML/env，适合本地启动，不适合 Web 后台持续管理。
2. 已有 `tool_definition`、`integration_connector`、`datasource_registry`、`permission_policy` 偏扁平，无法完整表达环境、基地、车间、资源绑定、密钥引用、访问授权和拖拽式诊断流程模板。

这个 change 的核心是把配置从“启动配置文件”提升为“平台配置领域模型”。第一版仍保持只读诊断 Agent 边界，不引入自动改库、删 Redis、重启服务、改代码或复杂 DAG 执行器。

关于数据库拆分，第一版不建议把 Web 平台配置和聊天/job/audit 物理分成多个 PostgreSQL database。理由是当前 MVP 更需要端到端链路清晰、事务和审计简单、部署复杂度低。更稳健的做法是同一个 PostgreSQL database 内按领域表前缀和 repository 边界隔离。聊天、消息、工具调用、审计属于高增长运行数据，后续再用分区、归档、冷热表或独立库迁移拆出。

## Goals / Non-Goals

**Goals:**

- 新增 `platform_config` DDD 模块，持久化环境、基地、车间、资源绑定、密钥引用、访问授权和配置审计。
- 新增 `workflow` DDD 模块，持久化后续 Web 拖拽编排所需的只读诊断 Agent 流程模板、节点、边和发布快照。
- 提供 Web 配置平台可调用的 REST API，覆盖查询、新增、修改、启停、YAML import/upsert 和 topology snapshot。
- Internal API Platform 优先从 PostgreSQL 读取运行快照，DB 没有配置时保留 YAML 本地 fallback。
- PostgreSQL 只保存 `secret_ref`，不保存真实 token、password、api key 或连接密码。
- 表结构预留版本、状态、扩展 JSON、审计和发布快照，避免后续 Web 化和拖拽编排时大改模型。

**Non-Goals:**

- 不实现前端 Web 页面。
- 不把真实密钥明文或加密密钥值写入 PostgreSQL。
- 不实现复杂 DAG 调度引擎，第一版 workflow 只负责模板配置和校验。
- 不改变只读诊断边界，不新增写库、删 Redis、服务重启、发版或代码修改能力。
- 不删除现有扁平配置表，本期以新增领域模型和兼容读取为主。
- 不在第一版物理分库。

## Decisions

### Decision 1: 第一版同库逻辑隔离，不做物理分库

配置、聊天、任务、工具调用和审计先放在同一个 PostgreSQL database。通过表前缀、模块 repository、迁移文件和应用服务边界隔离：

- 配置域表：`platform_*`
- 拖拽编排域表：`agent_workflow_*`
- 运行域表：继续使用 `agent_*`、`delivery_*`、`audit_*`

替代方案是现在就拆成 config DB、runtime DB、audit DB。它的缺点是本地 Docker Compose、迁移、事务、测试和故障定位都会变复杂，而当前数据量和团队阶段还不需要这个复杂度。后续如聊天和审计增长明显，可以先对 `agent_message`、`agent_tool_call`、审计表做按时间分区和归档，再决定是否迁移到独立库。

### Decision 2: `platform_config` 独立成配置领域模块

不把平台配置塞进 `agent`、`job` 或 `internal_api_platform`。DDD 边界如下：

- `platform_config/domain`: Environment、Base、Workshop、ResourceBinding、SecretReference、AccessGrant、ConfigAudit。
- `platform_config/application`: 配置 CRUD、YAML importer、配置校验、topology snapshot builder、配置审计服务。
- `platform_config/infrastructure`: SQL repository、secret ref resolver、YAML reader。
- `platform_config/api`: `/api/platform/*` 管理接口。

`internal_api_platform` 只消费配置快照，不拥有配置生命周期。这样后续 Web 后台、CLI import、seed、worker 都能复用同一个配置领域。

### Decision 3: 核心拓扑关系结构化，连接细节使用受控 JSON 扩展

表设计建议：

| 表 | 职责 | 关键字段 |
| --- | --- | --- |
| `platform_environment` | 环境，如 `sanjiu`、`mmk` | `id`, `code`, `display_name`, `status`, `aliases_json`, `metadata_json`, `revision`, `created_at`, `updated_at` |
| `platform_base` | 基地，归属环境 | `id`, `environment_id`, `code`, `display_name`, `engine`, `status`, `aliases_json`, `metadata_json`, `revision`, `created_at`, `updated_at` |
| `platform_workshop` | 车间，归属基地 | `id`, `base_id`, `code`, `display_name`, `table_prefix`, `redis_key_prefix`, `loki_labels_json`, `status`, `aliases_json`, `metadata_json`, `revision`, `created_at`, `updated_at` |
| `platform_secret_reference` | 密钥引用，不存密钥值 | `id`, `code`, `provider`, `ref`, `purpose`, `status`, `metadata_json`, `revision`, `created_at`, `updated_at` |
| `platform_resource_binding` | DB/Redis/Loki/ER/业务图资源绑定 | `id`, `code`, `scope_type`, `environment_id`, `base_id`, `workshop_id`, `resource_kind`, `connector_id`, `engine`, `config_json`, `secret_refs_json`, `status`, `revision`, `created_at`, `updated_at` |
| `platform_access_grant` | 用户/组/角色/服务账号访问授权 | `id`, `subject_type`, `subject_code`, `effect`, `environment_id`, `base_id`, `workshop_id`, `tool_scope_json`, `resource_scope_json`, `condition_json`, `priority`, `status`, `revision`, `created_at`, `updated_at` |
| `platform_config_audit` | 配置变更审计 | `id`, `entity_type`, `entity_id`, `action`, `actor_id`, `before_json`, `after_json`, `created_at` |

结构化字段表达稳定关系，`*_json` 只保存扩展配置，例如 Loki tenant、默认时间窗、查询 limit、连接池参数、UI 元数据。应用层必须校验 JSON schema，禁止把 `password`、`token`、`secret`、`api_key` 等真实密钥值写入 `config_json`。

### Decision 4: SecretReference 只保存引用，真实密钥由运行时解析

`platform_secret_reference.ref` 保存 `env:NAME`、`vault:path/key`、`kms:alias/key` 这类引用。运行时由 infrastructure 层解析，domain 和 API 返回值只暴露引用元数据。这样 Web 配置平台可以管理“使用哪个密钥”，但不会成为密钥仓库。

### Decision 5: Workflow 模板按图模型持久化，发布快照不可变

拖拽编排第一版聚焦“只读诊断流程模板”，不直接承担复杂执行器职责。表设计建议：

| 表 | 职责 | 关键字段 |
| --- | --- | --- |
| `agent_workflow_template` | 流程模板主表 | `id`, `code`, `name`, `description`, `project_code`, `status`, `version`, `entry_node_key`, `graph_schema_version`, `graph_json`, `settings_json`, `created_by`, `created_at`, `updated_at` |
| `agent_workflow_node` | 拖拽节点 | `id`, `template_id`, `node_key`, `node_type`, `title`, `position_json`, `config_json`, `ui_json`, `created_at`, `updated_at` |
| `agent_workflow_edge` | 节点连线 | `id`, `template_id`, `edge_key`, `source_node_key`, `target_node_key`, `source_port`, `target_port`, `condition_json`, `created_at`, `updated_at` |
| `agent_workflow_publication` | 已发布快照 | `id`, `template_id`, `version`, `graph_snapshot_json`, `config_hash`, `published_by`, `published_at` |

`agent_workflow_template` 保存当前可编辑草稿，`agent_workflow_publication` 保存不可变发布快照。后续运行时只读取发布快照，避免 Web 编辑中的半成品影响生产诊断。

节点类型第一版建议限制为：

- `trigger`: 用户问题入口。
- `context_search`: ER/业务图上下文检索。
- `tool_call`: 只读内部工具调用。
- `agent_prompt`: Claude 诊断提示词片段。
- `condition`: 条件分支。
- `report`: 诊断报告生成。
- `callback`: 钉钉或其他渠道回复。

### Decision 6: DB snapshot 优先，YAML 只作为 import/bootstrap/fallback

Internal API Platform 的读取顺序：

1. 从 PostgreSQL 构造 topology snapshot。
2. 如果 DB 没有任何启用的 topology，且当前环境允许本地 fallback，则读取 YAML。
3. 如果 DB 配置存在但不完整，启动或 health check 必须暴露配置错误，而不是静默回退。

这样可以平滑迁移：先导入 YAML 到 DB，再切换运行链路读取 DB。

## Risks / Trade-offs

- [Risk] 同库保存配置和运行数据，后续运行数据增长会影响配置查询。→ Mitigation: 表前缀和 repository 边界先隔离，运行数据后续按时间分区、归档，再按需独立库迁移。
- [Risk] `config_json` 过度泛化会变成不可治理的大杂烩。→ Mitigation: 稳定关系必须结构化；JSON 字段必须有应用层 schema 校验和测试。
- [Risk] Web 拖拽图模型如果直接等同执行引擎，后续会过早复杂化。→ Mitigation: 第一版只做模板、校验和发布快照；执行器能力另开 change。
- [Risk] 密钥引用配置错误导致工具链运行失败。→ Mitigation: 增加 secret ref 解析健康检查和 topology snapshot 校验，错误返回到调试 API。
- [Risk] DB 和 YAML 双来源可能产生混淆。→ Mitigation: DB 有配置时优先 DB；YAML 仅 import/bootstrap/local fallback，并在状态接口显示当前来源。

## Migration Plan

1. 新增 `platform_*` 和 `agent_workflow_*` 表，不改现有运行表。
2. 增加 seed/import，把 `backend/config/internal_platform_topology.example.yaml` upsert 到新表。
3. 实现 `platform_config` repository、application service 和 snapshot builder。
4. Internal API Platform 增加 DB-backed topology loader，保持 YAML local fallback。
5. 增加 `/api/platform/*` 和 `/api/agent/workflows/*` API。
6. 增加配置审计和 secret 泄露校验测试。
7. 文档明确同库策略、表设计、YAML 迁移方式和后续分库条件。

Rollback 策略：新增表和 API 可保持旁路；如果 DB-backed loader 出现问题，通过配置开关切回 YAML loader。新表不影响现有 job/worker 执行链路。

## Open Questions

- Web 平台用户体系是否直接复用 DingTalk 用户/部门，还是引入独立后台用户和角色。本 change 先用 `subject_type` + `subject_code` 支持两种形态。
- Secret provider 第一版是否只支持 `env:`，还是同步预留 `vault:`。本 change 预留 provider 字段，第一版实现可只解析 `env:`。
- Workflow 模板何时接入真实 Agent 执行链路。本 change 只持久化和发布模板，执行器接入另开 change。
