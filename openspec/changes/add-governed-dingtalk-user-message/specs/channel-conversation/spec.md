## ADDED Requirements

### Requirement: 官方用户批量机器人单聊必须与当前来源会话消息分离
`dingtalk_batch_send_message_to_users_by_robot` SHALL 表示由当前钉钉来源 Job 发起、向一个或多个明确 userId 整批发送的独立机器人单聊 mutation；它 MUST NOT 改变 `dingtalk_send_robot_message` 绑定当前来源会话的语义，也 MUST NOT 替代当前 Agent Job 的普通结果投递。普通结果 Delivery 的成功、失败或重试不得触发或重放该批量消息 Intent。

#### Scenario: 私聊中向多名员工发送
- **WHEN** 当前用户在钉钉私聊 Job 中明确选择多个员工并确认整批用户消息
- **THEN** worker 对冻结的 `user_ids` 执行至多一次官方机器人批量单聊请求
- **AND** Agent 最终回答仍按原私聊回复路由独立投递给当前用户

#### Scenario: 当前来源会话工具被调用
- **WHEN** Agent 调用现有 `dingtalk_send_robot_message`
- **THEN** 系统仍只解析当前群或当前私聊发起人
- **AND** 不读取新增 Tool 的 `user_ids` 或目标事实

#### Scenario: 管理面和确认卡展示历史当前来源 Tool
- **WHEN** 平台向用户或 Agent 展示 `dingtalk_send_robot_message` 的能力名称、描述或确认操作
- **THEN** 文案明确说明目标是当前钉钉来源会话且不支持按姓名或任意 userId 定向发送
- **AND** 系统保留历史 identifier、输入 schema、operation 和 target policy，不把它冒充为官方 Profile 的任意用户批量发送能力

### Requirement: 消息类型选择必须保持显式业务语义
Agent SHALL 仅在用户明确请求工作通知时选择 `dingtalk_send_work_notification`，仅在请求当前群/当前会话消息时选择 `dingtalk_send_robot_message`，并在请求向一个或多个已识别 userId 发送普通消息时选择 `dingtalk_batch_send_message_to_users_by_robot`。任一对应 Tool 缺失或姓名目标仍未唯一解析时 MUST 失败关闭，不得在三种语义之间自动降级、替换或缩小收件人集合。

#### Scenario: 请求普通私信但只有工作通知可用
- **WHEN** 当前 Job 没有新增用户批量消息 Tool 但存在本人工作通知 Tool
- **THEN** Agent 报告普通私信能力不可用
- **AND** 不准备工作通知确认卡

#### Scenario: 用户明确请求给本人发工作通知
- **WHEN** 请求明确包含工作通知语义且本人通知 Tool 已授权
- **THEN** Agent MAY 使用本人工作通知 Tool
- **AND** 不把该结果描述为向其它员工发送的机器人私信
