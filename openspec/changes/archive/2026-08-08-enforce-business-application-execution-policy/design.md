## Context

当前 Business Application Publication 已经冻结 Agent Publication、Trigger、Session Policy、Execution Policy 和 Delivery。钉钉 Stream 命中活动 route 后，API Server 会在入队前把应用、Publication、Deployment 和 route 来源保存到 `agent_job`，Worker 再按固定 Agent Publication 构建执行上下文。

现有 Agent Publication 的 `execution.max_turns` 和 `execution.timeout_seconds` 已经传给 Claude SDK，但 Business Application Publication 中同名的 `execution_policy` 没有进入 Job 或 Worker；`max_tool_calls` 也没有运行时计数器。`RuntimeReadinessEvaluator` 因此把整个 `execution_policy` 标为 `stored_only`，并且只要任意组件为 `partially_wired` 或 `stored_only` 就把整体状态降为 `partially_wired`。这也使非同步关键路径的 `retention_days` 清理缺口影响了“入口是否完整接管”的展示。

本项目必须保持只读诊断 Agent、安全失败投递、RabbitMQ 只传内部标识、已入队 Job 固定版本以及 API Server/Worker 共用 PostgreSQL 的边界。不新增全局 Feature Flag，也不在本变更中建设会话清理能力。

## Goals / Non-Goals

**Goals:**

- 将 Business Application Execution Policy 作为不可变 Job provenance 持久化。
- 计算并展示请求策略与有效策略，保证应用不能放宽 Agent 的轮次和超时限制。
- 在真实 Claude、Stub/fake 测试运行时和内部 MCP 工具桥强制执行三个字段。
- 使策略耗尽具备稳定分类、工具轨迹、审计和原钉钉会话失败投递。
- 将同步运行接管状态与后台数据治理缺口分开计算。
- 删除不具备 v1 策略快照的旧测试 Job 及关联运行数据，并要求所有新 Job 具有完整策略。

**Non-Goals:**

- 不实现 `retention_days` 清理、归档、脱敏、附件删除或相应队列。
- 不接入 Workflow 执行引擎、API Capability、Webhook Business Application Resolver 或新的 Agent 工具。
- 不改变现有 Agent 只读边界、权限模型、重试队列拓扑或 RabbitMQ 消息格式。
- 不增加用于临时绕过新策略的 Feature Flag。
- 不把执行策略扩展为租户配额、Token 预算、费用预算、并发配额或跨 Job 总预算。

## Decisions

### 1. 所有新Job使用版本化非空策略快照

新增 `agent_job.execution_policy_json TEXT NOT NULL`，不设置空对象默认值。采用 TEXT JSON 与现有 `session_policy_json`、`business_application_route_decision_json` 的序列化方式保持一致，但数据库和仓储都不允许迁移后创建空策略 Job。

建议的 v1 结构为：

```json
{
  "schema_version": 1,
  "requested": {
    "max_turns": 30,
    "timeout_seconds": 300,
    "max_tool_calls": 20
  },
  "effective": {
    "max_turns": 12,
    "timeout_seconds": 240,
    "max_tool_calls": 20
  },
  "sources": {
    "source_kind": "business_application",
    "business_application_publication_id": "business_app_publication_x",
    "business_application_config_hash": "…",
    "agent_publication_id": "agent_publication_x",
    "agent_config_hash": "…"
  }
}
```

命中应用后，由 Job 创建应用服务在已校验固定 Agent Publication 的同一流程中调用纯领域服务 `EffectiveExecutionPolicyResolver`，随后在创建 Job 的数据库事务中写入。非业务应用入口也必须在 Job 创建阶段从固定 Agent Publication 或当前运行时默认值生成 v1 快照，并通过 `source_kind` 说明来源。Worker、重试服务和运行记录只能读取该快照，不重新读取当前 Deployment，也不在消费阶段补默认值。

选择通用 `execution_policy_json` 而不是业务应用专用列，是因为调试入口、Webhook 和其他 Agent Job 同样必须在 Worker 执行前具备确定限制。选择 Job 快照而不是只保存 Publication ID，是为了避免 Worker 版本切换、应用回退或后续记录修改导致已排队任务的有效限制变化。

### 2. 公共字段取更严格值，工具调用上限由业务应用提供

有效值规则：

```text
effective.max_turns =
  min(application.max_turns, agent_publication.max_turns_or_runtime_default)

effective.timeout_seconds =
  min(application.timeout_seconds, agent_publication.timeout_or_runtime_default)

effective.max_tool_calls =
  application.max_tool_calls
```

Business Application 的三个字段仍使用现有校验范围。`max_tool_calls=0` 表示禁止工具调用。请求值大于 Agent 限制时不阻止历史或当前 Publication 激活，而是确定性收紧并在管理 API 显示 requested/effective 差异，避免升级后使已经活动的应用突然变成 `blocked`。

