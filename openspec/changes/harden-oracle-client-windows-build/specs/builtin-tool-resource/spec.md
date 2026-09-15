## MODIFIED Requirements

### Requirement: tool-mcp image bundles Oracle Instant Client
若平台支持 Oracle thick/legacy 连接，系统 SHALL 仅在 `tool-mcp` 镜像中安装匹配架构的 Oracle Instant Client，并由 Oracle Resource Revision 的固定 Provider 契约选择 thick/legacy 模式；API、Worker 和 Agent Runtime 镜像 MUST NOT 包含该客户端。构建链路 MUST 兼容 Windows CRLF 的 Oracle 安装与检测脚本，且 MUST 区分正常缺少客户端与检测执行失败；后者必须终止构建，不得伪装成无客户端的成功镜像。

#### Scenario: 构建 tool-mcp Oracle 镜像
- **WHEN** vendor 目录提供受支持的 Oracle Instant Client
- **THEN** `tool-mcp` 可以初始化 thick client，Worker/API/Runtime 镜像不包含该客户端

#### Scenario: 未提供 thick client
- **WHEN** Oracle Resource 要求 thick 模式但镜像没有客户端
- **THEN** 资源验证和 Tool Call 失败关闭且不回退到不兼容模式

#### Scenario: Windows CRLF 脚本构建
- **WHEN** 构建上下文内 Oracle 安装或 Python 检测脚本为 CRLF，且提供匹配架构的合规 64-bit 19c 客户端
- **THEN** 构建在执行前处理行尾并显式调用解释器，完成客户端安装及校验，不依赖 Python 脚本的 shebang 或可执行位

#### Scenario: ZIP 不含合规客户端
- **WHEN** 未提供客户端或提供的合法 ZIP 不含 19c 库成员
- **THEN** 构建可以保留 Oracle 不可用状态而继续支持其他 Provider，不把其他版本当作合规 19c

#### Scenario: 检测失败不得静默忽略
- **WHEN** 检测脚本不能执行、ZIP 损坏或不可读，或检测过程发生其他异常
- **THEN** 构建返回非零状态及明确诊断，不将异常归类为正常缺少客户端

#### Scenario: 发行版 libaio t64 兼容
- **WHEN** 合规 64-bit 19c 客户端需要 `libaio.so.1`，发行版仅提供已安装 `libaio1t64` 中的 `libaio.so.1t64`
- **THEN** 构建 SHALL 在 Oracle 安装目录提供受控兼容链接，不替换系统库或覆盖既有文件，并继续验证真实 Thick 初始化

#### Scenario: 构建时验证真实客户端加载
- **WHEN** 构建已安装合规客户端
- **THEN** 构建 MUST 实际调用 python-oracledb 初始化并确认 Thick 模式及客户端主版本 19；缺失依赖、初始化失败或实际版本不符必须终止构建，该检查不连接数据库也不替代真实服务端验收
