## MODIFIED Requirements

### Requirement: DingTalk message identity is parsed
The system SHALL parse and persist the DingTalk Stream conversation identity, actual DingTalk sender identity, source channel, connector identity, external event identity, and user message content needed to resolve an active Business Application Publication and create an Agent session and Agent job. Private and group messages MUST resolve the actual sender independently and MUST NOT use a group-level shared user, administrator, or service account as the external execution subject.

#### Scenario: User asks a diagnostic question
- **WHEN** a verified DingTalk Stream message contains a user diagnostic question
- **THEN** the system persists the conversation identity, actual sender identity, source channel, connector identity, external event identity, original user message and resolved Application Publication context

#### Scenario: Two users send messages in one group
- **WHEN** two DingTalk group messages have different actual senders
- **THEN** the system resolves and persists two independent internal users and never shares an ONES subject snapshot between them

## ADDED Requirements

### Requirement: 钉钉应用访问来自活动路由和启用用户
第一版 DingTalk Application Access MUST 在消息命中绑定活动 Application Publication 的启用连接器，且实际发送人解析为启用内部用户时成立；系统 MUST NOT 要求额外应用用户白名单、应用访问角色或Capability `use` Grant。

#### Scenario: 活动路由和用户均有效
- **WHEN** 钉钉消息命中唯一活动Application Publication且发送人映射到启用内部用户
- **THEN** 系统允许创建Job，并以该应用Publication的Capability Allowlist作为运行资格上限

#### Scenario: 路由未配置活动应用
- **WHEN** 连接器没有唯一活动Application Publication
- **THEN** 系统按现有路由失败关闭语义拒绝Job，不回退到默认Capability配置

#### Scenario: 内部用户已停用
- **WHEN** 发送人的钉钉身份存在但所属内部用户已停用
- **THEN** 系统拒绝创建Job并通过安全投递路径返回中文账户状态提示

### Requirement: 未绑定钉钉身份返回安全自助提示
当实际发送人无法解析为启用内部用户时，系统 MUST 不创建Agent Job或外部执行主体，并 SHALL 通过受控钉钉回复给出不暴露内部用户、应用或权限信息的绑定提示。

#### Scenario: 未知发送人访问应用
- **WHEN** 钉钉消息来自未绑定发送人
- **THEN** 系统不创建Job，并返回安全中文提示引导完成内部账号/钉钉身份绑定

### Requirement: ONES 可用性不改变钉钉应用访问判定
用户缺少 ONES 身份、default Team或有效Token时，系统 SHALL 保留其对已命中钉钉应用的基础访问，但 MUST 不暴露或执行依赖ONES的Capability，并 SHALL 在相关请求中返回安全自助绑定提示。

#### Scenario: 用户可访问应用但未绑定 ONES
- **WHEN** 启用用户命中活动应用且应用允许ONES Capability，但用户没有有效个人凭据
- **THEN** Job或对话可继续处理不依赖ONES的能力，ONES Tool不进入可用目录，并向用户说明需要绑定ONES

#### Scenario: 应用没有配置 ONES Capability
- **WHEN** 用户已绑定ONES但Application Allowlist不包含搜索能力
- **THEN** 系统不得暴露该Capability，也不得因用户已绑定而扩大应用权限
