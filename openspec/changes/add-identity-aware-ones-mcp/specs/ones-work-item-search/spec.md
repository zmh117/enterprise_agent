## REMOVED Requirements

### Requirement: 第一版只发布一个生产 ONES 查询 Capability
**Reason**: 旧 API Capability 控制面已退役；工作项查询改为代码拥有的标准 MCP Tool。

**Migration**: 使用固定 `ones-mcp:ones_work_item_search` Tool identifier、schema hash、Agent/Application MCP Tool 子集和角色 Tool grant，删除对 Capability Release 的依赖。

### Requirement: 完整发布链决定搜索可用性
**Reason**: 可用性不再由 Connection/Capability Release/Allowlist 决定。

**Migration**: 改由固定 MCP 服务、代码 Tool manifest、Agent/Application Publication MCP Tool 快照、当前角色授权、Principal JWT、用户 ONES 身份和 ACTIVE credential 共同决定。

## MODIFIED Requirements

### Requirement: ONES 查询只使用当前发送人的执行主体
私聊和群聊中的 ONES 搜索 MUST 使用每条消息实际钉钉发送人映射的内部用户。Identity Service SHALL 从该用户的运行 Job 签发 `aud=ones-mcp` 的 Principal JWT；MCP SHALL 再解析该用户当前唯一启用的 ONES User ID、默认 Team 和 ACTIVE credential。系统 MUST NOT 使用管理员验证凭据、应用服务账号、群共享主体、其它用户身份或 Tool 参数提供的身份值。

#### Scenario: 群内两个用户先后查询
- **WHEN** 两条群消息分别来自已绑定用户甲和用户乙
- **THEN** 两个 Job 分别签发自己的 Principal JWT，并使用各自 User、Team 和 Token，结果不得串用

#### Scenario: 当前发送人未绑定ONES
- **WHEN** 钉钉用户可以访问应用但没有启用 ONES 身份或 ACTIVE credential
- **THEN** 系统不执行搜索，并返回安全中文绑定/重验提示

#### Scenario: Tool参数尝试冒充用户
- **WHEN** 模型输入包含 system user、ONES user、Team 或 Token
- **THEN** Tool schema 拒绝调用且不访问 Provider

### Requirement: ONES 错误不导致主体或 Team 回退
未绑定、credential 不可用、Team 权限撤销、403、Principal JWT/Tool 授权失效 MUST 返回安全失败并保持原 Job 平台主体；系统 MUST NOT 切换到管理员、服务账号、新绑定、其它用户或其它 Team。首次401只允许使用同一身份的加密登录材料自动登录并重试一次。

#### Scenario: Token失效后刷新成功
- **WHEN** ONES 搜索首次返回401且当前登录材料仍有效
- **THEN** 系统验证同一 subject/Team、更新 Token 并重试一次，不使用共享 Token

#### Scenario: Token刷新失败
- **WHEN** 自动登录失败、subject/Team 变化或第二次查询仍401
- **THEN** 系统标记 REAUTH_REQUIRED 并要求当前用户本人重验，不回退身份或继续重试

#### Scenario: Team被撤销
- **WHEN** 当前默认 Team 不再属于最新登录响应的 Team 集合
- **THEN** 系统拒绝更新 Token 和执行查询，并要求重新验证/选择 Team

### Requirement: V1 端到端验收覆盖正向发布链
交付验收 MUST 覆盖本人 ONES 绑定与默认 Team、加密 credential、Principal JWT、Agent 精确选择 `ones_work_item_search`、应用选择 Agent 与 MCP Tool 子集、角色 Tool grant、Python/TypeScript Runtime、`ones-mcp`、`ones_mock` 查询、Tool Call 和 MCP 操作审计。

#### Scenario: 完整Mock正向链成功
- **WHEN** 测试用户完成绑定且 Job 的 Agent/Application/角色均授权 ONES 查询
- **THEN** 两个 Runtime 均通过 `ones-mcp` 使用该用户的 User/Team/Token 获得规范化 Mock 结果
- **AND** 审计能关联入口、Job、JWT jti、Tool Call、credential revision、Provider attempt 和结果且不含凭据

### Requirement: V1 端到端验收覆盖失败关闭和回归
交付验收 MUST 证明 Tool 未选、角色未授权、JWT 缺失/伪造/过期、用户未绑定、credential 缺失、401刷新失败、Team撤销和身份停用均失败关闭；同时 MUST 证明现有 `tool-mcp` 和未选择 ONES Tool 的历史 Agent/Application 保持原行为。

#### Scenario: 执行全部负向用例
- **WHEN** 测试分别触发发布/授权/JWT/身份/credential/Team/Provider 故障
- **THEN** 每个用例在外部调用前或明确故障点安全失败，且无主体或 Team 切换

#### Scenario: 回归现有tool-mcp
- **WHEN** 运行只包含原有 `tool-mcp` Tool 的 Job
- **THEN** Runtime 不要求或发送 Principal JWT，原有只读 Tool、Job 和 Delivery 路径保持行为

## ADDED Requirements

### Requirement: 工作项搜索必须作为固定ONES MCP Tool发布
系统 SHALL 以代码 manifest 发布 `server_code=ones-mcp`、`tool_identifier=ones_work_item_search` 和固定 schema hash；只有 Agent Publication、Application Publication 子集和当前角色 Tool grant 同时包含该精确 Tool 时，Runtime 才能向模型暴露它。

#### Scenario: Agent和应用均选择Tool
- **WHEN** 已发布 Agent 包含该 Tool、应用选择其子集且角色授权
- **THEN** Job 快照冻结 server code、identifier 和 schema hash，Runtime 可向模型暴露精确 MCP Tool 名

#### Scenario: 应用未选择Tool
- **WHEN** Agent 包含查询 Tool 但 Application MCP Tool 子集不包含它
- **THEN** Job 快照和模型 Tool Catalog 均不包含该查询

#### Scenario: Schema drift
- **WHEN** Job 冻结 schema hash 与代码 manifest 不一致
- **THEN** Worker 或 MCP 在 Provider 调用前失败关闭并要求重新发布
