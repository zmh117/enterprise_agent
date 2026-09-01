## ADDED Requirements

### Requirement: 每个 Runtime invocation 必须保存完整上下文审计
系统 MUST 为每个已完成上下文构建的 Agent Runtime invocation 保存不可变审计，包含完整应用 System/User Prompt、实际进入模型的上下文来源、SDK 原始消息、模型可见工具输入输出、Messages API 原始 request/response、usage、状态和时间。系统 MUST NOT 对这些正文执行应用层脱敏或长度截断；系统 MUST NOT 主动复制 Runtime Credential 或认证 Header。

#### Scenario: 成功 invocation
- **WHEN** Python Runtime 完成模型循环
- **THEN** Worker 持久化与 Runtime 实际装配和返回一致的完整审计
- **AND** 现有 Tool/MCP 主账继续保存安全摘要

#### Scenario: 失败或超时 invocation
- **WHEN** Runtime 在产生部分 SDK 消息或工具结果后失败或超时
- **THEN** 系统在失败或重试处理前保存已经产生的完整审计

#### Scenario: Provider 隐藏 reasoning
- **WHEN** SDK/Provider 未返回 hidden reasoning 正文
- **THEN** 系统原样保存实际暴露内容并标记限制，不构造缺失内容

### Requirement: 完整审计必须通过 Runtime v1.5 可验证分块传输
Runtime MUST 将审计 JSON 以带连续索引、总块数、编码和 SHA-256 的 `audit_chunk` 事件传输，并在 terminal 重复声明完整性元数据。Worker MUST 在持久化前验证块序、总数、摘要和 JSON 类型；不完整或冲突的审计 MUST fail closed。v1.4 schema MUST 保持不变。

#### Scenario: 相同 invocation 恢复重放
- **WHEN** Worker 在收到部分 stream 后使用相同 invocation/request digest 恢复
- **THEN** Runtime 重放同一组审计块与 terminal
- **AND** Worker 只持久化一份内容一致的 invocation 审计

#### Scenario: 审计块缺失
- **WHEN** terminal 声明的块数或摘要与已收集内容不一致
- **THEN** Worker 以 Runtime 协议错误终止，不保存伪完整审计

#### Scenario: 审计块位于安全事件与终态之间
- **WHEN** Runtime v1.5 在安全事件之后、terminal 之前发送一个或多个 `audit_chunk`
- **THEN** Worker 按 Runtime 原始 sequence 保存不含 Base64 `content` 的审计块结构元数据与 terminal
- **AND** `agent_runtime_event` 序列保持连续，完整审计在校验重组后仍只保存一份

### Requirement: 调优摘要必须区分实际 usage 和构成估算
系统 SHALL 保存每轮/Result usage、请求次数、峰值上下文、Token/cache/cost、注册工具、单次最大加载工具、无需确认工具、调用次数和不同工具数。`allowed_tools` 仅计入无需确认工具，不得冒充注册或加载工具总数。峰值上下文按 `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` 计算；字符估算 MUST 标明估算方法，不得冒充 Provider 计费事实。

#### Scenario: 多轮 Tool Loop
- **WHEN** 一个 invocation 产生多次模型 request 和重复工具调用
- **THEN** 页面分别展示请求次数、峰值上下文、累计 usage、注册/加载/调用/不同工具口径

### Requirement: 模型可见会话与上下文清单必须去除确定性重复
系统 MUST 让当前 Job 输入只作为 User Prompt 进入模型一次，并 MUST 在构造滚动摘要和最近历史窗口前按规范 `input_message_id` 排除当前输入。系统 MUST 将滚动摘要和最近历史消息只渲染为一份模型可见会话正文；`retrieved_context` 只可携带不重复正文的会话计数、截断和安全元数据。上下文清单 MUST 为每个来源只保存一份规范化 `content`，不得同时持久化可由该 `content` 确定性生成的 `rendered_text` 正文副本。该语义变更 MUST 使用新的 Prompt template version，历史 Job 的观测版本不得被回写。

#### Scenario: 当前问题已经写入 Session
- **WHEN** 当前 Job 的输入消息已存在于最近 Session 消息中
- **THEN** 历史上下文按 `input_message_id` 排除该消息
- **AND** 相同正文但不同消息 ID 的更早消息仍作为真实历史保留
- **AND** 当前问题只通过 User Prompt 发送一次
- **AND** 新 Job 报告 `agent-system-prompt-v5`，历史 Job 保持原 Prompt template version

