## ADDED Requirements

### Requirement: dingtalk-mcp 必须是部署固定的业务 MCP
系统 SHALL 通过部署固定、代码注册且使用 `business-principal-jwt` 的 `dingtalk-mcp` Streamable HTTP Server 暴露钉钉业务 Tool。Runtime MUST NOT 接受动态 Server URL、Profile、Provider URL、HTTP 方法、Header、Client Secret 或 Access Token。

#### Scenario: Runtime 调用钉钉 Tool
- **WHEN** Job 冻结合法 `dingtalk-mcp` Tool
- **THEN** Runtime 只向固定私网 `dingtalk-mcp` 地址发送 audience 匹配的短时 Principal JWT

### Requirement: MVP 只提供创建本人待办 mutation
MVP SHALL 只注册 `dingtalk_create_todo`，输入仅包含有界 `subject`、可选 `description` 和可选带时区 `due_time`。Tool MUST 声明 `effect=mutation` 与固定卡片确认策略，且不得接受 creator、executor、participant、userId、unionId、Connector 或企业参数。

#### Scenario: 创建本人待办
- **WHEN** Agent 提供合法标题、备注和截止时间
- **THEN** Tool 规范化参数并创建待确认 Action Intent，目标由当前 Principal 的钉钉身份解析

#### Scenario: Agent 传入 unionId
- **WHEN** Tool 输入包含 `unionId`、`userId`、Token 或 Provider URL
- **THEN** schema 校验拒绝整个调用且不创建意图

### Requirement: 当前用户钉钉身份必须由平台事实唯一解析
`dingtalk-mcp` MUST 从已验证 Principal 对应 Job 的来源 Connector、DingTalk enterprise 和启用内部用户解析唯一启用钉钉外部身份，并要求 `union_id` 非空。零命中、多命中、企业不匹配或身份停用 MUST 失败关闭。

#### Scenario: 当前用户身份唯一
- **WHEN** Job 用户在来源企业存在唯一启用身份且 union ID 已验证
- **THEN** 服务使用该 union ID 作为待办 creator 和唯一 executor

#### Scenario: 身份属于另一企业
- **WHEN** 当前用户只有其它 DingTalk enterprise 的身份
- **THEN** 服务返回安全身份不可用错误且不投放卡片或调用 Provider

### Requirement: 创建待办 Provider 合同必须固定且有界
执行器 SHALL 只调用 `POST https://api.dingtalk.com/v1.0/todo/users/{resolvedUnionId}/tasks`，body 只包含规范化 `subject`、`description`、`dueTime` 与 `executorIds=[resolvedUnionId]`。响应只保留有界 task ID、状态与关联证据。

#### Scenario: 用户确认后创建成功
- **WHEN** 已批准意图通过执行前复核且 Provider 返回合法 task ID
- **THEN** 意图转为 `SUCCEEDED` 并记录不含 Token 的有界 Provider 证据

#### Scenario: Provider 返回未知 schema
- **WHEN** 响应缺少预期结果或超过大小限制
- **THEN** 执行失败关闭且不得把原始无界响应返回模型或写入审计

### Requirement: App Access Token 只能由基础设施层解析和缓存
`dingtalk-mcp` worker SHALL 从意图冻结的来源 Connector 解析平台 Secret，使用固定 Token endpoint 获取 App Access Token，并只在进程内有界缓存。Token 与 Client Secret MUST NOT 进入数据库业务字段、卡片、MCP 结果、日志或审计。

#### Scenario: Connector Secret 不可用
- **WHEN** 已批准意图的 Connector Secret 被停用或无法解析
- **THEN** worker 失败关闭且不尝试其它 Connector 或旧 Token

### Requirement: dingtalk-mcp 必须使用统一 MCP 操作审计
准备阶段和确认后的 Provider 执行 SHALL 使用同一 `mcp_call_id`/Action Intent 关联链记录 TOOL、AUTHORIZATION、CONFIRMATION 与 PROVIDER 有界证据，同时保持 Agent Tool Call 与真实 SDK Tool Use 关联。

#### Scenario: Tool 只创建待确认意图
- **WHEN** 首次 MCP 调用成功准备 Action Intent
- **THEN** 审计状态明确为 `PENDING_CONFIRMATION` 而不是 Provider 成功

