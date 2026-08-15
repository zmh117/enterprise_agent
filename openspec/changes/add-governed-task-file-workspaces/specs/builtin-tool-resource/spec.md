## ADDED Requirements

### Requirement: File MCP 使用平台短时 Principal JWT
File Service的MCP接口 MUST 只接受平台身份服务签发、TTL不超过300秒且绑定内部用户、租户、RUNNING Job、Session、Agent Publication、Business Application Publication、授权快照和精确File Tool scope的Principal JWT。File Service MUST 使用平台JWKS验证签名、issuer、audience、authorized party、时间、JTI与全部绑定事实，并重新读取当前Job和任务工作区；JWT MUST NOT包含MinIO凭据、对象位置、钉钉凭据或其它下游Secret。

#### Scenario: 合法文件主体调用
- **WHEN** Runtime携带当前RUNNING Job的有效Principal JWT调用已冻结File Tool
- **THEN** File Service验证全部绑定事实并继续文件授权

#### Scenario: JWT与Job不匹配
- **WHEN** JWT的用户、Job、Session、Publication、scope或授权hash与当前事实不一致
- **THEN** File Service在读取文件元数据或MinIO前拒绝

#### Scenario: Agent把凭据放入JWT声明
- **WHEN** Token或请求包含MinIO Access Key、Secret Key、Session Token或对象键
- **THEN** 签发或验证流程拒绝且不记录原值

### Requirement: File MCP 参数不声明平台身份和对象位置
File MCP Tool输入 MUST 使用封闭Schema，只允许必要的文件选择、精确版本、沙盒文件句柄和用户业务意图。模型 MUST NOT声明用户、租户、任务工作区、reply route、Bucket、对象键、上传URL、Credential Reference或MCP Server地址；File Service必须从已验证Principal与Job解析这些事实。

#### Scenario: 模型提交任意对象键
- **WHEN** File Tool参数包含Bucket、对象键或跨工作区File ID
- **THEN** schema或授权校验在对象操作前拒绝

### Requirement: 内部文件调用使用独立短时 Service Principal
平台身份服务 MUST 使用独立于用户/Job Principal 的 Service Principal 签名密钥，为`file-worker`和Delivery Worker按需签发TTL不超过300秒的角色JWT。服务JWT MUST 绑定固定issuer、`aud=file-service-internal`、相同的`sub`/`azp`角色、完整固定scope集合、JTI与时间声明；File Service MUST 使用独立Service JWKS验签并确认当前接口所需scope属于该角色的完整集合。Worker MUST NOT持有服务签名私钥、另一角色bootstrap credential、预生成长期JWT或共享Internal API Token。

#### Scenario: File Worker换取并使用短时JWT
- **WHEN** File Worker以自己的角色bootstrap credential调用平台内部身份接口
- **THEN** 身份服务签发同时包含附件导入和内容清理固定scope、TTL不超过300秒的Service Principal JWT
- **AND** File Worker可在对应两个File Service接口使用该JWT并在到期前刷新

#### Scenario: Delivery凭据被File Worker使用
- **WHEN** File Worker使用Delivery Worker bootstrap credential或Delivery JWT调用附件导入
- **THEN** 平台身份服务或File Service在文件内容操作前拒绝

#### Scenario: Compose使用静态Service JWT文件
- **WHEN** 部署配置要求挂载预先生成且不会持续刷新的Service JWT
- **THEN** 部署契约测试失败且不得宣称服务身份已接线

### Requirement: File MCP 调用审计与统一 MCP Operation Audit 对齐
每次File MCP Tool调用 MUST 记录统一operation、attempt和event链，包含Job、内部用户、Agent/Application Publication、Tool identifier/schema hash、Workspace、File/Version、授权判定、Commit或Delivery关联、状态、耗时及有界摘要。审计 MUST 排除文件正文、完整Prompt、Principal JWT、MinIO或钉钉凭据、对象键和上传授权材料。

#### Scenario: 文件提交发生版本冲突
- **WHEN** File Tool完成暂存但基础版本不再是当前版本
- **THEN** 审计关联同一operation和提交意图并记录安全冲突结果
- **AND** 不保存文件正文或Secret

## MODIFIED Requirements

### Requirement: 双 Runtime 只使用固定标准 MCP Tool Server
系统 SHALL 由部署固定的`tool-mcp`使用官方MCP SDK向Python与TypeScript Runtime提供现有只读工具，并由部署固定的`file-service` File MCP接口提供任务文件工具。Runtime MUST 只连接Job与Publication冻结且部署注册的私网Server地址，不得接受Agent、Application、用户或模型提供MCP Server URL。两个Server MUST 使用代码拥有的稳定Tool identifier和等价跨Runtime语义，不得互相代理或回退。

#### Scenario: 两个 Runtime 调用同一只读工具
- **WHEN** Python与TypeScript Runtime分别执行冻结了同一只读Tool的Job
- **THEN** 两端通过`tool-mcp`使用同一schema和等价执行语义

#### Scenario: 两个 Runtime 调用同一文件工具
- **WHEN** Python与TypeScript Runtime分别执行冻结了同一File Tool的Job
- **THEN** 两端通过`file-service`使用同一schema、Principal JWT契约和等价执行语义

