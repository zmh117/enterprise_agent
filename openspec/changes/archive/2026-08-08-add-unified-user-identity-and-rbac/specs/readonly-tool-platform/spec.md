## MODIFIED Requirements

### Requirement: Tool definitions are persisted
The system SHALL persist tool definitions, connector configuration metadata, data source registry entries, enablement status, Agent publication assignments, and user/role permission relationships needed for web-based configuration. Runtime availability MUST be the intersection of code-registered read-only tools, enabled persisted definitions, the job's Agent publication assignment, user/role permission, and platform data scope.

#### Scenario: Tool registry is loaded
- **WHEN** the Agent runtime prepares available tools for a job
- **THEN** it loads the fixed Agent publication assignments and enabled PostgreSQL-backed tool definitions, then filters them through the internal user's effective permissions and data scope

#### Scenario: Administrator assigns existing tool
- **WHEN** an authorized administrator assigns an existing enabled read-only tool to the default diagnostic Agent draft and publishes it
- **THEN** new authorized jobs may expose the tool while older jobs retain their fixed publication

#### Scenario: Administrator attempts to assign unregistered tool
- **WHEN** a draft references a tool code that is not code registered, is disabled, or is not read-only
- **THEN** publication validation rejects the assignment

## ADDED Requirements

### Requirement: 第一版 Web 不动态创建 executable tools
系统 SHALL 允许管理端查看、启停和分配已有只读工具，但 MUST NOT 在本 change 中通过 Web 创建任意 HTTP、MCP、Shell、代码或 SQL executable adapter。

#### Scenario: 管理员打开工具分配页
- **WHEN** 管理员编辑默认诊断 Agent 的工具集合
- **THEN** 页面只列出系统已注册且可分配的只读工具

#### Scenario: 请求提交任意 HTTP 工具定义
- **WHEN** 客户端尝试通过本 change 的管理 API 创建新的动态 HTTP API 工具
- **THEN** 系统拒绝或不存在该能力，并要求使用后续专门的工具定义 change
