## MODIFIED Requirements

### Requirement: Internal API Platform image bundles Oracle Instant Client
若平台支持 Oracle thick/legacy 连接，系统 SHALL 仅在 `tool-mcp` 镜像中安装匹配架构的 Oracle Instant Client，并由 Oracle Resource Revision 显式选择模式；Internal API Platform 镜像和服务 MUST 不存在。

#### Scenario: 构建 tool-mcp Oracle 镜像
- **WHEN** vendor 目录提供受支持的 Oracle Instant Client
- **THEN** `tool-mcp` 可以初始化 thick client，Worker/API/Runtime 镜像不包含该客户端

#### Scenario: 未提供 thick client
- **WHEN** Oracle Resource 要求 thick 模式但镜像没有客户端
- **THEN** 资源验证和 Tool Call 失败关闭且不回退到不兼容模式

