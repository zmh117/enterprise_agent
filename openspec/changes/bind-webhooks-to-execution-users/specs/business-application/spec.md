## MODIFIED Requirements

### Requirement: 应用策略采用严格的受控结构
系统 SHALL 对 Trigger、Actor、Session、Execution 和 Delivery 策略执行严格 schema 校验，MUST 拒绝未知字段、未知枚举、越界限制、任意 URL、底层查询语言和敏感凭据。

#### Scenario: 保存钉钉当前发送人策略
- **WHEN** 钉钉 Trigger 使用 `CURRENT_SENDER` actor policy 并引用允许入口的 connector
- **THEN** 系统接受该受控策略并保存非敏感 connector 与路由标识

#### Scenario: 保存Webhook绑定用户策略
- **WHEN** Webhook Trigger 使用 `BOUND_USER` actor policy
- **THEN** 系统要求引用Webhook 发布已固定的启用 human 用户，应用不得另行覆盖
- **AND** 不允许在策略中直接提交外部系统用户名、密码或 Token

#### Scenario: 提交不安全配置
- **WHEN** 草稿包含数据库连接、Redis地址、Loki地址、SQL、LogQL、Shell、任意HTTP URL、Password、Secret或Token字段
- **THEN** 系统拒绝保存并返回安全的字段级校验错误
- **AND** 错误、日志和审计中不回显敏感值

### Requirement: 运行时接管受支持的钉钉与Webhook入口
应用运行态 SHALL 支持 `dingtalk_private`、`dingtalk_group` 与 `webhook` 三种已发布 Trigger。钉钉使用 CURRENT_SENDER 与 `bot:` 或 `conversation:` 路由键；Webhook 使用 BOUND_USER 与 `webhook:` 路由键。未知类型、错误前缀、主体策略不匹配或无有效来源依赖 MUST 失败关闭。

#### Scenario: 钉钉入口
- **WHEN** 受信消息匹配启用的私聊或群聊 Trigger
- **THEN** 服务按当前发送人解析身份和角色，并固定命中的应用发布版本。

#### Scenario: Webhook入口
- **WHEN** 受治理Webhook绑定启用执行用户与已发布应用
- **THEN** 服务通过完整认证授权链创建Job，不回退默认Agent或其他人工主体。

#### Scenario: Webhook重新绑定人员
- **WHEN** 事件执行用户与应用发布固定的入口用户不一致
- **THEN** 系统拒绝创建 Job 并提示重新保存、发布和激活应用，不静默切换执行身份。

## REMOVED Requirements

### Requirement: 服务账号仅通过业务授权参与非交互式入口
**Reason**: Webhook 改为发布绑定的启用人员，使用此人的现有权限与身份。
**Migration**: 旧服务账号 Webhook 停用并重新选择执行用户发布，不将服务账号权限自动复制给人员。
