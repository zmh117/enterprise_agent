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

### Requirement: 调优摘要必须区分实际 usage 和构成估算
系统 SHALL 保存每轮/Result usage、请求次数、峰值上下文、Token/cache/cost、注册工具、单次最大加载工具、无需确认工具、调用次数和不同工具数。`allowed_tools` 仅计入无需确认工具，不得冒充注册或加载工具总数。峰值上下文按 `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` 计算；字符估算 MUST 标明估算方法，不得冒充 Provider 计费事实。

#### Scenario: 多轮 Tool Loop
- **WHEN** 一个 invocation 产生多次模型 request 和重复工具调用
- **THEN** 页面分别展示请求次数、峰值上下文、累计 usage、注册/加载/调用/不同工具口径

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

#### Scenario: 历史 Job
- **WHEN** Job 创建于完整审计启用前
- **THEN** 页面说明审计不可用，不按当前配置回填历史上下文
