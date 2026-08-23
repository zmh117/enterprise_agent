## ADDED Requirements

### Requirement: 固定 MCP Server 必须声明唯一鉴权模式
系统 SHALL 在代码拥有的固定MCP Server策略中为每个可部署Server声明恰好一个鉴权模式：`tool-mcp`使用`job-context`，普通业务MCP使用`business-principal-jwt`，`file-service`使用`file-principal-jwt`。Tool Manifest中的每个`server_code` MUST解析到该固定策略，且请求、数据库、Agent、Application、用户或模型不得创建、覆盖或动态选择Server鉴权模式。

#### Scenario: 发布固定业务 MCP Tool
- **WHEN** 代码Manifest新增属于部署固定业务MCP的Tool
- **THEN** 该Server必须显式声明`business-principal-jwt`后才可通过启动、发布和Job快照校验

#### Scenario: 新 Server 未声明鉴权模式
- **WHEN** Tool Manifest引用未知Server或Server没有唯一固定鉴权策略
- **THEN** 启动、发布或Job快照创建失败关闭且不得使用默认鉴权模式

#### Scenario: 请求尝试覆盖鉴权模式
- **WHEN** Runtime请求、Tool参数或模型输出提供auth mode、Server URL、Header或Token
- **THEN** 协议或服务端在连接MCP前拒绝且不持久化这些值

### Requirement: 业务 MCP 只接受自身 audience 的平台 Principal
每个`business-principal-jwt` Server SHALL 只接受平台统一Principal信任根签发、`aud`等于自身固定`server_code`且scope与当前Job对该Server冻结Tool集合完全一致的短时JWT。业务MCP MUST 在访问Provider Credential或上游系统前复核RUNNING Job、内部用户、Session、两个Publication、Tool/schema、authorization hash和当前调用Tool scope，并 MUST 拒绝其它Server、File或Service Principal。

#### Scenario: 同一 Job 调用两个业务 MCP
- **WHEN** Runtime分别携带`aud=ones-mcp`和另一固定业务Server audience的两个JWT调用各自冻结Tool
- **THEN** 每个Server只验证并使用自身JWT，两个调用共享Job provenance但不共享Bearer Token或scope

#### Scenario: 业务 token 被跨 Server 复用
- **WHEN** Runtime把一个业务Server的JWT作为另一个Server的Authorization
- **THEN** 接收Server因audience不匹配而在Provider Credential解析和上游连接前拒绝

#### Scenario: 业务 MCP 收到 File Principal
- **WHEN** 业务MCP收到`aud=file-service`或包含文件工作区claims的Principal
- **THEN** 服务拒绝且不得尝试把File scope解释为业务Tool scope

#### Scenario: 业务调用审计
- **WHEN** 业务MCP Tool调用成功或失败
- **THEN** 统一MCP Operation Audit记录Server、Job、主体、Publication、Tool/schema、授权判定、correlation、状态、耗时和有界摘要
- **AND** 审计不得记录Principal JWT、Provider Credential、完整Prompt或无界上游响应

## MODIFIED Requirements

### Requirement: Python Runtime只使用固定标准MCP Tool Server
系统 SHALL 由部署固定的`tool-mcp`使用官方MCP SDK向Python Runtime提供现有只读资源Tool，由部署固定且代码声明为`business-principal-jwt`的业务MCP提供经发布和Job冻结的业务Tool，并由部署固定的`file-service` File MCP接口提供任务文件工具。Runtime MUST只连接Job与Publication冻结且部署注册的私网Server地址，不得接受Agent、Application、用户或模型提供MCP Server URL、鉴权模式或凭据。各Server MUST使用代码拥有的稳定Tool identifier，不得互相代理、回退或复用其它Server的身份令牌。

#### Scenario: Python Runtime调用只读资源工具
- **WHEN** Python Runtime执行冻结了合法只读资源Tool的Job
- **THEN** Runtime通过`tool-mcp`使用冻结schema和受治理执行语义且不携带Authorization