#### Scenario: 管理员查看上下文清单
- **WHEN** `agent_run_audit` 保存包含字符串、数组或对象的上下文来源
- **THEN** 每个来源只保存完整规范化 `content`、字符数、Token 估算和截断事实
- **AND** 页面从 `content` 渲染正文，不要求持久化第二份 `rendered_text`

### Requirement: 完整正文查询必须先通过现有 Job 授权
完整审计 MUST 只通过要求 `jobs.read` 且命中现有业务范围的管理 Job 详情返回。系统 MUST 在读取大正文前完成 scope 判断；Debug evidence、Tool Call 和 MCP 查询 MUST 继续返回安全摘要。

#### Scenario: 范围外 Job
- **WHEN** 当前用户缺少 `jobs.read` 或目标 Job 不在其业务范围
- **THEN** API 返回拒绝或 404，且不查询或返回完整审计正文

### Requirement: 运行详情必须摘要优先并折叠长正文
Agent 运行详情 SHALL 保留现有执行、工具合同、文件和 Delivery 证据，并增加调优摘要。每个 attempt 的上下文/Prompt、模型 request/response、工具 I/O、usage/元数据 MUST 默认折叠；展开后 MUST 支持换行、固定最大高度和滚动。

#### Scenario: 超长上下文
- **WHEN** 管理员打开包含超长 Prompt 和工具结果的 Job
- **THEN** 初始页面保持紧凑，管理员可逐组展开并完整滚动查看

#### Scenario: 工具契约证据较长
- **WHEN** 管理员打开包含工具快照、多个 invocation 观测和逐工具状态矩阵的 Job
- **THEN** 工具契约卡片的标题、说明、状态和总体摘要保持可见
- **AND** Job 快照及每个 invocation 内的长证据分组默认折叠
- **AND** 管理员可逐组独立展开或收起内部证据

#### Scenario: 工具契约摘要包含长标识
- **WHEN** Invocation ID 或其他摘要值超过单个网格列宽
- **THEN** 长标识在所属指标单元内断行
- **AND** 不得覆盖相邻指标的标题或内容

#### Scenario: 历史 Job
- **WHEN** Job 创建于完整审计启用前
- **THEN** 页面说明审计不可用，不按当前配置回填历史上下文

## MODIFIED Requirements

### Requirement: 模型运行记录必须只展示安全Provenance
系统 SHALL 在 Agent Job、普通运行记录和安全诊断中保存 Agent Publication、模型连接 revision/config hash、模型、effort 和脱敏 Provider Host，并 MUST NOT 持久化 API Key、Auth Token、Secret ref/value、Runtime Grant、Principal JWT、认证 Header、Cookie、完整 Base URL 查询参数或 private thinking。作为唯一例外，Runtime protocol v1.5 的 `agent_run_audit` 专用链 MAY 保存完整应用 Prompt、SDK/模型原始响应、模型可见 Tool I/O 和 Provider request/response，并只在管理 Job 详情通过 `jobs.read` 与业务范围检查后返回；这些完整正文不得复制到普通运行记录、搜索列表或安全诊断字段。

#### Scenario: 查看成功 Job 的完整调用审计
- **WHEN** 管理员通过 `jobs.read` 与目标 Job 业务范围检查
- **THEN** Job 详情返回该 invocation 实际保存的完整 Prompt、SDK/模型响应、模型可见 Tool I/O 和 Provider request/response
- **AND** 不返回 Credential、认证 Header、Cookie、完整敏感 URL 或 private thinking

#### Scenario: Provider认证失败
- **WHEN** Claude Agent SDK 因 Key 无效返回认证错误
- **THEN** Job 记录稳定安全错误码和脱敏 Provider Host
- **AND** 普通日志、安全诊断和原会话失败投递不包含 Key、请求头或上游响应正文
- **AND** `agent_run_audit` 只保存已采集的请求/响应 body，不主动复制 Credential、认证 Header 或 Cookie

