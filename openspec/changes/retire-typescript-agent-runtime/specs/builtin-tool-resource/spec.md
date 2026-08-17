## MODIFIED Requirements

### Requirement: Real-tools 必须通过标准 MCP Tool Runtime 执行
真实工具验收 SHALL 启动 PostgreSQL、RabbitMQ、`tool-mcp`、`python-agent-runtime`、Worker 与所需工具资源；MUST NOT 启动 TypeScript Agent Runtime、Internal API Platform 或配置 `INTERNAL_API_*`。

#### Scenario: 真实数据库工具链
- **WHEN** Python Agent Job 对已授权目标调用数据库只读 Tool
- **THEN** 请求沿 `python-agent-runtime -> tool-mcp -> Resource` 完成并记录精确审计

## ADDED Requirements

### Requirement: Python Runtime只使用固定标准MCP Tool Server
系统 SHALL 由部署固定的 `tool-mcp` 使用官方 MCP SDK 向 Python Runtime 提供现有只读工具，并由部署固定的 `file-service` File MCP 接口提供任务文件工具。Runtime MUST 只连接 Job 与 Publication 冻结且部署注册的私网 Server 地址，不得接受 Agent、Application、用户或模型提供 MCP Server URL。两个 Server MUST 使用代码拥有的稳定 Tool identifier，不得互相代理或回退。

#### Scenario: Python Runtime调用只读工具
- **WHEN** Python Runtime 执行冻结了合法只读 Tool 的 Job
- **THEN** Runtime 通过 `tool-mcp` 使用冻结 schema 和受治理执行语义

#### Scenario: Python Runtime调用文件工具
- **WHEN** Python Runtime 执行冻结了合法 File Tool 的 Job
- **THEN** Runtime 通过 `file-service` 使用冻结 schema、Principal JWT 和任务工作区边界

#### Scenario: payload提供自定义Server
- **WHEN** 请求或模型输出包含自定义 MCP URL、Server code 或 transport
- **THEN** Runtime 和对应 MCP 服务必须在连接或调用前拒绝

## REMOVED Requirements

### Requirement: 双 Runtime 只使用固定标准 MCP Tool Server
**Reason**: TypeScript Agent Runtime 被退役后，不再需要跨语言 Runtime 等价性合同；固定 Server、精确 Tool 和失败关闭边界仍由 Python 单 Runtime 要求继承。

**Migration**: 使用新增的“Python Runtime只使用固定标准MCP Tool Server”要求，并删除 TypeScript parity fixture、配置和验收入口。
