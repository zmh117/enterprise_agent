## ADDED Requirements

### Requirement: DingTalk enterprise App connector uses secret references
系统 SHALL 使用 connector 配置表达钉钉企业 App 的 Client ID 和 Client Secret，真实值 MUST 通过环境变量或受控 secret reference 解析，不能明文写入 job、audit、delivery attempt 或仓库文件。

#### Scenario: Enterprise connector resolves credentials
- **WHEN** `dingtalk_enterprise_robot` delivery adapter 需要发送消息
- **THEN** 系统从 connector 的 secret references 解析 Client ID 和 Client Secret，并只在日志和审计中记录 connector ID

#### Scenario: Enterprise connector is missing credentials
- **WHEN** connector 未配置 Client ID 或 Client Secret
- **THEN** 系统将 delivery 标记为配置失败，返回安全错误摘要，且不发起钉钉网络请求

### Requirement: DingTalk webhook robot connector stores endpoint and signing secret safely
系统 SHALL 使用 connector 的 endpoint reference 和 secret reference 表达钉钉 webhook 群机器人 URL 与加签密钥，并在发送前执行 host allowlist 校验。

#### Scenario: Webhook endpoint is allowed
- **WHEN** webhook 群机器人 endpoint 的 host 匹配 connector host allowlist
- **THEN** 系统允许 delivery adapter 发送群消息

#### Scenario: Webhook endpoint is denied
- **WHEN** webhook 群机器人 endpoint 的 host 不在 connector host allowlist 中
- **THEN** 系统阻止外部请求、记录配置错误，并且不保存完整 webhook URL

### Requirement: Webhook robot connector is delivery-only
系统 SHALL 支持将 DingTalk webhook 群机器人 connector 配置为 `allow_ingress=false`、`allow_delivery=true`，并在运行时强制执行。

#### Scenario: Webhook robot configured for delivery
- **WHEN** Agent job 使用 webhook 群机器人 connector 作为 delivery connector
- **THEN** 系统允许投递流程继续执行

#### Scenario: Webhook robot configured for ingress
- **WHEN** 请求使用 webhook 群机器人 connector 作为入口 connector
- **THEN** 系统拒绝入口授权并记录安全审计事件