#### Scenario: payload 提供自定义 Server
- **WHEN** 请求或模型输出包含自定义MCP URL、Server code或transport
- **THEN** Runtime和对应MCP服务必须在连接或调用前拒绝

### Requirement: MCP Tool 实现必须由代码 Manifest 拥有
系统 MUST 从代码Manifest注册稳定Tool identifier、server code、描述、输入Schema、操作语义、风险等级、资源类型和实现函数；现有`tool-mcp`只可注册只读资源Tool，File Service只可注册固定任务文件Tool。数据库和管理API MUST NOT创建或覆盖URL、SQL、Shell、脚本、模板、对象键规则或任意可执行实现。

#### Scenario: 部署合法 Manifest
- **WHEN** `tool-mcp`和`file-service`启动并加载无冲突的代码Manifest
- **THEN** 各自`tools/list`只返回当前Job冻结、schema匹配且授权的Manifest子集

#### Scenario: 文件Tool伪装为通用执行器
- **WHEN** File Tool schema接受任意路径、Bucket、对象键、Shell、URL或脚本
- **THEN** Manifest验证拒绝启动或发布

#### Scenario: 管理端提交动态实现
- **WHEN** 管理端尝试创建任意MCP、HTTP、SQL、Shell、脚本或模板实现
- **THEN** 系统拒绝且不持久化该内容

### Requirement: MCP 调用必须绑定有效 Job
每个MCP调用 MUST 绑定有效RUNNING Job和Job冻结的精确Tool/schema hash。`tool-mcp`继续接受非敏感Job标识并重新读取Job；File Service MUST 从已验证Principal JWT解析Job并重新读取用户、Session、Publication、Workspace和scope。任一Server均 MUST 在上游连接、文件元数据读取或对象操作前拒绝不存在、非RUNNING、Runtime/protocol不合法、Tool未冻结或schema漂移的调用。

#### Scenario: 合法 Job 调用冻结只读工具
- **WHEN** RUNNING Job调用其冻结的精确只读Tool
- **THEN** `tool-mcp`进入资源、权限和只读策略校验

#### Scenario: 合法 Job 调用冻结文件工具
- **WHEN** RUNNING Job以有效Principal调用其冻结的精确File Tool
- **THEN** File Service进入任务工作区、文件和操作授权校验

#### Scenario: Job 或 Tool 不匹配
- **WHEN** Job不存在、非RUNNING、Tool未冻结或schema hash漂移
- **THEN** 调用在连接上游或读取文件内容前失败关闭

### Requirement: MCP Transport 不新增认证和治理层
现有`tool-mcp` MUST 不签发或验证Bearer Token/JWT，不挂载Runtime Grant、不拥有signing key，也不新增MCP专用RBAC、授权表或Resource Mapping；携带Authorization的`tool-mcp`请求继续拒绝。File MCP MUST 复用平台统一Principal JWT签发与验证、Job、角色、Business Application和Tool授权事实，不得自建用户、角色、JWT issuer、凭据表或替代授权模型。

#### Scenario: Runtime 调用只读 MCP
- **WHEN** Runtime向`tool-mcp`发起工具调用
- **THEN** 请求不包含Runtime Grant、模型Key、Internal API Token或MCP access token

#### Scenario: tool-mcp 请求携带 Authorization
- **WHEN** `tool-mcp` HTTP请求携带Authorization header
- **THEN** 服务拒绝该请求以维持现有非认证传输边界

#### Scenario: Runtime 调用 File MCP
- **WHEN** Runtime向File Service发起文件工具调用
- **THEN** 请求只携带平台Principal JWT并由File Service复核现有统一授权事实
- **AND** File Service不创建独立RBAC或签发Token

### Requirement: Tool platform resolves secrets only in infrastructure layer
系统 SHALL 仅在拥有外部连接的基础设施适配器中解析`secret://platform/<code>`。Internal API Platform只在建立DB、Redis、Loki连接时解析对应Secret；File Service只在其MinIO存储适配器中解析MinIO Secret。Agent、模型、Runtime、File Worker、MCP Tool参数与响应、Job、Resource Revision、审计和业务领域服务 MUST NOT 接收或保存原始Secret。

#### Scenario: Database tool uses platform secret ref
- **WHEN** 已发布数据库revision的`password_ref`为`secret://platform/order_db_password`
- **THEN** Internal API Platform基础设施适配器在创建受限连接前解析该Secret
- **AND** 其他层只看见reference和configured状态

#### Scenario: File Service uses MinIO secret ref
- **WHEN** File Service配置引用有效平台MinIO Secret
- **THEN** 只有MinIO基础设施适配器获得解密值
- **AND** File MCP、Runtime和File Worker看不到原始凭据

#### Scenario: Secret value appears in tool result
- **WHEN** 上游结果或异常意外包含credential
- **THEN** 平台必须在返回、持久化或发送给模型前脱敏

#### Scenario: Unsupported provider reference appears
- **WHEN** 运行时快照包含新的`env:`、`vault:`或`kms:`引用
- **THEN** 快照装载必须失败并保留Last Known Good，不得尝试回退解析