### Requirement: Runtime不得泄漏凭据和私有推理
模型 Key、Runtime Grant、Master Key、Secret ref/value、Principal JWT、认证 Header、Cookie、完整敏感 URL 和 private thinking MUST NOT 出现在 RabbitMQ、Job 快照、Runtime 日志、事件、恢复账本、响应或审计中。完整 Prompt、SDK/模型原始响应、模型可见 Tool I/O 和 Provider request/response 只允许出现在 Runtime protocol v1.5 的 `audit_chunk`、同 invocation 恢复账本、持久化 `agent_run_audit` 与授权后的管理 Job 详情；普通 Runtime 事件和 terminal 只保存不含正文的分块结构与安全 provenance，MCP 边界不得创建专用 Token。

#### Scenario: Runtime 传输完整调用审计
- **WHEN** Runtime v1.5 为当前 invocation 生成完整调用审计
- **THEN** 完整正文只通过可验证 `audit_chunk` 和同 invocation 恢复账本传输
- **AND** 普通 Runtime 日志、归一化事件、terminal、RabbitMQ 和 Job 快照不包含正文
- **AND** Credential、认证 Header、Cookie 和 private thinking 在审计正文中仍被排除

### Requirement: 运行记录查询和页面必须受授权且默认安全
受授权的运行记录列表和 Job 详情 MUST 展示系统人员显示名称与用户名、业务应用名称与编码、Agent、执行与投递状态、统计可用性、总耗时、API 总耗时、模型轮次、四类 Token、估算成本、工具安全摘要和失败位置。显示名称仅用于受权页面投影，MUST NOT 取代稳定用户或应用标识参与授权。运行记录页默认 MUST 只提供开始时间、结束时间、用户名和应用名四个查询条件；用户名查询 MUST 在用户名与显示名称中匹配，应用名查询 MUST 在应用名称与应用编码中匹配。查询 MUST 复用当前登录、业务应用运维权限和平台管理员授权，并 MUST 对租户与应用范围执行服务端过滤。列表、搜索、Debug evidence、Tool/MCP 主账、普通日志和事件 MUST NOT 保存或返回完整 Prompt、完整模型回复、原始 SDK 消息或 Provider/MCP 原始业务载荷；Runtime v1.5 `agent_run_audit` 是唯一例外，且完整正文必须在 Job 详情完成 `jobs.read` 和业务范围检查后才读取和返回。所有路径 MUST NOT 保存或返回 private thinking、Secret、Token、密码、Cookie、认证 Header 或数据库凭据。

#### Scenario: 授权用户查看完整 Job invocation
- **WHEN** 当前用户具备 `jobs.read` 且目标 Job 命中其业务范围
- **THEN** 服务端先完成授权和范围过滤，再读取并返回 `agent_run_audit` 完整正文
- **AND** 列表查询、范围外查询、Debug evidence 和 Tool/MCP 查询不读取或返回该正文

#### Scenario: 错误和模型消息包含敏感内容
- **WHEN** SDK 错误、模型响应或工具载荷包含认证材料、原始业务正文或 private thinking
- **THEN** 普通运行记录、错误字段、Debug evidence 和 Tool/MCP 主账仅保留稳定分类和有界脱敏摘要
- **AND** 原始业务正文只可进入 `agent_run_audit` 并在授权后的 Job 详情返回
- **AND** 认证材料和 private thinking 不进入 `agent_run_audit` 或页面

### Requirement: Agent Job 运行审计必须保持执行事实与完整上下文快照的边界
系统 SHALL 继续以 `agent_job_execution_summary`、`agent_model_call`、`agent_tool_call`、`mcp_operation_audit` 和 Delivery 事实分别承担可筛选执行、模型轮次、安全工具、MCP 与投递主账，并 MUST 为 Runtime protocol v1.5 的每个 invocation 保存一份完整上下文/runtime I/O 快照。完整快照不得替代或反向修改这些主账；相同 invocation 的恢复重放必须幂等。

#### Scenario: Agent 成功而 Delivery 失败
- **WHEN** Runtime invocation 成功并保存完整审计，但后续 Delivery 失败
- **THEN** 执行审计保持成功，Delivery 独立显示失败

#### Scenario: Job retry
- **WHEN** 同一 Job 产生多个 invocation
- **THEN** 每个 invocation 独立保存完整审计，Job 执行汇总继续按唯一 terminal 重算
