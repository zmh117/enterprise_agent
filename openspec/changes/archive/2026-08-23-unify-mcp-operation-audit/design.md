## Context

当前存在三条不一致的 Tool 事实链：

- `tool-mcp` 在 `ReadOnlyToolService` 内直接创建并完成 `agent_tool_call`，但不写 `mcp_operation_audit`。
- `ones-mcp` 写 `mcp_operation_audit` 与 `audit_event`，但不创建 `agent_tool_call`；现有 Worker 只能按 `job_id + tool_name` 尝试补链，在线记录已出现 `agent_tool_call_id` 为空。
- Runtime 另外把 SDK Tool Event 交给 Worker 写 `agent_tool_call`。TypeScript 使用真实 SDK Tool Use ID，但未知拒绝事件默认标记为 `tool-mcp`；Python 的归一化对未知 Tool 也默认使用 `tool-mcp`，且原始 `tool_use`/`tool_result` 尚未稳定提取同一个 Tool Use ID。

`agent_tool_call` 是 Job Tool Call 查询和 Runtime 原生 Tool 审计的长期事实，不能由 MCP 审计替代；`mcp_operation_audit` 是真正进入 MCP Server 后的详细执行证据，也不能由 Runtime 摘要替代。本设计建立明确的一对多关系，并覆盖两个 Runtime、两个 MCP Server、失败恢复和保留期清理。

## Goals / Non-Goals

**Goals:**

- 让 `tool-mcp` 与 `ones-mcp` 使用同一套通用 MCP 审计模型。
- 让每次 MCP Tool Call 对应一条 `agent_tool_call`，并与所有 MCP 执行证据精确关联。
- 修复 Python/TypeScript Runtime 对未知或 SDK 原生 Tool 的 MCP 来源误判。
- 保留有界完整业务审计，同时结构性排除所有认证材料。
- 保持 Job Tool Call API 路径与管理员 MCP 审计 API 可持续查询。
- 通过 expand → dual-read/write → cutover 的顺序部署，保留现有数据并允许回滚。

**Non-Goals:**

- 不删除 `agent_tool_call`，不把 SDK 内置或自定义 Tool 写入 `mcp_operation_audit`。
- 不开放新的 SDK 内置工具、任意 MCP Server、任意 URL 或动态 Tool 实现。
- 不改变 ONES 查询范围、身份绑定、Principal JWT 或 Token 刷新业务规则。
- 不在本变更中引入独立审计数据库、消息队列或外部可观测平台。
- 不按名称、时间窗口、参数 hash 或插入顺序推断历史记录之间的关联。

## Decisions

### 1. 两张表分别承担 Runtime 事实和 MCP 执行证据

`agent_tool_call` 继续作为一次逻辑 Tool Use 的主事实。它新增：

- `invocation_id`
- `runtime_tool_call_id`
- `tool_origin`：`mcp | sdk_builtin | sdk_custom | unknown`
- 可空 `server_code`
- 可空且唯一的 `mcp_call_id`
- 可空 `persisted_by`：`mcp_server | worker`

`mcp_operation_audit` 继续作为事件表，并新增或通用化：

- `mcp_call_id`：一次 MCP 调用的稳定分组键
- `parent_audit_id`：可选父事件
- `invocation_id`
- `agent_tool_call_id`
- `event_kind`：`TOOL | AUTHORIZATION | RESOURCE | PROVIDER | CREDENTIAL`
- 通用的业务目标、Resource identity/revision、权限判定和有界请求/响应字段

ONES 的 Principal、External Identity、Credential、Team 和 Provider User 字段改为可选扩展；`tool-mcp` 不填伪造的 ONES 值。现有 ONES 行保留，`mcp_call_id` 可确定性回填为其 TOOL 事件 ID 或既有 correlation 派生的迁移 ID，但未知 `agent_tool_call_id` 保持空，不猜测关联。