非业务应用新 Job 在创建时把 Agent Publication 值或运行时默认值转换为同一个 v1 快照。Worker 不再具有“策略缺失时读取 Agent Publication/全局默认”的 fallback；缺失、空对象、未知 schema 或不完整有效值都是不可重试完整性错误。

备选方案是让业务应用完全覆盖 Agent 限制；该方案会允许应用扩大 Agent Profile 的安全边界，因此不采用。另一方案是在请求值较宽时拒绝发布；该方案会使现有已发布配置无法继续激活，因此仍采用确定性收紧并展示 requested/effective 差异。

### 3. 三个限制按单次Agent execution attempt执行

`max_turns` 和 `timeout_seconds` 继续通过 `AgentExecutionContext` 进入 Claude client；新增 `max_tool_calls` 字段。每个 Worker attempt 都从固定 Job 快照初始化相同的限制：

- `max_turns` 传给 SDK `max_turns`；
- `timeout_seconds` 包裹本次 SDK session 的墙钟时间；
- `max_tool_calls` 由本次运行共享的 `ToolCallBudget` 在内部 MCP handler 进入 `ToolRegistry` 前检查并消费。

工具预算统计成功和失败的调用尝试，因为失败调用同样消耗下游资源。达到上限后的下一次调用不会进入 ToolRegistry，而是抛出专用 `ExecutionPolicyExceeded`，映射为 `execution_policy_max_tool_calls_exhausted` 非重试错误。已经收集的工具事件必须与最大轮次、timeout 失败路径一样交给 `AgentExecutor` 持久化。

本阶段按 attempt 而不是跨所有 retry 累计，是为了与现有 `max_turns`、墙钟 timeout 及 retry 模型一致。每次 retry 都使用相同上限；策略耗尽本身不触发普通 transient retry，只有现有明确允许的 timeout/transport 分类可以进入 retry。

备选方案是在数据库中做跨 attempt 原子工具预算；它可以限制整个 Job 的累计成本，但会引入调用预留、崩溃回收和 retry 剩余预算语义，超出本次接线范围。

### 4. 策略快照从入口传到Job，但MQ消息保持不变

`ChannelIngressService` 从已解析的 Business Application Publication 获取 `execution_policy`，连同现有应用 provenance 传给 `CreateAgentJobCommand`。`CreateAgentJobService` 在校验 Agent Publication 后计算有效值并持久化；其他 Job 创建入口也必须通过同一服务生成策略。RabbitMQ publisher 仍只发送 `job_id` 和 `correlation_id`，Worker 通过共享 PostgreSQL 读取策略。

这样避免把策略 JSON 复制到消息队列，也不会改变消息幂等或重投递契约。

### 5. 将retention治理从同步Session组件中拆开

运行时状态模型新增非阻塞影响维度，建议为 `RuntimeComponentStatus` 增加：

```text
impact: runtime | governance
```

并把现有 Session 状态拆为：

- `session_policy`：`conversation_mode`、`recent_message_limit`、`continuous_conversation_enabled`、`attachments_enabled`，全部接线后为 `wired`、`impact=runtime`；
- `retention_policy`：`retention_days=stored_only`、`impact=governance`。

整体 `runtime_status` 只聚合 `impact=runtime` 的组件；`impact=governance` 仍通过列表、详情、Publication、Deployment、effective 查询和管理 UI 返回，但不能把已完整执行的钉钉同步链路降为 `partially_wired`。

Workflow Publication 一旦被声明仍为 `stored_only/impact=runtime`，所以继续使整体状态为 `partially_wired`。不支持或损坏的 Trigger、Agent Publication、Delivery、Capability 继续保持现有 `blocked`/`unsupported` 行为。

选择显式 `impact` 而不是在聚合器中硬编码忽略 `retention_days`，是为了让未来备份、归档或数据驻留等治理能力使用同一可解释模型，并避免 UI 猜测哪些警告影响接管。

### 6. 管理端分别展示接管状态与治理提示

应用列表和详情继续使用服务端统一的 `runtime_status`，文案调整为：

```text
运行接管：已接管 / 部分接管 / 未接管 / 已阻塞
治理提示：会话保留策略尚未执行
```

组件详情显示 Execution Policy 的每个字段为 `wired`，运行记录显示 requested/effective 值与来源。UI 不根据字段自行推导状态。

### 7. 策略耗尽复用现有失败与投递链

新增稳定错误码至少包括：

- `execution_policy_max_tool_calls_exhausted`
- 复用现有 `max_turns_exhausted`
- 复用或规范化现有 `runtime_timeout`

工具调用耗尽为非重试策略失败；最大轮次保持非普通 transient；timeout 继续遵守现有 timeout retry 决策。所有路径保留安全工具事件并进入现有 Job 状态、审计、dead-letter/retry 与原会话失败 Delivery，不新增旁路通知。

