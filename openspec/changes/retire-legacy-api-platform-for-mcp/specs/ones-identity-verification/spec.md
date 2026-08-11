## MODIFIED Requirements

### Requirement: ONES验证只通过受信Connection发起
这里的受信 Connection SHALL 收敛为服务端固定的 ONES 身份提供方配置，而不是已退役的通用 API Connection。系统 MUST 使用固定 Base URL、代码内固定登录 Path 和主机白名单执行验证，不接受浏览器或请求体提供 URL、Method、Path、Header、代理、API Connection Revision 或 MCP Server。

#### Scenario: 身份提供方未配置
- **WHEN** 固定 ONES 身份配置不可用
- **THEN** 系统拒绝验证且不尝试旧 API Connection 或任意 MCP 地址

### Requirement: 成功验证原子绑定ONES身份
系统 MUST 使用不含 Token 的短时单次身份 Challenge，在确认默认 Team 时原子校验当前用户、唯一 subject、候选 Team 和现有 Identity，然后创建或刷新 Identity 并消费 Challenge。

#### Scenario: 新ONES主体验证成功
- **WHEN** 当前用户确认合法 Challenge 和候选 Team
- **THEN** 系统创建 verified/provider_login Identity 并保存最新 Team、默认 Team 和验证时间，不创建个人业务调用 Credential

### Requirement: ONES团队上下文不等于授权
系统 SHALL 保存经过验证的 Team ID/名称、默认 Team 和最近验证时间作为身份上下文，MUST NOT把 Team 自动转为内部角色、数据范围、Capability、MCP Tool 授权或业务调用 Token。

#### Scenario: 用户属于多个Team
- **WHEN** ONES 登录响应包含多个合法 Team
- **THEN** Identity 保存去重后的候选与默认 Team，内部 RBAC 保持不变
