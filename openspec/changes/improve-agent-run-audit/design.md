## Context

当前运行中心已经能从 `agent_job`、`agent_step`、`agent_tool_call`、`mcp_operation_audit`、`audit_event`、`delivery_attempt` 和 `agent_runtime_event` 读取 Job 生命周期、工具、MCP 与投递证据。两套 Claude Agent SDK Runtime 也已经通过版本化事件协议向 Worker 返回 `execution_started`、工具事件、assistant 安全文本和唯一终态，但 Worker 的 `AgentRunResult` 尚未完整承接 ResultMessage 的耗时、Token、按模型 usage 和估算成本，管理页面也没有模型轮次投影。

本变更跨 TypeScript/Python Runtime、Worker、PostgreSQL、管理 API 和 Web 页面。关键约束如下：

- 不引入 OpenTelemetry、Collector、Tempo、audit-ingestor、Trace 上下文传播或新容器；数据只能来自当前进程内 Claude Agent SDK 消息流和已有执行链。
- `agent_job` 已承担 Job 身份、冻结配置、路由、重试与生命周期事实，不再叠加可重算统计字段。
- Claude Agent SDK 的 ResultMessage 能提供 query 级 `duration_ms`、`duration_api_ms`、`modelUsage`、usage 和 `total_cost_usd`；SDK 消息流不能保证提供 Provider HTTP 请求的精确逐次 Span。
- 现有 Runtime 协议、恢复账本和 `invocation_id + request_digest` 是跨进程幂等边界；当前 checkout 另有 active change 正在引入 Runtime protocol v1.1 和统一 MCP 审计，实施时必须在其实际落地状态上选择下一个可用 minor version。
- 新数据必须继续遵守当前授权、租户隔离、脱敏和 private reasoning 禁止持久化边界。

## Goals / Non-Goals

**Goals:**

- 在现有系统内得到 Job 级总耗时、API 总耗时、四类 Token、按模型 usage、估算成本、SDK 可见模型轮次、API retry 和稳定失败位置。
- 为优化页面提供可筛选列表和可追溯详情，同时诚实表达数据精度和缺失状态。
- 保持 Job 生命周期、Runtime 事件、模型轮次、工具审计、MCP 审计和 Delivery 各自只有一个明确事实源。
- 使重复 MQ 投递、Job retry、Runtime 终态重放和 Worker 崩溃恢复不会重复累计。
- 让旧 Runtime 与新版 Runtime 能在受控发布窗口内共存和回滚。

**Non-Goals:**

- 不建设通用遥测、分布式 Trace、指标告警或跨服务调用链平台。
- 不声称得到 Claude Provider HTTP 层的精确逐请求耗时、TTFT、网络分段或服务端排队时间。
- 不从总成本按 Token 比例分摊逐轮成本，也不重新计算或纠正 SDK 返回的价格。
- 不复制 `agent_tool_call`、`mcp_operation_audit`、`audit_event` 或 `delivery_attempt` 已有业务证据。
- 不保存 Prompt、完整回答、raw SDK message、private thinking 或原始 Provider/MCP payload。
- 不承诺采集 SDK 消息流没有稳定暴露的 Hook 完成或 Skill 激活事件；现有应用配置和受治理 Skill 事实仍沿用其当前事实源。

## Decisions

### 1. 直接扩展现有 Runtime 事件链，不引入遥测旁路

TypeScript 和 Python Runtime 在消费 Claude Agent SDK 消息时增加安全归一化器，并通过现有 stdout 版本化协议发送：

- `runtime_initialized`：Runtime、SDK/CLI 安全版本、选择模型和部署固定 MCP Server 的有界连接状态；
- `model_call`：SDK 可见的模型响应轮次；
- `api_retry`：attempt、max retries、delay、稳定错误分类和可选安全 HTTP status；
- `terminal`：现有终态字段加 ResultMessage 汇总、统计可用性和稳定错误分类。

Worker 继续先把合同事件幂等写入 `agent_runtime_event`，再从唯一终态和模型轮次投影业务查询表。`agent_runtime_event` 是恢复证据，不对页面承担无限期 raw event 查询职责。

选择该方案是因为数据源和 Job 身份已经在 Runtime/Worker 边界内，部署、授权和恢复模型也已经存在。备选的 OpenTelemetry 分流会新增异步投递、关联、数据脱敏和双写一致性问题，超出本次轻量运行审计目标。

### 2. 使用一张 1:1 汇总表和一张 1:N 模型轮次表

新增 `agent_job_execution_summary`，建议字段为：

- `job_id` 主键并外键关联 `agent_job(id)`；
- `accounting_status`：`COMPLETE | PARTIAL | UNAVAILABLE`；
- `observed_model_turn_count`、`api_retry_count`、`runtime_invocation_count`；
- `total_duration_ms`、`total_api_duration_ms`；
- `input_tokens`、`output_tokens`、`cache_creation_input_tokens`、`cache_read_input_tokens`；
- `model_usage_json`：仅允许固定 schema 的按模型数值汇总，不接受 raw SDK JSON；
- `estimated_cost_usd`：使用足够精度的定点数值，API 必须带 `estimated` 语义；
- `execution_status`、`execution_failure_stage`、`failure_code`、`failure_summary`、`retry_exhausted`；
- `source_protocol_version`、`created_at`、`updated_at`。

