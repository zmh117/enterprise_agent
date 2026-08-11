## MODIFIED Requirements

### Requirement: Read-only tools are exposed only through the deployment-fixed standard MCP server
系统 SHALL 让两个独立 Runtime 通过固定标准 `tool-mcp` 服务访问 Job 冻结的只读 MCP Tool。Runtime MUST NOT 注册旧 Capability Tool、接受任意 Server URL、发送 Runtime Grant/Internal API Token 或在 Tool 不可用时 fallback。MCP transport 不新增 Token、签名、RBAC 或治理层；业务权限与只读边界继续由 Job 和 Tool 实现复核。

#### Scenario: Python Runtime调用允许Tool
- **WHEN** Python SDK 调用 Job 精确允许的 MCP Tool
- **THEN** 调用通过标准 MCP SDK 进入直接工具实现并返回安全结果

#### Scenario: TypeScript Runtime调用允许Tool
- **WHEN** TypeScript SDK 调用 Job 精确允许的 MCP Tool
- **THEN** 调用通过同一服务进入等价直接工具实现

#### Scenario: Tool上下文按Job隔离
- **WHEN** 两个 Runtime 并发调用相同 Tool
- **THEN** 每次调用使用各自 Job/Publication/目标上下文且不共享模型凭据或可变全局上下文

#### Scenario: 模型提供任意MCP地址
- **WHEN** 请求内容或模型输出尝试注册未冻结 MCP Server URL 或 Tool
- **THEN** Runtime 与服务端失败关闭

#### Scenario: 旧平台对象被配置
- **WHEN** 启动或执行配置包含旧 Capability、Handler、Resource Mapping、Internal API Token、`RUNTIME_TOOL_MCP_*` 或 HS256 signing key
- **THEN** 部署预检失败且不启动兼容模式

### Requirement: Built-in mutating tools are disabled
系统 SHALL 禁止 SDK 的 Bash、Write、Edit、NotebookEdit、WebFetch、WebSearch、Shell、文件修改、部署或其它开放执行工具。系统 MUST 只自动批准当前 Job 冻结且满足角色、应用、数据范围与唯一资源解析的 MCP 只读 Tool，不再注册 `cap__*` Capability Tool。

#### Scenario: Model attempts a built-in write tool
- **WHEN** SDK 尝试调用 Bash、Write 或 Edit
- **THEN** 该工具不可用或调用被拒绝

#### Scenario: Only current MCP set is auto-approved
- **WHEN** Application Publication 只选择一个 MCP Tool
- **THEN** 只有该 Tool 可进入 allowedTools/自动批准集合

#### Scenario: Application has no Tool
- **WHEN** Application MCP Tool 子集为空
- **THEN** 不注册或批准任何平台 Tool