选择该方案而不是合并两表，是因为 SDK 原生/自定义/拒绝 Tool 不会进入 MCP Server，而一次 MCP 调用又可能产生多次 Provider/Resource/Credential 证据和独立保留周期。

### 2. MCP Server 是 MCP Tool Call 主事实的首写方

共享模块提供 `McpAuditCoordinator`：

1. 在验证出有效 Job、Session、Invocation 与 Tool 后生成 `mcp_call_id`。
2. 在任何受治理 Resource/Provider 访问前，以一个数据库事务创建 `agent_tool_call(STARTED)` 和 MCP `TOOL(STARTED)` 根事件，并立即互相精确关联。
3. 写入 AUTHORIZATION/RESOURCE/PROVIDER/CREDENTIAL 子事件。
4. 在成功、失败或拒绝时完成同一 `agent_tool_call` 和 TOOL 根事件。
5. 在 `CallToolResult._meta` 返回 `mcp_call_id` 与 `agent_tool_call_id`。

`tool-mcp` 移除 `ReadOnlyToolService` 内分散的 Tool Call 写入职责，`ones-mcp` 接入同一协调器。无有效 Job 的传输拒绝仍进入平台安全审计/指标，不创建带伪造外键的 MCP 操作记录。

选择 MCP Server 首写而不是等待 Worker，是为了在外部访问发生前建立审计根事实，并使外部访问失败、Runtime 断连或 Worker 重试时仍保留真实执行证据。

### 3. 使用标准 MCP `_meta` 传播服务端关联标识

MCP Server 在 `CallToolResult._meta` 的平台命名空间中返回：

- `enterprise-agent/mcp-call-id`
- `enterprise-agent/agent-tool-call-id`

Runtime 从 Tool Result 元数据提取这些字段，将其与 SDK Tool Use ID 一起写入终态 Tool Event；元数据不进入模型可见文本、structured business result 或 Tool Input Schema。Worker 收到后按服务端 ID更新已有 `agent_tool_call` 的 `runtime_tool_call_id`，并跳过重复插入。

实施第一步必须用当前固定的 Python/TypeScript Agent SDK 做契约测试，证明 `_meta` 保真。若任一 SDK 丢弃 `_meta`，验收失败并停止关联切换；不得退回 `job_id + tool_name`、时间窗口或载荷 hash。此约束优先于“看起来已关联”的非确定性兼容。

### 4. Runtime 只依据已发布事实判定 Tool 来源

来源分类顺序固定为：

1. Tool 的完整 SDK 名称与当前 Job 的 MCP alias、Server code 和 Tool identifier 精确匹配 → `mcp`。
2. 名称属于代码内固定 SDK builtin 目录 → `sdk_builtin`。
3. 名称属于平台注册 SDK Tool 目录 → `sdk_custom`。
4. 其它 → `unknown`。

只有第 1 类可设置 `server_code`。Python 必须从 `tool_use.id` 和 `tool_result.tool_use_id` 提取同一 `runtime_tool_call_id`；TypeScript 延续 `permissionOptions.toolUseID`。Worker 以 `(job_id, invocation_id, runtime_tool_call_id)` 幂等聚合 STARTED/终态事件。

这取代当前 Python 的 `published.get(tool_name, alias_server or "tool-mcp")` 和 TypeScript 未识别拒绝事件的 `tool-mcp` 缺省值。

### 5. Runtime 协议采用 v1.1 双读迁移

新增 `agent-runtime/contracts/v1.1`，Tool Event 显式包含 `tool_origin`，并让 `server_code`、`mcp_call_id`、`persisted_tool_call_id` 按来源可空。Worker 先支持 v1.0 与 v1.1；对 v1.0 事件只能基于 Job 冻结 Binding 保守归类，无法唯一匹配时使用 `unknown`。