新增 `agent_model_call`，建议字段为：

- `id`、`job_id`、`invocation_id`、`request_digest`、`runtime_sequence`；
- 有界的 `provider_request_id` / `provider_message_id`、`model_id`；
- `status`、`started_at`、`completed_at`、`duration_ms`、`duration_source`；
- 四类可空 Token、`stop_reason`、`error_code`、`error_summary`；
- `created_at`、`updated_at`。

核心约束为 `UNIQUE(job_id, invocation_id, runtime_sequence)`；若当前协议为一个模型轮次提供更稳定的 Runtime call ID，可再增加同等范围的唯一约束。所有计数和 Token 使用 64 位非负整数约束；未知值为 `NULL` 而不是 0；错误摘要、模型与 Provider 标识均设定长度上限。两表随 Job 的既有保留策略清理，不建立独立且更短的清理窗口。

选择独立表而非继续给 `agent_job` 加列，是为了保持生命周期主账稳定，并允许模型明细独立分页和演进。选择两张表而非通用 JSON event 表，是为了让筛选、排序、约束、索引和统计语义可验证。无需新增第三张 attempt 汇总表：每个 invocation 的唯一 terminal 已存在于 Runtime 事件恢复账本，Job 汇总可从这些证据重算。

### 3. 逐轮只承诺 SDK 观测，query 汇总以 ResultMessage 为准

模型轮次在 Runtime 能识别安全起点时，使用本地单调时钟计算从 SDK 请求边界到 assistant message 完成边界的耗时，并另存墙钟时间用于展示。若缺少可靠起点，`duration_ms=NULL` 且 `duration_source=UNAVAILABLE`。任何页面、导出和 API 字段说明都使用“SDK 观测耗时”，不使用“Provider 请求耗时”或“网络耗时”。

SDK ResultMessage 是 query/invocation 级核算事实：

- 完整的 `modelUsage` 可用时，按其固定白名单字段归一化，并标记 `COMPLETE`；
- 只有主循环 `usage` 可用时可以保存，但标记 `PARTIAL`，不得暗示覆盖子 Agent、sidechain 或其他 SDK 内部模型调用；
- ResultMessage 不含字段时保存 `NULL`，不得从逐轮事件补成所谓精确总量；
- `total_cost_usd` 原样作为 SDK 估算值保存，不做逐轮分摊；
- `duration_api_ms` 是 query 级 API 合计，不分配给任一轮次。

这一决策牺牲了逐次 HTTP 精度，换取无需额外基础设施且与 SDK 官方返回事实一致的统计。若未来业务必须获得 TTFT 或 Provider HTTP Span，应另立 change 评估遥测链，而不是静默改变本字段语义。

### 4. Job 汇总按唯一 invocation 终态重算，禁止增量盲加

Runtime invocation 使用现有 `invocation_id + request_digest` 识别一次 SDK query，事件使用单调 sequence 去重，每个 invocation 只接受一个终态。Worker 在同一数据库事务中：

1. 幂等保存事件或模型轮次；
2. 校验终态身份、协议版本和 schema；
3. 从该 Job 所有唯一、合同有效的 terminal 重新计算 `agent_job_execution_summary`；
4. 提交后再执行现有消息确认流程。

Job retry 产生新的 invocation，已经实际发生且有可靠终态的使用量计入 Job 总成本；同一 invocation 的恢复或 MQ 重放不会重复计入。若进程崩溃只留下部分事件，没有可靠 ResultMessage，则保留可见轮次证据并把汇总标记为 `PARTIAL`，不推测缺失使用量。旧协议 Job 可展示已有工具和生命周期证据，但新增统计为 `UNAVAILABLE`。

选择重算而非 `total = total + delta`，是为了使恢复、重复消费和人工重放天然幂等。Job 规模下 invocation 数量有严格 retry 上限，重算成本可控。

### 5. 失败位置使用根因阶段加 retry 结果，Delivery 在查询层合并

执行汇总的 `execution_failure_stage` 仅允许：

- `RUNTIME_START`
- `RUNTIME_PROTOCOL`
- `MCP_CONNECTION`
- `MODEL_API`
- `TOOL_PERMISSION`
- `TOOL_EXECUTION`
- `UNKNOWN`

映射只依据 typed SDK message、稳定内部异常类型、Runtime 合同错误、工具审计状态或 MCP 审计状态，不解析自由文本猜测。`retry_exhausted` 单独表达 Job 是否耗尽重试，避免把 `MODEL_API` 等可行动根因覆盖成笼统的“重试失败”。错误摘要通过现有脱敏器处理并限制长度。

Delivery 失败不写入 `agent_job_execution_summary`。管理查询同时读取 `agent_job` 和 `delivery_attempt`，在投影视图中给出 `display_failure_stage=DELIVERY`，同时保留 Agent 执行成功/失败和 Delivery 状态。这样延续 canonical spec 已接受的执行与投递分离规则。