#### Scenario: Python Runtime调用业务 MCP 工具
- **WHEN** Python Runtime执行冻结了合法业务MCP Tool的Job
- **THEN** Runtime只连接该Tool代码固定的业务Server并携带audience匹配的业务Principal JWT

#### Scenario: Python Runtime调用文件工具
- **WHEN** Python Runtime执行冻结了合法File Tool的Job
- **THEN** Runtime通过`file-service`使用冻结schema、独立File Principal JWT和任务工作区边界

#### Scenario: payload提供自定义Server
- **WHEN** 请求或模型输出包含自定义MCP URL、Server code、鉴权模式、Header、Token或transport
- **THEN** Runtime和对应MCP服务必须在连接或调用前拒绝

### Requirement: MCP 调用必须绑定有效 Job
每个MCP调用 MUST绑定有效RUNNING Job和Job冻结的精确Tool/schema hash。`tool-mcp`继续接受非敏感Job标识并重新读取Job；业务MCP MUST从自身audience匹配的已验证Principal JWT解析Job和主体，并重新读取用户、Session、Publication、authorization hash和scope；File Service MUST从独立File Principal JWT解析Job并重新读取用户、Session、Publication、Workspace和scope。任一Server均 MUST在Provider Credential解析、上游连接、文件元数据读取或对象操作前拒绝不存在、非RUNNING、Runtime/protocol不合法、Tool未冻结、scope不匹配或schema漂移的调用。

#### Scenario: 合法 Job 调用冻结只读资源工具
- **WHEN** RUNNING Job调用其冻结的精确只读资源Tool
- **THEN** `tool-mcp`进入资源、权限和只读策略校验

#### Scenario: 合法 Job 调用冻结业务工具
- **WHEN** RUNNING Job以audience和scope匹配的业务Principal调用其冻结的精确业务Tool
- **THEN** 业务MCP进入Provider身份、业务权限和上游调用校验

#### Scenario: 合法 Job 调用冻结文件工具
- **WHEN** RUNNING Job以有效File Principal调用其冻结的精确File Tool
- **THEN** File Service进入任务工作区、文件和操作授权校验

#### Scenario: Job、Principal 或 Tool 不匹配
- **WHEN** Job不存在、非RUNNING、Principal audience或scope不匹配、Tool未冻结或schema hash漂移
- **THEN** 调用在解析Provider Credential、连接上游或读取文件内容前失败关闭

### Requirement: MCP Transport 不新增认证和治理层
现有`tool-mcp` MUST不签发或验证Bearer Token/JWT，不挂载Runtime Grant、不拥有signing key，也不新增MCP专用RBAC、授权表或Resource Mapping；携带Authorization的`tool-mcp`请求继续拒绝。业务MCP和File MCP MUST复用平台统一Principal签名信任根、Job、角色、Business Application和Tool授权事实，不得自建用户、角色、JWT issuer、凭据表或替代授权模型；业务MCP使用按自身Server隔离的业务Principal，File MCP继续使用独立File Principal。

#### Scenario: Runtime 调用只读 MCP
- **WHEN** Runtime向`tool-mcp`发起工具调用
- **THEN** 请求不包含Runtime Grant、模型Key、Internal API Token、Principal JWT或MCP access token

#### Scenario: tool-mcp 请求携带 Authorization
- **WHEN** `tool-mcp` HTTP请求携带Authorization header
- **THEN** 服务拒绝该请求以维持现有非认证传输边界

#### Scenario: Runtime 调用业务 MCP
- **WHEN** Runtime向固定业务MCP发起冻结Tool调用
- **THEN** 请求只携带该Server audience的短时平台Principal JWT并由业务MCP复核现有统一授权事实
- **AND** 业务MCP不创建独立RBAC或签发平台Principal

#### Scenario: Runtime 调用 File MCP
- **WHEN** Runtime向File Service发起文件工具调用
- **THEN** 请求只携带独立File Principal JWT并由File Service复核现有统一授权和工作区事实
- **AND** File Service不创建独立RBAC或签发Token
