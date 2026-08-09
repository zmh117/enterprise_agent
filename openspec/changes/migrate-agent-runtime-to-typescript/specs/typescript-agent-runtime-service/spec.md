## ADDED Requirements

### Requirement: TypeScript Runtime 必须是独立且有界的执行服务
系统 SHALL 将真实 Claude Agent SDK 执行放入独立 TypeScript `agent-runtime` 服务；该服务 MUST 只执行 Python Worker 已授权的一次 invocation，MUST NOT 消费业务 RabbitMQ Job 队列、决定 Job 状态、管理 Application、执行 Delivery 或成为平台数据库事实源。

#### Scenario: Worker 委托一次执行
- **WHEN** Python Worker 已 claim 一个合法 Job 并构造固定执行上下文
- **THEN** Runtime 执行该 invocation 并返回规范事件与终态，Job 状态和结果仍由 Python Worker 持久化

#### Scenario: Runtime 收到业务状态写入请求
- **WHEN** 请求要求 Runtime 直接更新 Job、Application、授权或 Delivery 数据
- **THEN** Runtime 拒绝未定义操作且不获得这些表的写权限

### Requirement: 内部执行协议必须版本化、完整性校验且大小有界
Worker 与 Runtime MUST 使用严格版本化的执行 schema，冻结 invocation、Job、Agent/Application Publication、模型连接、执行限制、MCP Binding 和安全规则；Runtime MUST 校验 request digest 与 Publication 完整性，并 MUST 拒绝未知字段、不支持版本、摘要不一致和超限请求。

#### Scenario: 合法 v1 请求
- **WHEN** Worker 提交受支持协议版本、完整必填字段、正确摘要和有效执行授权
- **THEN** Runtime 接受请求并返回具有单调 sequence 的版本化事件流

#### Scenario: 请求摘要被篡改
- **WHEN** 请求正文与 Runtime Grant 中的 request digest 不一致
- **THEN** Runtime 在启动 SDK、解析模型 Key 或连接 MCP 前失败关闭

#### Scenario: 请求包含未知安全字段
- **WHEN** 客户端提交 schema 未定义的 Tool、Header、身份、URL 或权限字段
- **THEN** Runtime 拒绝整个请求而不是忽略字段或扩大执行范围

### Requirement: Runtime 执行授权必须短期、单次且绑定精确 Job
每次调用 MUST 使用平台签发的 Runtime Grant；Runtime MUST 验证 issuer、`aud=agent-runtime`、authorized party、Job、invocation、attempt、Publication/hash、request digest、expiry 和 JTI，并 MUST 防止过期、错误 audience、跨 Job 与摘要不同的重放。

#### Scenario: 相同 invocation 安全重取终态
- **WHEN** Worker 因连接中断使用相同 invocation ID、attempt 和 request digest 重试
- **THEN** Runtime 返回已有有界终态或继续关联原执行，不再次无条件启动模型

#### Scenario: invocation 被跨 Job 重放
- **WHEN** 客户端把一个合法 Grant 用于不同 Job 或不同请求摘要
- **THEN** Runtime 拒绝请求并记录不含认证材料的安全拒绝审计

### Requirement: Runtime 必须隔离解析模型凭据
Runtime MUST 按 Job 固定的模型连接 revision/hash 和稳定 Secret ref 解析 attempt 开始时的 active 模型 Key；Master Key 只能以只读文件挂载到 Runtime，Runtime 数据库身份只能读取所需模型/Secret 事实。Key MUST NOT 进入 RabbitMQ、Job/Publication、执行事件、日志、trace、错误、浏览器或 MCP 参数。

#### Scenario: Active Key 已轮换
- **WHEN** Job 固定模型连接配置不变但稳定 Credential 在 attempt 前完成轮换
- **THEN** Runtime 使用新的 active Secret version，并保持模型 revision/hash provenance 不变

#### Scenario: Secret 不可用
- **WHEN** 固定 Secret 缺失、禁用、解密失败或不属于模型连接
- **THEN** Runtime 返回不可重试安全配置错误且不调用模型或 MCP