### 6. 页面查询复用现有 Job evidence 授权并采用列表摘要、详情分页

扩展现有运行中心列表和 Job evidence/detail API，而不是创建未治理的通用事件查询接口：

- 列表只联接 1:1 汇总和已有状态，支持按时间、用户安全标识、Agent、执行状态、Delivery 状态、失败阶段和模型筛选；
- 详情返回汇总、分页模型轮次、已有工具调用/MCP 关联和 Delivery 证据；
- 用户、租户和应用过滤在 repository 查询前由现有授权服务确定，客户端参数不能扩大范围；
- 模型轮次默认不携带任何输入/输出正文；错误只返回 code 和有界安全摘要；
- 对列表排序建立 `job_id`、`completed_at`、`execution_failure_stage`、`model_id` 等必要索引，避免扫描通用 Runtime event JSON。

选择扩展已有 API 是为了复用当前登录、应用运维权限和平台管理员授权。直接暴露 `agent_runtime_event` 会把协议内部字段、保留策略和安全边界泄漏给页面，因此不采用。

### 7. Runtime 协议和数据库迁移均采用 expand-first

本 change 的 Runtime 事件使用实施时“下一个可用 minor version”。按当前 active change 的 documented intent，它预计是 v1.2；apply 阶段必须核对当前 checkout 的协议 ledger，不能硬编码假设。Worker 先支持旧 minor 与新 minor，再切换 Runtime 镜像和 Agent Publication。未知 major、未知 event type 和 schema 不合法事件继续 fail closed。

数据库使用一份新的 expand migration 创建两表、索引、外键、约束与注释，并同步 `backend/app/shared/schema_fact_sources.json` 及相应 schema 校验测试。apply 阶段必须先检查现有 migration head，再选用下一个版本号；不得覆盖当前 active migration 或修改已应用 migration。该变更没有旧表收缩或删除，因此不需要 contract migration。

## Risks / Trade-offs

- [逐轮耗时不等于 Provider HTTP Span] → 字段和页面固定使用 `SDK_OBSERVED`，起点不可靠时返回未知；query 级 `duration_api_ms` 单独展示。
- [SDK 消息类型或字段随版本变化] → 锁定当前 SDK/CLI 版本、使用 fixture 合同测试、白名单归一化字段，并通过 Runtime minor version 演进。
- [可见模型轮次数与 `modelUsage` 覆盖范围不同] → 分别展示 `observed_model_turn_count` 与按模型总 usage，不把二者声明为可一一对账。
- [旧 Job 与异常退出 Job 数据不完整] → 使用 `COMPLETE | PARTIAL | UNAVAILABLE`，未知字段保持 `NULL`。
- [多 invocation 重算增加写放大] → Job retry 有上限，重算只扫描单 Job 的终态和轮次索引；禁止全表聚合。
- [错误摘要意外携带 Secret 或业务正文] → 仅接受 typed code/status，复用脱敏器、长度上限与 Secret 负向测试；无法安全归类时只存 `UNKNOWN`。
- [与统一 MCP 审计 active change 发生协议或 migration 冲突] → apply 前读取当前 ledger 和 migration head，复用其已落地字段，不复制或回退其变更。
- [汇总与 Runtime event 在崩溃时短暂不一致] → 同事务写入并提供按 Job 重建命令；重建过程也按唯一终态重算。

## Migration Plan

1. 核对当前 migration head、Runtime 协议 ledger、`unify-mcp-operation-audit` 的实际落地状态和工作树，选定新的 expand migration 与下一个 minor version。
2. 新增两张表、约束、索引、注释和 Schema fact-source 登记；先部署数据库，不改变现有查询。
3. 扩展共享 Runtime schema、fixture 和 Worker parser；部署能双读旧版和新版事件的 Worker，并保持旧 Runtime 为默认。
4. 更新 TypeScript/Python Runtime 归一化器与合同测试，发布新 Runtime 镜像，但暂不切换 Agent Publication。
5. 以受控测试 Application 切换新版 Runtime，验证成功、API retry、MCP 连接失败、模型失败、工具拒绝、工具失败、超时、Job retry、终态恢复和重复 MQ 投递。
6. 扩大 Publication 切换范围，再上线管理 API 与页面筛选；旧 Job 显示 `UNAVAILABLE`。
7. 观察数据库写入、查询延迟、部分统计比例和失败分类分布后，结束旧 minor 的发布窗口；移除旧版支持须另立明确 change。

回滚时先停止新版 Publication 切换并恢复旧 Runtime；Worker 保留双读和新增表以读取已产生数据。新增表和 migration 不回滚或删除，页面可通过功能开关隐藏新增投影。若聚合逻辑有问题，暂停汇总更新并从保留的合同事件按 Job 重建，不能修改 `agent_job` 生命周期事实。

## Open Questions

无待用户确认的功能性问题。实施开始时仍需基于当前 checkout 解析两个机械事实：下一个可用 migration 版本和下一个可用 Runtime minor version；这两项不得在提案阶段固定为未经核对的编号。
