## Context

当前只读诊断 Agent 已经通过 RabbitMQ worker 调用真实 Claude Agent SDK，并通过 in-process MCP 只读工具访问 Internal API Platform。近期本地验证暴露了三个问题：

1. 真实 SDK 工具循环触发 `AGENT_MAX_TURNS=12` 后，`RealClaudeCodeAgentClient.run()` 抛出错误，`AgentExecutor` 没有机会持久化已收集的 runtime tool events，`GET /tool-calls` 只看到进入模型前的 context 工具。
2. Internal API Platform 已能按 topology 路由数据库，但 context 工具只返回 addressing，不返回真实表/字段目录。模型面对 `CRMES_TEST_CLOUD_GL` 这类本地样例库时只能猜 `GL001_EBR_mo`、`GL001_EBR_order` 等表，导致持续 400/表不存在。
3. Prompt 没有明确把“schema 不足、表不存在、字段缺失、连续策略拒绝”定义成停止条件，模型倾向继续尝试相邻表名，而不是给出“不具备诊断证据”的报告。

约束仍然不变：第一版是只读诊断 Agent；Agent runtime 不直连 MySQL/Redis/Loki；数据库、Redis、Loki 访问必须经 Internal API Platform；不得通过调大 `AGENT_MAX_TURNS` 掩盖工具循环缺陷。

## Goals / Non-Goals

**Goals:**

- 真实 Claude runtime 在失败、timeout、max-turns exhaustion 路径也保留已发生的工具调用摘要。
- Agent 在模型执行前拿到按 environment/base/workshop 和权限过滤后的 schema 目录，用目录约束 SQL 生成。
- Internal API Platform 提供安全的 schema directory endpoint，只暴露表、列、类型、可选行数/注释等非密钥元数据。
- 模型遇到缺证据场景时停止扩散式试错，输出证据不足报告，而不是继续消耗 turns。
- Debug API 能展示失败前的工具轨迹，方便定位是 schema 不足、SQL 策略拒绝、上游不可达还是模型循环。

**Non-Goals:**

- 不引入写操作、自动修复、重启服务、修改数据库或代码变更能力。
- 不绕过 Internal API Platform 让 Agent runtime 直连数据库。
- 不把 MySQL `SHOW TABLES`、`DESCRIBE` 等非 SELECT 语句开放给模型；schema 目录由平台专用只读服务提供。
- 不把完整数据库导出塞进 prompt；schema 目录必须 bounded，并按目标拓扑过滤。
- 不保证在业务库本身缺少订单表或订单字段时给出业务根因；此时应明确证据不足。

## Decisions

### 1. 用运行时事件缓冲对象承载失败路径工具事件

`RealClaudeCodeAgentClient` 现在在 `_run_async()` 内维护 `tool_events` 列表，但异常抛出后调用方拿不到这个列表。新增一个内部异常或结果包装机制，例如 `ClaudeRuntimeErrorWithEvents`，携带 `safe_message`、retry 分类和 bounded `tool_events`。`AgentExecutor` 捕获后先持久化事件，再按现有 retry service 处理 job 状态。

替代方案是让 tool handler 每次调用后立即写库。暂不采用，因为 tool handler 位于 infrastructure runtime 层，直接写 repository 会破坏 `AgentExecutor` 统一持久化边界，也更难复用 fake SDK 测试。保留事件缓冲，由 executor 负责落库。

### 2. max-turns exhaustion 作为确定性诊断循环失败处理

`Reached maximum number of turns` 不是普通网络抖动。运行时应将其映射为带工具事件的安全失败，并让 retry 策略能够避免对同一输入立即重复消耗。实现上可以新增非重试错误类型，或在 retry service 中识别 `max_turns_exhausted` 这类错误码。

替代方案是提高 `AGENT_MAX_TURNS`。不采用，因为这只会扩大无效查询次数，不能解决缺 schema 和缺停止条件的问题。

### 3. Schema directory 是 Internal API Platform 能力，不是 Agent 直连 DB introspection

平台新增 schema directory 应用服务：