#### Scenario: Python 与 Node 解密格式兼容
- **WHEN** 两端读取同一组受控加密 fixture
- **THEN** Node 只能用正确 Master Key 解密出相同值，错误 Key、tag 或版本均失败关闭且不输出明文

### Requirement: Runtime 必须通过官方 TypeScript SDK 严格限制 MCP 与内置 Tool
Runtime SHALL 使用精确锁定的最新稳定 `@anthropic-ai/claude-agent-sdk`，并 MUST 为每次 query 显式使用 `settingSources: []`、精确远程 MCP Server、精确 `allowedTools`、deny-by-default permission hook 和内置危险 Tool denylist。Runtime 与 MCP Server MUST 分别执行权限校验。

#### Scenario: Job 仅允许一个 ONES Tool
- **WHEN** 执行请求只包含一个合法 ONES MCP Tool Binding
- **THEN** SDK 只注册对应 Server 并只批准该精确 Tool，Data MCP 与其他 ONES Tool 不可见

#### Scenario: SDK 尝试读取宿主设置
- **WHEN** 容器或工作目录存在用户、project 或 local Claude settings
- **THEN** Runtime 因 `settingSources: []` 不加载这些设置、命令、Plugin、Skill 或额外 Tool

#### Scenario: 模型尝试调用写工具
- **WHEN** 模型请求 Bash、Write、Edit、WebFetch、WebSearch、Shell 或未列入 allowlist 的 Tool
- **THEN** SDK permission hook 拒绝调用且不产生外部副作用

### Requirement: Runtime 事件和错误必须规范化且不包含私有推理
Runtime SHALL 流式返回有界 `accepted`、文本、Tool、diagnostic 和单一终态事件，并 MUST 将 SDK/CLI 结果映射为稳定错误码与 retry class。事件 MUST NOT 包含 thinking block、chain-of-thought、完整 Prompt、认证材料、原始 Provider/MCP payload 或不受限 stderr。

#### Scenario: Tool 后发生 timeout
- **WHEN** SDK 在完成一个 MCP Tool 后达到 wall-clock timeout
- **THEN** Runtime 返回已发生 Tool 的安全摘要和 timeout 终态，Python Worker 可持久化失败前证据

#### Scenario: stderr 包含 Token
- **WHEN** SDK/CLI stderr 包含 Authorization、API Key、Token 或敏感 URL
- **THEN** Runtime 在序列化日志和 diagnostic 前屏蔽并截断敏感内容

### Requirement: Runtime 必须支持取消、连接中断和终态恢复
Runtime MUST 将 Worker 取消、Job 撤销、wall-clock timeout 和客户端连接中断传播到 SDK AbortController 及当前 MCP 请求，并 MUST 为 invocation 保留有界终态以支持 Worker 恢复。运行中的 invocation MUST NOT 自动切换到另一 Runtime 实现。

#### Scenario: Job 在模型执行中被取消
- **WHEN** Worker 发送合法取消请求或关联 Job 已不可执行
- **THEN** Runtime 中止 SDK/MCP、返回 cancelled 终态且不继续产生 Tool Call

#### Scenario: Runtime 完成后 Worker 断线
- **WHEN** Runtime 已产生 completed 终态但 Worker 尚未提交本地事务即断线
- **THEN** Worker 用相同 invocation digest 取得相同终态，避免无条件重复调用模型

### Requirement: Runtime 部署和健康检查不得调用真实模型
Runtime MUST 使用非 root Node LTS 镜像、精确 lockfile、只读文件系统和最小网络/数据库权限；health/readiness SHALL 报告协议、SDK/CLI 版本、配置与依赖状态，但 MUST NOT 调用真实模型或业务 MCP Tool。

#### Scenario: 无真实模型凭据启动
- **WHEN** Runtime 以测试或未配置模式启动
- **THEN** 进程健康可用，readiness 明确报告模型执行未配置且不产生外部费用

#### Scenario: 镜像依赖检查
- **WHEN** 构建生产 Runtime 镜像
- **THEN** 镜像使用 lockfile 中精确 SDK 版本、不执行启动时安装、不包含 Python Claude SDK或全局浮动 Claude CLI