### 8. 采用维护窗口执行破坏性运行数据重置

不为迁移前 Job 猜测或回填策略。迁移与维护脚本按以下边界删除测试运行数据：

```text
删除：
  旧 agent_session / agent_job
  agent_message / agent_step / agent_tool_call / agent_artifact
  delivery_attempt / delivery_chunk
  message_attachment / attachment_content 及对应 MinIO 对象
  与旧 Job 关联的 webhook_event / webhook_outbox
  与旧 Job 关联的 audit_event

保留：
  app_user / user_external_identity / RBAC
  agent_definition / agent_revision / agent_publication
  business_application / revision / publication / deployment / route
  integration_connector / credential / secret / platform config
  webhook trigger definition / revision / publication
```

schema migration 先以可重放方式增加可空 `execution_policy_json` 和运行计数字段。由于本项目启动时会重复执行 migration 文件，破坏性数据清理不得直接写入常规 migration；在 API Server、Ingress 和 Worker 停止接收/执行任务的维护窗口内，由显式确认的一次性维护命令先清理 MinIO 对象和旧运行数据，确认 `agent_job` 为空后再把列改为 `NOT NULL` 且不设置默认值。附件对象不能只删数据库元数据；一次性维护命令必须先收集并删除对应 MinIO object key，失败则中止数据库清理并报告。

选择删除完整旧运行链而不是只删 `agent_job`，是为了满足外键顺序、避免孤儿消息/附件以及防止旧连续会话内容进入新策略 Job。控制面配置不参与清理，迁移后可直接继续使用现有默认诊断应用。

## Risks / Trade-offs

- [破坏性迁移期间仍有入口创建Job] → 先停止 API Server、Ingress、Webhook/Attachment Worker 和 Agent Worker，在维护窗口内完成对象与数据库清理，再部署同一提交的全部服务。
- [API Server 已写入新策略但旧 Worker 尚不识别] → 新列无默认值且不兼容旧进程，禁止混跑；迁移后一次性部署同版本 API Server 和 Worker。
- [业务应用请求值与有效值不同造成困惑] → 管理 API 和运行记录同时展示 requested/effective 及 Agent Publication 来源，UI 不只显示请求值。
- [SDK 对 MCP handler 异常的包装方式导致策略错误被误分类] → 使用 fake SDK 覆盖异常传播，并在 Claude client 边界显式识别专用异常与错误码。
- [失败工具调用反复消耗预算] → 所有进入 MCP handler 的尝试都计数，超过上限时在 ToolRegistry 前停止。
- [删除数据库附件元数据后MinIO遗留对象] → 维护命令先删除已枚举对象并验证结果，再提交数据库运行数据清理。
- [清理范围误删控制面配置] → 清理使用明确表清单和删除前后计数，不使用 `docker compose down -v` 或数据库全库重建。
- [迁移后出现空策略Job] → 数据库 `NOT NULL` 无默认值、仓储必填参数和所有 Job 创建入口契约测试共同失败关闭。
- [整体显示wired但retention未执行被理解为全部治理完成] → 引入 `impact=governance` 和独立治理提示，字段继续显示 `stored_only`，禁止使用“全部策略已执行”文案。
- [按attempt计数允许一次transport retry再次使用工具预算] → 保留现有 retry 语义并在运行记录按 attempt 展示；跨 retry 总预算留给后续独立能力。

## Migration Plan

1. 在维护开始前输出待删除 Job、Session、附件对象、消息、工具调用、投递、Webhook 事件和审计计数，并确认控制面表计数基线。
2. 停止所有可能创建或消费 Job 的 API Server、钉钉/Webhook Ingress、Agent/Attachment/Webhook Worker，保留 PostgreSQL、MinIO 和 RabbitMQ 基础设施。
3. 一次性维护命令删除旧附件/产物对象；任何对象清理失败都中止后续数据库迁移。
4. 可重放 schema migration 增加临时可空策略列；一次性维护命令按外键安全顺序删除旧运行数据和孤立 Session，验证没有旧 Job 后将列设为 `NOT NULL` 且无默认值。
5. 以同一提交部署会强制写/读 v1 快照的 API Server、Ingress、Worker 和管理 Web，不允许新旧版本混跑。
6. 接通策略解析、Job 固定和三字段执行后，更新 RuntimeReadiness 与管理 API/Web。
7. 使用保留的默认诊断应用和身份/Connector 配置创建全新 Job，验证 v1 provenance、有效限制、运行状态和投递。
8. 本迁移不承诺恢复已删除测试运行数据。代码回滚需要同时提供能够创建必填策略的前向修复版本，不能直接回退到不写新列的旧 API。

## Open Questions

无。本变更明确采用破坏性测试运行数据重置、所有新 Job 强制 v1 快照、单 attempt 执行预算、requested/effective 双值展示、非阻塞 retention 治理状态，并保持现有 timeout retry 语义。
