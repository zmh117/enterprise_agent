## MODIFIED Requirements

### Requirement: Debug API documentation shall cover real-tools verification
系统 SHALL 在调试 API 文档中提供 real-tools 验证流程，覆盖创建 job、轮询状态、查询 steps、查询 tool-calls，并说明如何确认工具调用来自固定 `tool-mcp` 服务及实际 Published Resource Revision。

#### Scenario: 查询 real-tools tool calls
- **WHEN** 开发者按 real-tools 文档提交 debug job
- **THEN** `GET /api/agent/jobs/{job_id}/tool-calls` SHALL 返回工具名称、状态、耗时、风险等级、脱敏请求摘要、响应摘要和实际 Resource Revision metadata

#### Scenario: 工具链失败排查
- **WHEN** debug job 失败
- **THEN** 文档 SHALL 指引开发者检查 job 状态、worker/runtime 日志、tool-calls、`tool-mcp` health、资源发布状态、Secret 状态和对应只读工具的安全错误分类

### Requirement: Debug smoke documentation shall include failure triage
系统 SHALL 在 smoke 文档中记录失败排查顺序，覆盖 job detail、worker/runtime logs、RabbitMQ 消费、runtime config degraded、Secret 状态、`tool-mcp` 健康状态和 Published Resource Revision 解析结果。

#### Scenario: Smoke job fails
- **WHEN** smoke job 返回 `FAILED`、`TIMEOUT` 或长时间停留在 `PENDING`
- **THEN** 文档 SHALL 提供 curl/docker compose 命令定位失败发生在 API 接收、RabbitMQ、worker、Claude runtime、`tool-mcp`、Secret resolver、资源解析或只读适配器哪一段

### Requirement: Agent sessions and jobs are persisted
The system SHALL persist Agent sessions, Agent jobs, user messages, assistant messages, retry metadata, result summaries, failure reasons, source channel metadata, requester identity, routing context, reply route, and an immutable MCP Tool Execution Snapshot before dispatch. The Snapshot MUST include the exact Agent/Application Publication and each allowed MCP server code, Tool identifier and schema hash required by the Job; it MUST NOT include Tool Release, Handler Version, dynamic MCP URL, Application Resource Mapping or Resource Revision.

#### Scenario: New diagnostic request is accepted
- **WHEN** a verified Channel request passes connector, publication, identity and permission checks
- **THEN** the system persists the session, Job, user message, routing facts and complete MCP Tool Execution Snapshot before publishing the Job to the message bus

#### Scenario: Agent result is produced
- **WHEN** Agent execution completes with a final answer
- **THEN** the system persists the assistant message, result summary, Job completion timestamp, delivery-ready result artifact and exact Tool Call fact references

#### Scenario: Legacy DingTalk request is accepted during cutover
- **WHEN** an existing DingTalk endpoint creates a new Job after MCP snapshot cutover
- **THEN** the system persists equivalent generic channel fields and a complete MCP Tool Execution Snapshot; it MUST NOT create a new `legacy-v1` tool binding

#### Scenario: Snapshot cannot be constructed uniquely
- **WHEN** the active Agent/Application Publication cannot produce one consistent MCP Tool identifier/schema hash intersection
- **THEN** Job creation fails before queue dispatch and records a safe non-retryable composition error

### Requirement: 运行中的业务能力调用重新校验当前授权
系统 SHALL 在运行中每次 MCP Tool 或外部业务能力调用前重新校验当前角色成员状态、业务应用 Tool 子集和数据范围。权限变化导致的拒绝 MUST NOT 重试，也不得访问目标数据源。

#### Scenario: 执行中撤销数据范围
- **WHEN** job 运行期间管理员撤销目标基地范围，随后 Agent 请求该基地能力
- **THEN** 系统在 `tool-mcp` 建立上游连接前拒绝请求并记录授权变化

### Requirement: Job 必须保存创建时的授权与资源事实
Job MUST 保存内部用户、Agent/Application Publication、允许的 MCP Tool identifier/schema hash、授权事实摘要、Execution Scope 和 Session 策略快照；MUST NOT 保存 Handler Version、Application Resource Mapping 或 Resource Revision binding。后续配置变化不得扩大该 Job 的 Tool 集合或身份边界，每次资源调用仍 MUST 实时复核当前数据范围并解析当前唯一 Published Resource Revision。

