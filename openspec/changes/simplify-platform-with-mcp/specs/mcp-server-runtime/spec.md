## ADDED Requirements

### Requirement: 领域 MCP Server 必须独立部署并固定官方 SDK 版本
系统 MUST 将 `ones-mcp-server` 和 `data-mcp-server` 作为独立服务部署，并 MUST 在各自依赖环境中固定提案日期的最新稳定官方 MCP Python SDK `mcp==2.0.0`；Agent Worker MUST 保持 Claude Agent SDK 兼容的 MCP 1.x 依赖，禁止在同一环境强行解析不兼容主版本。

#### Scenario: 构建独立 MCP 镜像
- **WHEN** 构建 Agent Worker、ONES MCP 和 Data MCP 镜像
- **THEN** 两个 MCP 镜像安装 `mcp==2.0.0`，Agent Worker 继续满足 `claude-agent-sdk` 的 `mcp<2.0.0` 约束，三个镜像均能独立启动

#### Scenario: 旧协议客户端连接 v2 Server
- **WHEN** 当前 Claude Agent SDK MCP 客户端通过 Streamable HTTP 连接 v2 Server
- **THEN** Server 使用官方兼容能力完成协议协商并提供相同的受控 Tool 契约，不要求替换 Agent Loop

### Requirement: Agent 只能连接显式允许的 MCP Server 与 Tool
Agent Runtime MUST 从当前 Job 的精确运行绑定构造 Server 列表和 Tool allowlist，MUST NOT 自动发现、注册或批准平台内全部 MCP Server 和 Tool；Bash、Write、Edit、WebFetch、WebSearch、Shell、脚本和未声明 Tool MUST 保持不可用。

#### Scenario: Job 只允许 ONES 查询
- **WHEN** Job 的运行绑定只包含 ONES MCP 工作项搜索 Tool
- **THEN** Agent 只能看到和调用该精确 Tool，Data MCP Tool 和其他 ONES Tool 不进入模型目录

#### Scenario: 模型尝试调用未授权 Tool
- **WHEN** 模型构造未在当前 allowlist 中的 MCP Tool 名称
- **THEN** Runtime 和 MCP Server 均拒绝调用，且拒绝不会触发上游请求

### Requirement: MCP Server 必须验证平台短期访问令牌
每个远程 MCP 请求 MUST 使用平台签发的短期访问令牌；Server MUST 验证签名、issuer、audience、subject、authorized party、Job、scope、expiry 和 token ID，并 MUST 拒绝错误 audience、过期、撤销或超出 scope 的令牌。

#### Scenario: ONES Token 被错误当作 MCP Token
- **WHEN** 客户端把下游 ONES Token 作为 ONES MCP Bearer Token
- **THEN** ONES MCP 因 issuer、audience 或签名不匹配拒绝请求，且不尝试 Token passthrough

#### Scenario: Job 执行窗口结束
- **WHEN** MCP Token 已过期或关联 Job 已进入不可执行终态
- **THEN** Server 拒绝新的 Tool Call并记录安全认证错误，不使用缓存身份继续执行

### Requirement: 身份、权限和连接依赖必须对模型不可见
MCP Server MUST 通过鉴权层和 SDK `Resolve` 依赖注入 `PrincipalContext`、`JobContext`、Provider Client 与 Resource Context；这些参数 MUST 不出现在 Tool Schema，客户端提交的同名字段 MUST 被忽略或拒绝，HTTP Header MUST NOT 被直接当作业务身份。

#### Scenario: 模型提交伪造主体和 Team
- **WHEN** Tool 参数包含 `user_id`、`team_id`、`resource_revision_id` 或 `credential_ref`
- **THEN** Server 不使用这些值，并只使用鉴权层和冻结 Job 事实解析出的隐藏依赖

#### Scenario: 客户端伪造身份 Header
- **WHEN** 请求携带未经鉴权层签名验证的用户 Header
- **THEN** Server 不以该 Header 建立 Principal，调用失败关闭

### Requirement: MCP Tool 必须由代码定义并保持只读有界
MCP Tool 的名称、描述、输入输出 Schema、只读语义、结果大小、超时、允许的 Provider 操作和错误分类 MUST 由 Server 代码拥有；系统 MUST NOT 从数据库或管理输入生成任意 HTTP、SQL、LogQL、Redis 命令、脚本、Shell 或模板执行器。

#### Scenario: 管理配置尝试新增任意 SQL Tool
- **WHEN** YAML、CLI 或数据库记录尝试定义模型可见 SQL 文本或新 Tool Schema
- **THEN** Server 拒绝或忽略该配置，且 `tools/list` 不出现该 Tool

#### Scenario: 上游返回超大结果
- **WHEN** ONES、数据库、Redis 或 Loki 响应超过 Tool 的条数或字节上限
- **THEN** Server 停止读取或安全截断并返回明确元数据，原始超大响应不得进入模型、日志或数据库

### Requirement: MCP Server 必须提供安全健康与调用 Provenance
每个 Server MUST 暴露不执行真实业务查询的健康检查，并 MUST 为每次 Tool Call 记录 Server Code/Version、Tool Name/Schema Hash、Job、主体快照、资源 Revision或凭据 Revision、状态、耗时、结果 Hash/大小和关联 ID；记录 MUST NOT 包含认证 Header、Secret Ref、连接地址、密码、Token 或原始 Provider 响应。

#### Scenario: 查询 MCP Tool Call 历史
- **WHEN** 授权用户查看一次成功或失败的 MCP Tool Call
- **THEN** 系统返回可关联的安全 Provenance 和结果摘要，不返回可重放请求或认证材料

#### Scenario: 健康检查在 Provider 不可用时执行
- **WHEN** 运维系统调用 Server 健康端点且业务 Provider 暂时不可达
- **THEN** 健康响应区分进程、配置与依赖状态，但不发起不受控业务查询或泄露连接信息
