## ADDED Requirements

### Requirement: 业务 MCP 可按 Job 来源解析当前钉钉身份
平台 SHALL 允许固定 `dingtalk-mcp` 在验证自身 audience 的 Business Principal 后，按 Job 内部用户、来源 Connector 和 Connector 所属企业解析唯一启用的钉钉外部身份。身份或 union ID 不得来自 JWT、Prompt 或 Tool 参数。

#### Scenario: 当前 Job 来自钉钉私聊
- **WHEN** Job 来源 Connector、企业、用户与唯一启用身份一致
- **THEN** dingtalk-mcp 获得服务端解析的 staff ID 和 union ID

### Requirement: mutation 确认人必须仍是有效原始主体
系统 MUST 在卡片确认时和 Provider 执行前分别复核原始内部用户、钉钉外部主体与来源企业映射；身份解绑、停用、歧义或换绑 SHALL 阻止执行。

#### Scenario: 用户在确认后解绑身份
- **WHEN** Action Intent 已批准但执行前外部身份已解绑
- **THEN** worker 拒绝 Provider 调用且不回退到其它身份

