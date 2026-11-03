## ADDED Requirements

### Requirement: Webhook 首次创建自动建立独立入口
管理员在 Web 新建受管 Webhook 时，系统 SHALL 原子创建独立的 `managed_webhook` 入站 Connector、服务账号和默认停用的 Trigger 定义，不要求环境预置入口。Connector MUST 仅允许 ingress；认证 SHALL 由 Trigger 发布中的受管 Secret 引用承担，不复制真实 Token 到 Connector。创建不得修改既有渠道、凭据、Agent 发布或业务授权。

#### Scenario: 首个 Webhook
- **WHEN** 没有可复用入口且有权限管理员提交合法编码、名称和类型
- **THEN** 创建独立入口、服务账号和停用定义，并打开可继续配置的 Web 界面

#### Scenario: 创建失败或重复编码
- **WHEN** 创建链任一步骤失败或编码已存在
- **THEN** 整体回滚并返回安全错误，不遗留无主 Connector 或服务账号

#### Scenario: 入口被用于结果投递
- **WHEN** 尝试把 managed_webhook Connector 用于 Delivery
- **THEN** 按代码类型拒绝，即使配置错误地打开 allow_delivery

### Requirement: Webhook 在渠道页面完成配置发布闭环
Web SHALL 提供受管认证引用、映射、路由、Agent 发布版本、投递和限制配置，复用既有草稿 revision、校验、无副作用预览、发布和启停协议。编辑未保存时 MUST 不允许误校验或发布旧草稿。发布重新验证依赖和权限；未发布 MUST 不允许启用。无结果投递 SHALL 使用 none 且无目标，不要求虚构投递 Connector；其他投递仍执行原授权约束。

#### Scenario: 保存校验预览和发布
- **WHEN** 管理员保存合法草稿、完成依赖配置并校验和预览
- **THEN** 可发布该草稿并单独启用，展示当前发布、公开接收路径和服务账号；预览不创建 Event、Job 或 Delivery

#### Scenario: 无有效凭据或 Agent 未分配入口
- **WHEN** 草稿引用不可用凭据或 Agent 发布未分配独立入口
- **THEN** Web 展示后端字段错误，不自动生成授权、不允许发布

#### Scenario: 草稿未保存或未发布
- **WHEN** 存在未保存编辑或定义尚无发布
- **THEN** Web 分别禁用旧草稿的后续动作和启用操作，后端同样拒绝未发布启用

#### Scenario: 配置读取与授权边界
- **WHEN** 查询目录、详情或执行配置动作
- **THEN** 沿用登录、CSRF 和动作授权；仅返回受管引用与非敏感目录，不返回真实 Token
