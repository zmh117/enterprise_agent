## ADDED Requirements

### Requirement: 双 Runtime 只使用固定标准 MCP Tool Server
系统 SHALL 由单一 `tool-mcp` 服务使用官方 MCP SDK 向 Python 与 TypeScript Runtime 提供工具；Runtime MUST 只连接部署固定的私网地址和 `server_code=tool-mcp`，不得接受 Agent、Application、用户或模型提供的 MCP Server URL。

#### Scenario: 两个 Runtime 调用同一工具
- **WHEN** Python 与 TypeScript Runtime 分别执行冻结了同一 Tool 的 Job
- **THEN** 两端必须使用同一 MCP Tool schema 和等价执行语义

#### Scenario: payload 提供自定义 Server
- **WHEN** 请求或模型输出包含自定义 MCP URL、Server code 或 transport
- **THEN** Runtime 和 `tool-mcp` 必须在连接或调用前拒绝

### Requirement: MCP Tool 实现必须由代码 Manifest 拥有
系统 MUST 从代码 Manifest 注册稳定 Tool identifier、描述、输入 Schema、只读标记、资源类型和实现函数；数据库和管理 API MUST NOT 创建或覆盖 URL、SQL、Shell、脚本、模板或任意可执行实现。

#### Scenario: 部署合法 Manifest
- **WHEN** `tool-mcp` 启动并加载无冲突的代码 Manifest
- **THEN** MCP `tools/list` 只返回当前 Job 冻结且授权的 Manifest 子集

#### Scenario: 管理端提交动态实现
- **WHEN** 管理端尝试创建任意 MCP/HTTP/SQL/Shell/脚本实现
- **THEN** 系统拒绝且不持久化该内容

### Requirement: MCP 调用必须绑定有效 Job
每个 MCP 调用 MUST 携带非敏感 Job 标识；`tool-mcp` MUST 重新读取 Job，并要求状态为 RUNNING、Runtime/protocol 合法、Tool 存在于 Job 冻结集合且 schema hash 一致。

#### Scenario: 合法 Job 调用冻结工具
- **WHEN** RUNNING Job 调用其冻结的精确 Tool
- **THEN** `tool-mcp` 进入资源、权限和只读策略校验

#### Scenario: Job 或 Tool 不匹配
- **WHEN** Job 不存在、非 RUNNING、Tool 未冻结或 schema hash 漂移
- **THEN** 调用在连接上游前失败关闭

### Requirement: 工具资源必须按调用目标唯一解析
`tool-mcp` SHALL 使用 Agent 在当前 Tool Call 中提供的 `environment`、可选 `base`/`workshop`/`placement`、Tool 资源类型和当前可用 Published Resource Revision 解析资源；调用目标 MUST 先通过当前角色数据范围校验。匹配结果 MUST 恰好为一个，不得按顺序、默认值、最近父级或最新版本猜测；Job Snapshot 或 Routing Context 中的历史目标字段 MUST NOT 覆盖调用参数。

#### Scenario: test 环境唯一 MySQL 资源
- **WHEN** Tool Call 目标为 `environment=test` 且只有一个符合条件的已发布 MySQL Resource Revision
- **THEN** 工具使用该版本并记录资源 identity/revision 的非敏感审计

#### Scenario: 环境级资源不要求基地或车间
- **WHEN** Agent 调用目标为 `environment=test`、未提供 base/workshop，且存在唯一 environment scope 资源
- **THEN** 资源可以唯一解析，服务端不得要求虚构基地或车间

#### Scenario: 调用目标超出角色数据范围
- **WHEN** Agent 提供的 environment/base/workshop 不在当前用户角色数据范围内
- **THEN** 调用在资源连接前失败关闭，且不得尝试其它环境或候选

#### Scenario: 资源零命中或多命中
- **WHEN** 目标没有资源或存在两个同等候选
- **THEN** Tool Call 返回稳定资源解析错误且不访问任何候选

#### Scenario: cloud 与 edge 并存
- **WHEN** 同一逻辑目标存在 cloud 与 edge 资源
- **THEN** 调用必须提供明确 placement，否则失败关闭

### Requirement: 数据库 Redis Loki 执行必须保持只读安全边界
`tool-mcp` MUST 在进程内执行数据库、Redis 与 Loki 工具，并保留方言感知只读 SQL、表/前缀隔离、行数/超时、Redis Key 前缀、Loki selector/时间/行数和响应大小限制。

#### Scenario: 合法只读数据库查询
- **WHEN** 查询只读取允许表且满足已授权的 Tool Call 目标和上限
- **THEN** 执行器返回有界、脱敏且标记为不可信内部证据的结果

#### Scenario: 写 SQL 或越界目标
- **WHEN** SQL 包含写操作、多语句、未允许表，或参数尝试覆盖资源/租户/前缀事实
- **THEN** 执行器必须在目标执行前拒绝

### Requirement: MCP Transport 不新增认证和治理层
`tool-mcp` MUST 不签发或验证 Bearer Token/JWT，不挂载 Runtime Grant，不拥有 signing key，不新增 MCP 专用 RBAC、授权表或 Resource Mapping；业务权限由 Job、角色、应用和工具实现复核。

#### Scenario: Runtime 调用 MCP
- **WHEN** Runtime 发起工具调用
- **THEN** 请求不包含 Runtime Grant、模型 Key、Internal API Token 或 MCP access token

#### Scenario: 请求携带 Authorization
- **WHEN** MCP HTTP 请求携带 Authorization header
- **THEN** 服务拒绝该请求，避免形成未定义凭据协议

### Requirement: 工具调用审计必须精确且不含 Secret
系统 SHALL 记录 Job、Agent/Application Publication、Tool identifier/schema hash、业务目标、实际 placement、Resource Revision、权限判定、correlation id、耗时与有界结果摘要；MUST NOT 记录连接密码、Token、完整 Prompt 或无界上游响应。

#### Scenario: 工具调用完成
- **WHEN** Tool Call 成功或失败
- **THEN** 历史记录足以定位精确工具、目标和资源版本且不泄漏 Secret

### Requirement: 旧平台和专用密钥不得回归
发布检查 MUST 拒绝 `runtime-tool-mcp`、`RUNTIME_TOOL_MCP_*`、HS256 issuer/verifier/signing key、Internal API Platform 服务、Internal API Token secret 或 `INTERNAL_API_*` 配置残留。

#### Scenario: 残留扫描命中旧链路
- **WHEN** 代码、Compose、env 示例或活动规格包含旧运行组件或配置
- **THEN** 验收失败直到残留被删除