- 输入：`user_id`、`environment`、`base`、`workshop`、可选 `query` / `table_prefix` / `limit`。
- 输出：当前 caller 有权访问的表清单、列清单、列类型、nullable、可选表行数估计、metadata.source、truncated。
- 策略：复用 topology registry 和 access policy；partitioned base 必须带 workshop；只返回匹配 `table_prefix` 的表；结果数量和字符数受限。

实现上由平台基础设施层使用数据库元数据 API 或 information_schema 查询。这个查询不暴露给模型执行，不走 `query_database` 的用户 SQL 策略，避免为了 schema introspection 放宽业务 SQL 白名单。

### 4. ContextBuilder 预取 schema 目录并注入 prompt

`AgentContextBuilder` 继续先调用 `get_er_context` / `get_business_flow_context`，再基于 addressing 和用户问题解析候选 environment/base/workshop，调用新的 `get_schema_directory` 工具。首版可以只在存在明确单一目标时预取；若目标不明确，则把可用 addressing 放进 prompt，要求模型先解析目标，再调用 schema 工具。

Prompt 必须新增硬规则：

- SQL 只能引用 schema directory 中存在的表和列。
- 不能猜测未出现在目录中的业务表名。
- 如果目录为空、缺少订单号字段、缺少状态字段、或连续工具拒绝达到阈值，停止工具调用并输出“不具备诊断证据”。

### 5. 平台错误摘要要帮助模型停止，而不是诱导继续猜

数据库 gateway 对表不存在、字段不存在、跨 workshop 前缀、非 SELECT、空 schema 等错误返回结构化 safe summary，例如：

```json
{
  "error": "table_not_available",
  "message": "Table GL001_EBR_mo is not in the schema directory for sanjiu/guanlan/GL001.",
  "diagnostic_action": "stop_or_use_schema_directory"
}
```

模型收到这类结果后应将其当作证据限制，而不是继续换相邻表名。

## Risks / Trade-offs

- [Risk] schema directory 可能很大，导致 prompt 过长 -> Mitigation：按 workshop 前缀过滤、限制表数/列数、支持 query 过滤，并标记 truncated。
- [Risk] information_schema 权限或不同数据库方言行为不一致 -> Mitigation：在 platform infrastructure 按 MySQL / SQL Server / Oracle 分驱动实现，首批测试覆盖 MySQL，其他方言保留明确错误。
- [Risk] max-turns 被改成非重试后可能掩盖真正瞬时问题 -> Mitigation：只对明确的 `Reached maximum number of turns` / tool-loop exhaustion 分类，不改变网络超时、429、503 等 transient 分类。
- [Risk] 失败事件重复持久化 -> Mitigation：事件持久化由 `AgentExecutor` 单点执行，失败路径和成功路径使用同一去重/插入策略；测试覆盖 retry 后不会重复写同一批事件。
- [Risk] 模型仍可能忽略 prompt -> Mitigation：工具层继续强制 SQL 只读、前缀隔离和 schema 拒绝；prompt 只是减少无效调用，不承担安全边界。

## Migration Plan

1. 新增 schema directory 平台服务、endpoint、client contract 和工具定义。
2. 扩展 Agent context 构建与 prompt，要求基于 schema 查询，不猜表。
3. 扩展 Claude runtime 错误类型和事件缓冲，失败路径把已收集 tool events 交给 executor。
4. 调整 retry 分类，max-turns exhaustion 不再默认作为普通瞬时失败反复重试。
5. 更新 README 本地验证步骤：覆盖 schema directory、缺表/缺字段报告、失败 tool-calls 可见性。

回滚方式：关闭真实 Claude 或回退到 stub runtime；schema directory endpoint 是只读新增能力，回滚不需要数据迁移。若失败事件持久化引入问题，可通过 feature flag 暂停失败路径事件落库，但不应影响平台只读安全策略。

## Open Questions

- schema directory 是否需要返回样例值或 distinct enum？首版建议不返回，避免敏感数据进入 prompt；如需枚举，应单独设计 bounded sampling 策略。
- max-turns exhaustion 是否直接标记 FAILED，还是保留一次重试但带不同退避？建议首版标记非重试，避免同一 prompt 重复消耗。
- 多目标问题（例如用户同时提到 GL001 和 GL002）是否允许一次 job 查询多个 workshop？建议首版要求模型选择单一目标或报告目标不明确。