#### Scenario: Job 排队期间用户权限被撤销
- **WHEN** Worker 开始执行前发现当前严格 RBAC 已撤销
- **THEN** Worker 必须拒绝执行并记录安全授权失败

#### Scenario: 资源发布新 revision
- **WHEN** Job 创建后同一 Resource Identity 发布新版本
- **THEN** 后续 Tool Call 只可在原 Job Tool 集合和当前数据范围内解析新的唯一 Published Revision，并记录实际版本；不得改写 Job Snapshot 或回退旧 Revision

### Requirement: Job Tool Execution Snapshot must be immutable
系统 MUST 在 Job 创建后禁止修改其 Agent/Application Publication、MCP server code、Tool identifier、schema hash、身份、Execution Scope 和授权事实摘要；Resource Revision、placement 和资源策略不写入 Job Snapshot，而由每次 Tool Call 在当前授权内唯一解析并作为调用事实记录。

#### Scenario: Resource rotates after job creation
- **WHEN** Job 已创建后 Resource Identity 发布了新 Revision
- **THEN** Job Snapshot 保持不变，后续 Tool Call 解析当前唯一 Published Revision并记录实际版本

#### Scenario: Operator attempts to edit snapshot
- **WHEN** 管理 API、恢复命令或数据库 repository 请求替换已有 Job 的 MCP Tool 或授权快照
- **THEN** 系统拒绝修改并记录审计，不提供普通 CRUD 覆盖路径

### Requirement: Retry and replay must use the original snapshot
所有自动重试、Outbox replay 和授权的显式恢复 MUST 使用原 Job 的 Agent/Application Publication、MCP Tool identifier/schema hash、身份与 Execution Scope 快照，并重新检查当前角色、应用 Tool 子集和数据范围；资源在实际调用时重新唯一解析，MUST NOT 使用动态 MCP URL、旧 Application Resource Mapping 或已停用 Resource Revision。

#### Scenario: Retry after application upgrade
- **WHEN** 原 Job 失败后应用切换到新的 Application Publication
- **THEN** 重试仍使用原 Publication 和 MCP Tool Snapshot

#### Scenario: Tool schema no longer matches
- **WHEN** 当前代码 Manifest 中同名 Tool 的 schema hash 与 Job Snapshot 不一致
- **THEN** Runtime 或 `tool-mcp` 不执行相似名称工具，并报告安全的 schema drift 错误

#### Scenario: Resource is no longer uniquely resolvable
- **WHEN** 重试中的 Tool Call 对当前目标解析到零个或多个 Published Resource Revision
- **THEN** 该调用失败关闭，不自动使用旧 Revision或第一候选

### Requirement: Tool Call must record the actual resolved placement and scope
每次资源型 Tool Call SHALL 持久化实际选择的 placement、Resource Revision、当前数据范围授权判定、适用 selector 或 namespace 的安全摘要、correlation id 和 MCP Tool identifier/schema hash，并 MUST NOT 保存 Secret 或无界业务响应。

#### Scenario: Cloud resource is selected
- **WHEN** 某次 Tool Call 明确请求 cloud 且当前目标唯一解析到 cloud Resource
- **THEN** Tool Call 记录 `cloud` 和其精确 Resource Revision，后续同 Job 的其它调用继续独立解析

#### Scenario: No-placement resource is selected
- **WHEN** Job 使用没有 placement 维度的 Redis Resource
- **THEN** Tool Call 记录 placement 缺省而不是 `none` 或 `standalone`

### Requirement: 诊断上下文必须包含目标 schema 目录
系统 SHALL 通过 `tool-mcp` 的 `get_schema_directory` Tool 为明确目标提供当前可访问的 schema 目录，或明确说明目标无法唯一解析。目录 MUST 来自当前唯一 Published Database Resource Revision，只包含按当前权限和资源范围过滤后的表、列和非密钥元数据。

#### Scenario: 单一目标问题获取 schema
- **WHEN** Agent 已明确 environment/base/workshop 并调用 `get_schema_directory`
- **THEN** Tool Call 返回该目标当前可访问的 schema 目录摘要，供模型生成 SQL 前检查可用表和字段

#### Scenario: 目标不明确时不猜 schema
- **WHEN** 用户问题不能唯一确定 environment/base/workshop
- **THEN** Agent 必须先澄清或通过允许的上下文工具解析目标，不得猜测目标代码、Resource 或表名
