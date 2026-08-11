## ADDED Requirements

### Requirement: ONES MCP 第一阶段只发布工作项查询
系统 SHALL 提供固定 `ones-mcp` Streamable HTTP 服务，且第一阶段只发布 `ones_work_item_search`；服务 MUST NOT 发布新增、修改、删除、任意 GraphQL、任意 HTTP 或登录 Tool。

#### Scenario: 列出ONES MCP Tools
- **WHEN** Runtime 读取 `ones-mcp` Tool Catalog
- **THEN** Catalog 只包含 `ones_work_item_search`

#### Scenario: 模型尝试调用写操作
- **WHEN** 模型请求 `ones_work_item_create`、`ones_work_item_update` 或任意未冻结 Tool
- **THEN** Runtime 或 MCP 在外部调用前拒绝请求并记录拒绝

### Requirement: ONES查询公开输入输出必须有界
`ones_work_item_search` SHALL 只接受 `keyword`、`issue_type` 和 `limit`；`keyword` 长度为 1..200，`issue_type` 只允许 `demand|task|defect`，`limit` 为 1..50。输出 SHALL 只包含有界 `number/name/type` 列表、`total`、`truncated` 和 `untrusted_data=true`。

#### Scenario: 合法查询
- **WHEN** Agent 提交合法 keyword、issue type 和 limit
- **THEN** MCP 返回不超过 limit 的规范化工作项结果

#### Scenario: 输入尝试覆盖身份或GraphQL
- **WHEN** Tool Input 包含 user ID、Team、Token、URL、Header、query、document 或其它额外字段
- **THEN** 输入 schema 拒绝整个调用且不访问数据库凭据或 ONES

### Requirement: ONES MCP必须从平台Principal解析业务身份
ONES MCP SHALL 使用 JWT `sub` 和 `job_id` 解析当前系统用户唯一启用的 ONES 身份、当前默认 Team 和 ACTIVE 凭据；Tool Input MUST NOT 决定这些值。

#### Scenario: 当前用户已绑定且凭据有效
- **WHEN** `sub` 对应启用用户、启用 ONES 身份、有效默认 Team 和 ACTIVE 凭据
- **THEN** MCP 使用该身份的 ONES User ID、Team 和 Token 调用查询

#### Scenario: 当前用户未重验旧绑定
- **WHEN** 用户存在 ONES 身份事实但没有本变更创建的 ACTIVE 加密凭据
- **THEN** MCP 返回需要本人重新验证的安全错误且不调用 ONES

#### Scenario: 多个当前ONES身份
- **WHEN** 同一用户出现多个未解绑 ONES 身份或默认 Team 不唯一
- **THEN** MCP 以身份数据不一致失败关闭，不任意选择记录

### Requirement: ONES查询必须使用固定受控Provider请求
ONES MCP MUST 使用服务端固定 Base URL、登录路径、查询路径、Header 名、只读 GraphQL document、issue type 映射、超时和响应大小；生产目标 MUST 为 HTTPS 且 host 在 allowlist 中，本地 Mock 仅可通过显式配置允许 HTTP。

#### Scenario: 调用ones_mock查询
- **WHEN** 本地测试启用固定 Mock host 并提供合法 Principal 与凭据
- **THEN** MCP 使用 `Ones-User-Id`、`Ones-Auth-Token` 和默认 Team 调用 Mock 已定义查询路径

#### Scenario: Provider重定向或响应过大
- **WHEN** ONES 返回重定向、非 JSON、超限响应或缺少必填字段
- **THEN** MCP 中止处理并返回安全 Provider 错误，不跟随重定向或保存原始正文

### Requirement: Token失效后必须自动重新登录一次
ONES MCP SHALL 在查询首次返回 401 后解析当前加密登录材料，调用固定登录端点并严格验证返回 subject 与 Team；成功后 MUST 以 credential revision 条件更新加密 Token，并最多重试原查询一次。

#### Scenario: 401后重新登录成功
- **WHEN** 缓存 Token 被 Mock 拒绝但加密邮箱和密码仍有效
- **THEN** MCP 登录取得新 Token、更新 credential revision、重试一次查询并返回成功结果

#### Scenario: 其它实例已经刷新Token
- **WHEN** MCP 处理 401 时发现数据库 credential revision 已变化
- **THEN** MCP 使用较新 Token 重试，不用旧 revision 覆盖数据库

#### Scenario: 重新登录身份变化
- **WHEN** 登录返回的 ONES User ID 与已绑定 subject 不同或默认 Team 不在返回 Team 集合
- **THEN** MCP 标记凭据为 `REAUTH_REQUIRED`、不更新身份事实并返回安全错误

#### Scenario: 重试仍然401
- **WHEN** 更新 Token 后原查询再次返回 401
- **THEN** MCP 不进行第二次登录，标记需要重验并失败关闭

### Requirement: ONES凭据不得离开受信执行边界
ONES MCP MAY 在进程内短暂解密登录材料和 Token，但 MUST NOT 把它们返回给 Runtime、模型或用户，也不得写入 Tool event、审计、日志、异常、metric label 或终端 ledger。

#### Scenario: 扫描成功与失败证据
- **WHEN** 测试完成绑定、查询、401刷新和失败路径
- **THEN** 数据库公开投影、审计、日志、Runtime 事件和 Tool 输出中都找不到邮箱、密码、Token 或 Principal JWT 原文

### Requirement: Python与TypeScript Runtime必须等价调用ONES MCP
两个 Runtime SHALL 使用相同固定 `ones-mcp` URL、Principal JWT Header、Tool schema、模型 Tool 名和失败分类，并继续执行精确 Tool allowlist 与调用预算。

#### Scenario: 双Runtime执行Mock查询
- **WHEN** Python 与 TypeScript Runtime 分别执行同一已冻结 ONES 查询 Job fixture
- **THEN** 两端调用 `ones-mcp` 并得到 schema 等价的有界 Mock 结果与审计证据
