## MODIFIED Requirements

### Requirement: ONES 身份通过服务端登录验证
系统 SHALL 使用服务端固定且独立于 API Connection、Capability 与 MCP 的受信 ONES 身份配置，由当前用户本人提交邮箱与一次性密码完成验证，并使用响应中的用户 UUID 作为外部身份标识。管理员不得为其他用户输入邮箱密码或代为验证。

#### Scenario: ONES 凭据验证成功
- **WHEN** 当前用户提交有效邮箱与一次性密码
- **THEN** 系统调用固定登录端点，严格校验响应，并经无 Token Challenge 保存 User ID、显示名称、Team、默认 Team 和验证时间

#### Scenario: 管理员尝试代用户验证
- **WHEN** 管理员在人员管理上下文提交他人的邮箱密码
- **THEN** 系统拒绝且不访问 ONES 登录端点

### Requirement: ONES 凭据和令牌不得持久化
系统 MUST NOT 将 ONES 邮箱、明文密码、登录 Token 或原始登录响应保存到数据库、缓存、日志、审计、API 响应或前端持久层；旧 External API Credential 不得作为身份绑定依赖恢复。

#### Scenario: ONES 登录成功并返回令牌
- **WHEN** ONES 登录响应包含用户令牌
- **THEN** 系统在当前请求内丢弃令牌，仅保留允许的身份与 Team 字段

### Requirement: 外部身份生命周期可管理
系统 SHALL 区分提供方治理动作：钉钉身份继续由管理员按受信候选进行启停和软解绑；ONES 身份由本人绑定、重新验证和软解绑，管理员只可查看、停用和审计，不得启用、代验证或代解绑 ONES。

#### Scenario: 管理员停用 ONES 身份
- **WHEN** 管理员使用当前 Revision 停用 ONES 身份
- **THEN** 系统停用并记录审计，重新启用必须由本人完成新一轮验证

#### Scenario: 管理员尝试解绑 ONES 身份
- **WHEN** 管理员调用通用身份解绑接口处理 ONES 身份
- **THEN** 系统拒绝且保持身份事实不变

### Requirement: 本阶段不接入 ONES 业务能力
ONES 身份绑定 SHALL 独立于工具运行时，不创建 API Capability、API Connection、业务调用 Token 或 MCP Tool 调用凭据。未来 ONES MCP 凭据必须由独立规格定义。

#### Scenario: 完成 ONES 身份绑定
- **WHEN** 用户完成绑定或重新验证
- **THEN** 系统只更新身份事实，不授予或触发任何 ONES 业务调用能力
