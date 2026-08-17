## ADDED Requirements

### Requirement: Runtime 按 MCP Server 隔离业务 Principal Secret
Control Plane SHALL根据当前Job已经验证并冻结的MCP bindings，为每个鉴权模式为`business-principal-jwt`的`server_code`调用一次统一业务签发器，并以`mcp_principal_tokens[server_code]`语义向Python Runtime传递恰好一个对应JWT。业务Principal MUST通过逐Server的受限Secret Header传递，不得进入Runtime请求JSON、request digest、Runtime Grant、Job payload、Invocation/terminal ledger、事件、日志、错误、审计payload或模型上下文；File Principal MUST继续通过独立Secret槽位和Header传递。

#### Scenario: 一个 Job 同时调用 ONES 和第二业务 MCP
- **WHEN** Job冻结的Runtime bindings同时包含`ones-mcp`和另一个代码固定业务MCP
- **THEN** Control Plane分别签发两个audience不同的JWT并以两个Server code键传给Runtime
- **AND** Runtime请求正文、摘要和持久化账本中不出现任一Token或Token映射

#### Scenario: 业务 Server 缺少对应 token
- **WHEN** Runtime请求包含某个业务MCP binding但Secret Header集合缺少该Server的token
- **THEN** Runtime在调用模型或连接任何MCP前以稳定不可重试身份错误失败

#### Scenario: 出现额外或未知 token
- **WHEN** Secret Header包含未出现在当前请求bindings中的Server、未知Server、重复Server、非法Header-safe名称、超长值或CR/LF
- **THEN** Runtime在读取或持久化Invocation状态之外的业务Secret前拒绝整个请求
- **AND** 错误和审计不得回显Header或Token值

#### Scenario: File token 与业务 token 同时存在
- **WHEN** Job同时冻结业务MCP Tool和File Tool
- **THEN** Runtime分别构建`mcp_principal_tokens`和`file_principal_token`
- **AND** 任何一侧缺失时不得从另一侧fallback

#### Scenario: Secret 安全投影
- **WHEN** Runtime Secret Context被repr、记录异常、生成事件或进入诊断投影
- **THEN** 输出只表明受保护凭据存在或被隐藏，不包含Server对应JWT原文

### Requirement: Python Runtime 按冻结 binding 精确选择业务 Principal
Python Runtime SHALL只针对已通过Runtime协议验证且代码固定的业务MCP binding，从`mcp_principal_tokens`按完全相同的`server_code`取Bearer Token，并为每个SDK MCP Server创建独立Header集合。Runtime MUST拒绝缺失、空值、额外或跨Servertoken，不得尝试单一默认`principal_token`、首个token、File Principal或其它Server token；`tool-mcp`继续不携带Authorization，`file-service`继续走进程内File bridge和独立File Principal。

#### Scenario: 两个业务 MCP 并发调用
- **WHEN** 模型在同一Invocation中并发调用两个已冻结业务MCP Server的Tool
- **THEN** 每个SDK MCP连接只携带自身Server code对应的Bearer Token
- **AND** Tool事件、结果和审计继续按各自Server、Tool、call id和Job关联

#### Scenario: ONES token 被错误放入另一 Server 键
- **WHEN** 映射键是第二业务Server但JWT audience实际为`ones-mcp`
- **THEN** 第二业务MCP的固定audience验证失败且Runtime不得使用ONES连接作为fallback

#### Scenario: 模型尝试提供 token 或 Server 地址
- **WHEN** Prompt、Tool参数或模型输出包含Principal Token、Authorization、Server URL或自定义MCP配置
- **THEN** Runtime工具策略和固定MCP装配拒绝这些字段且不改变Secret Context

#### Scenario: File bridge 行为保持不变
- **WHEN** Job执行冻结的File Tool
- **THEN** Python Runtime继续使用独立File Principal、当前Job Sandbox和进程内File MCP bridge
- **AND** 业务Principal映射不进入文件传输上下文

## MODIFIED Requirements

### Requirement: Read-only tools are exposed only through the deployment-fixed standard MCP server
系统 SHALL让独立Python Runtime通过部署固定的标准`tool-mcp`访问Job冻结的只读资源MCP Tool，通过部署固定且代码声明为`business-principal-jwt`的业务MCP访问经发布和Job冻结的业务Tool，并通过部署固定的`file-service` File MCP接口访问Job冻结的任务文件工具。Runtime MUST NOT注册旧Capability Tool、接受任意Server URL或鉴权模式、在Tool不可用时fallback、跨业务Server复用Principal，或把文件工具路由到`tool-mcp`。`tool-mcp`继续使用非认证Job绑定传输；业务MCP MUST使用audience和Server匹配的平台短时Principal JWT并复核主体、Job、Publication、authorization hash和scope；File MCP MUST使用独立平台短时File Principal JWT并复核主体、Job、Publication、scope和任务工作区。

#### Scenario: Python Runtime调用允许的只读资源Tool
- **WHEN** Python SDK调用Job精确允许的只读资源MCP Tool
- **THEN** 调用通过标准MCP SDK进入部署固定`tool-mcp`并返回安全结果
- **AND** 请求不携带Authorization

#### Scenario: Python Runtime调用允许的业务Tool
- **WHEN** Python SDK调用Job精确允许的业务MCP Tool
- **THEN** 调用只进入该Tool代码固定的业务Server且携带该Server audience的Principal JWT

#### Scenario: Python Runtime调用允许的文件Tool
- **WHEN** Python SDK调用Job精确允许的File MCP Tool
- **THEN** 调用只进入部署固定`file-service`且携带不含下游Secret的独立File Principal JWT

#### Scenario: Tool上下文按Job和Server隔离
- **WHEN** Python Runtime并发执行两个调用相同或不同MCP Tool的Job
- **THEN** 每次调用使用各自Job、Publication、Server和scope且不共享业务Principal、模型凭据或MinIO凭据

#### Scenario: 模型提供任意MCP地址或凭据
- **WHEN** 请求内容或模型输出尝试注册未冻结MCP Server URL、鉴权模式、Header、Token或Tool
- **THEN** Runtime与服务端失败关闭

#### Scenario: 旧平台对象被配置
- **WHEN** 启动或执行配置包含旧Capability、Handler、Resource Mapping、Internal API Token、`RUNTIME_TOOL_MCP_*`或HS256 signing key
- **THEN** 部署预检失败且不启动兼容模式
