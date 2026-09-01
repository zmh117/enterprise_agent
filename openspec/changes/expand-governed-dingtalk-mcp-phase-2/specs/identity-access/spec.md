## ADDED Requirements

### Requirement: 钉钉业务 MCP 必须按精确 Tool 合同复核 Principal
`dingtalk-mcp` SHALL 对每次调用使用目标 Tool 自身的 identifier、schema hash、effect、confirmation policy、required scope、operation 和 risk 复核 Business Principal JWT、运行 Job、Agent/Application Publication、角色 grant 与 Job Snapshot。Resolver MUST NOT 使用固定创建待办常量替代实际 Tool 事实。

#### Scenario: 只读 Tool 通过授权
- **WHEN** 当前 Principal 和 Job Snapshot 精确包含 `dingtalk_search_users` 的 read/none 合同且角色与 Application 仍授权
- **THEN** 系统允许该只读 Tool 继续解析 Connector 和企业身份

#### Scenario: mutation 使用只读快照
- **WHEN** mutation Tool 在 Job Snapshot 中缺少自身 mutation effect 或确认策略
- **THEN** 系统在 Action Intent 或 Provider I/O 前拒绝

### Requirement: 钉钉 Tool 目标身份必须来自当前 Job 与持久事实
系统 SHALL 从当前运行 Job 的内部用户、来源 Connector、Connector 企业和唯一启用钉钉外部身份解析 staff ID 与 union ID，并按 Tool target policy 解析当前用户、primary calendar、AI 表格 operator、来源会话或本人通知接收人。JWT、Prompt 与 Tool 参数 MUST NOT 携带或选择这些可信目标身份。

#### Scenario: 当前用户身份唯一有效
- **WHEN** Job 来源 Connector 有效且内部用户在同一企业只有一个启用、完整的钉钉身份
- **THEN** 系统把该身份作为 Tool 的唯一 staff ID/union ID 来源

#### Scenario: 普通成员身份只有 Staff ID
- **WHEN** 当前企业内唯一启用的钉钉身份已有可信 staff ID、尚无 union ID，且目标 Tool 的 Provider 合同需要 union ID
- **THEN** 系统使用当前 Job 的同一 Connector 应用凭据和该 staff ID 调用代码固定的联系人详情接口，核对返回 user ID 后原子补全 union ID，并使用补全后的同一身份继续本次调用

#### Scenario: Tool 不需要 Union ID
- **WHEN** 目标 Tool 的固定 Provider 合同只需要应用可见范围和当前身份 staff ID
- **THEN** Resolver 不得仅因该身份缺少 union ID 而拒绝调用

#### Scenario: 受信身份补全发生冲突
- **WHEN** Stream 消息或固定联系人详情接口返回的非空 union ID 与当前身份已保存的非空 union ID 不同
- **THEN** 系统保留原身份事实、记录不含身份明文的安全审计并失败关闭，不得覆盖或新建第二个身份

#### Scenario: 身份补全不可用
- **WHEN** 需要 union ID 的 Tool 无法从同一 Connector 的固定联系人详情接口取得经 user ID 核对的非空 union ID
- **THEN** 系统返回稳定的身份不完整或 Provider 权限错误，并且不得改用其它 Connector、Credential、用户或模型参数

#### Scenario: 身份在确认后换绑
- **WHEN** mutation 确认后原身份已解绑、停用、换绑或变为歧义
- **THEN** worker 在 Provider I/O 前拒绝执行且不得改用新身份静默续行

### Requirement: Provider 数据范围不得因工具授权而扩大
角色 Tool grant 只表示可以调用指定 Tool，不得扩大钉钉应用可见范围、当前 operator 的 AI 表格访问、当前用户日历或当前来源会话。系统 SHALL 在准备和执行阶段使用这些 Provider 与来源事实形成数据范围交集。

#### Scenario: 联系人不在应用可见范围
- **WHEN** 当前 Connector App 无权读取目标联系人或部门
- **THEN** Tool 返回安全不可用或空结果，不得改用其它 Connector Credential

#### Scenario: AI 表格不属于当前 operator 可访问范围
- **WHEN** 当前 union ID 不能读取目标 base/sheet
- **THEN** read Tool 拒绝或返回 Provider 安全错误，mutation 不得进入写 endpoint