随后部署两个 v1.1 Runtime，最后让新 Agent Publication 固定 v1.1。既有 v1.0 Job 在兼容窗口内继续执行。该方案避免在严格 `additionalProperties=false` 的 v1.0 Schema 上静默改变含义。

### 6. 业务载荷不做普通字段脱敏，但认证材料必须结构性排除

审计可在配置上限内保存完整业务输入和业务输出。共享序列化器递归拒绝认证字段和值类型，包括密码、Token、Authorization/Cookie、Credential ciphertext、Nonce、私钥、Secret reference 解析值和带凭据 URL。该规则应用于 Tool、Resource、Provider、Credential 事件和异常路径。

普通业务字段不因名称或内容被泛化掩码；超出大小边界时记录截断标志和稳定摘要，不保存无界正文。

### 7. 保留周期只清理 MCP 详细证据

`MCP_OPERATION_AUDIT_RETENTION_DAYS` 继续控制 `mcp_operation_audit`。清理按外键策略安全删除子事件与根事件，但不级联删除 `agent_tool_call`、Job 或 `audit_event`。Job Tool Call 查询因此在详细 MCP 审计过期后仍可返回长期安全摘要。

### 8. 查询接口保持用途分离

- `/api/agent/jobs/{job_id}/tool-calls` 继续读取 `agent_tool_call`，增加 origin、server、runtime/mcp call ID 的受控投影。
- `/api/admin/mcp-operation-audits` 读取全部 MCP 事件，并增加 server、tool、event kind、status、job 与 mcp_call_id 筛选。
- 详细审计读取继续要求 `audit:*:read` 并记录读取审计。

## Risks / Trade-offs

- [Agent SDK 不暴露 MCP `_meta`] → 先做两个固定 SDK 的真实契约测试；失败则停止切换，绝不采用模糊关联。
- [MCP Server 首写与 Worker 终态更新并发] → 使用唯一约束、期望状态更新和幂等 upsert；服务端 ID拥有最终关联权。
- [Runtime v1.0/v1.1 混跑] → Worker 先双读，Runtime 后升级，新 Publication 最后切换，并以协议矩阵测试覆盖。
- [审计写入增加数据库负载] → 单次调用根事实事务保持小而有界，子事件使用索引化批次写入，保留期任务按主键分页。
- [审计不可用导致 Tool 失败] → readiness 主动验证 Schema 和写权限；失败关闭优先于产生不可审计外部访问。
- [现有 ONES 记录无法精确补链] → 保留记录并标注 legacy/unlinked，不对历史数据做猜测性回填。
- [完整业务审计增加数据敏感度] → 严格 RBAC、大小边界、认证材料拒绝、保留期清理和每次读取审计共同约束。

## Migration Plan

1. 增加 SDK `_meta` 保真契约测试和 v1.1 Runtime Schema，不切流量。
2. 通过下一顺序 migration 扩展两张表、约束和索引；保留现有行，对可确定字段做非破坏回填。
3. 部署支持 v1.0/v1.1 的 API、Worker、Repository 与共享 `McpAuditCoordinator`，旧 MCP 写入仍可工作。
4. 先切换 `tool-mcp`，验证单次、重复、并发、失败和资源审计；再切换 `ones-mcp`，验证 Provider 与 Token 刷新证据。
5. 部署 Python/TypeScript Runtime v1.1，验证 Tool 来源、SDK Tool 拒绝与 `_meta` 传播。
6. 将新 Agent Publication 的 Runtime 协议切到 v1.1，完成 Compose 双 Runtime E2E 和在线数据库关联检查。
7. 删除 `job_id + tool_name` 模糊关联代码；保留数据库兼容列到后续独立 contract migration。

回滚时先停止新 Publication 使用 v1.1，恢复 Runtime v1.0，再回退 MCP 写入协调器与 Worker；expand migration 和新增列保留，不删除已产生的审计数据。

## Open Questions

无。`_meta` 保真是实施门禁而非允许模糊替代的开放设计选择。
