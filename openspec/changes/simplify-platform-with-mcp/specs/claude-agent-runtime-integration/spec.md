## ADDED Requirements

### Requirement: 只读工具只能通过显式允许的领域 MCP Server 暴露
系统 SHALL 仅通过当前 Job 精确绑定的远程 ONES MCP 与 Data MCP Server 暴露代码定义的只读 Tool；Runtime MUST 为每个 Job 构造精确 Server 列表、Tool allowlist 和平台短期 MCP Token，且 MUST NOT 把旧 Capability Runtime、任意 URL 或模型提供的身份参数作为调用路径。

#### Scenario: 模型调用 ONES MCP Tool
- **WHEN** 当前 Job 只绑定已发布的 ONES 工作项搜索 Tool
- **THEN** Runtime 通过固定 ONES MCP Server 执行该 Tool，并使用当前 Job 的主体快照且不暴露个人 ONES Token

#### Scenario: 两个 Job 并发执行
- **WHEN** 两个不同主体的 Job 同时连接同一 MCP Server
- **THEN** 每个请求使用独立的短期令牌、Job 上下文和 allowlist，主体、资源与结果不得跨 Job 泄露

### Requirement: 模型可以组合允许的 MCP Tool 输入输出
Claude Tool 循环 SHALL 能读取一个允许 MCP Tool 的结构化公开输出，并依据后续允许 Tool 的公开 Input Schema 组织新调用；每次调用 MUST 独立经过当前 Job 的 Runtime allowlist 与 MCP Server scope 校验，系统 MUST NOT 创建隐式服务端通用执行流水线。

#### Scenario: 顺序调用两个允许 Tool
- **WHEN** 模型使用第一个 MCP Tool 的规范化字段构造第二个 Tool 输入
- **THEN** SDK 循环执行两个独立调用并分别产生安全 MCP Tool 事件

#### Scenario: 后续 Tool 不在当前目录
- **WHEN** 模型尝试根据文本调用未注册的 MCP Tool
- **THEN** Runtime 和 Server 均拒绝调用且不发起上游请求

### Requirement: 不可用 MCP Tool 使用独立安全提示通道
Runtime MUST 将 MCP Tool 调用资格与模型解释事实分离：不满足当前主体、凭据或资源前置条件的 Tool MUST 保持未注册、未批准；仅当该 Tool 属于当前 Job 精确发布交集时，Runtime MAY 使用固定白名单文案说明不可用状态。提示 MUST NOT 包含用户标识、Team、Resource、Credential、Server 地址或认证材料，也不得成为可调用 Tool。

#### Scenario: 当前主体缺少 ONES 新凭据
- **WHEN** 当前 Job 的发布允许 ONES Tool，但用户尚未在切换后重新验证
- **THEN** Runtime 只提示用户前往本人身份页重新验证，且 ONES Tool 不进入 allowlist

#### Scenario: 安全提示不扩大权限
- **WHEN** 模型收到某 Tool 的 unavailable 提示
- **THEN** 该 Tool 仍不进入 MCP Server 列表、allowed_tools 或自动批准集合

## MODIFIED Requirements

### Requirement: Built-in mutating tools are disabled
The system SHALL prevent the SDK's built-in mutating tools such as Bash, Write, Edit, file modification, deployment, arbitrary web access, scripts, or Shell from being available or approved. The system SHALL auto-approve only the exact code-defined MCP tools resolved for the current Job's immutable publication and deployment bindings; it SHALL deny all other tools through `allowed_tools`, `disallowed_tools`, `permission_mode`, `can_use_tool`, and server-side scope checks.

#### Scenario: Model attempts a built-in write tool
- **WHEN** the SDK runtime would otherwise allow a built-in Bash, Write, or Edit tool
- **THEN** the tool is not available or its call is denied, so no mutation can occur

#### Scenario: Only the current MCP set is auto-approved
- **WHEN** the Job binding includes one ONES MCP Tool and no Data MCP Tool
- **THEN** only that exact ONES Tool is approved, while other MCP Tool names and generic web access remain denied

#### Scenario: Job has no eligible MCP Tool
- **WHEN** the publication permits a Tool but current identity, credential, or resource checks fail
- **THEN** no corresponding Tool is registered or auto-approved

### Requirement: 外部规范化文本不得提升为指令
运行时 MUST 将 ONES、数据库、Redis 和 Loki 的 MCP Tool 字符串输出标记和封装为不可信业务数据，不得把它拼接进 system/developer/Tool 定义，也不得据此修改 MCP Server 列表、`allowed_tools`、scope 或权限策略。

#### Scenario: MCP Tool 输出包含提示注入
- **WHEN** 外部字段内容声称自己是系统指令或要求调用被禁用 Tool
- **THEN** 内容保持普通 Tool 数据，系统提示、Tool 集合和权限不发生变化

## REMOVED Requirements

### Requirement: Read-only tools are exposed only through an in-process SDK MCP server
**Reason**: 进程内 SDK MCP 与旧 Capability/Internal Platform 运行时一并退役，由独立部署的领域 MCP Server 取代。

**Migration**: 不保留兼容入口；新 Job 只能使用精确绑定的 ONES MCP 或 Data MCP Tool。

### Requirement: 模型可以组合公开的 Capability 输入输出
**Reason**: 通用 API Capability 目录与执行管线被彻底删除。

**Migration**: 不迁移旧 Capability 定义或运行数据；需要的只读语义由代码定义 MCP Tool 重新实现。

### Requirement: 不可用 Capability 使用独立安全提示通道
**Reason**: Capability 不再是运行时对象，不应继续出现在提示或允许集合语义中。

**Migration**: 使用本变更新增的不可用 MCP Tool 安全提示契约，无旧数据转换。
