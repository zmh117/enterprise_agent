## ADDED Requirements

### Requirement: Phase 2 必须暴露固定且有界的钉钉工具目录
系统 SHALL 在同一代码注册的 `dingtalk-mcp` 中保留 `dingtalk_create_todo`，并新增 proposal 指定的 18 个只读 Tool 与 8 个 mutation Tool。运行时 MUST NOT 读取 `ACTIVE_PROFILES`、官方 YAML、动态 Tool 名、Provider URL、HTTP Method/Header 或模型提供的 Credential 来扩大目录。

#### Scenario: 授权用户列出钉钉工具
- **WHEN** 当前 Job 的 Publication、角色和 Job Snapshot 只授权 Phase 2 目录中的一部分 Tool
- **THEN** `dingtalk-mcp` 只返回该精确子集及代码固定 schema/effect/confirmation policy

#### Scenario: 环境配置请求激活全部官方 Profile
- **WHEN** 运行环境存在 `ACTIVE_PROFILES=ALL` 或包含本 change 未注册的官方 Profile
- **THEN** 系统忽略该配置且不得增加任何 Tool 或 Provider endpoint

### Requirement: 只读 Tool 必须在完整授权后直接返回有界结果
18 个只读 Tool SHALL 使用当前 Job Principal、Agent/Application Publication、角色 grant、Job Snapshot、Connector、企业和外部身份完成逐工具复核，并在不创建 Action Intent 或确认卡片的情况下调用固定只读 Provider endpoint。列表、时间窗、游标、请求和响应 MUST 受代码上限约束。

#### Scenario: 用户查询本人未完成待办
- **WHEN** `dingtalk_list_todos` 通过全部授权且请求位于分页上限内
- **THEN** 系统使用服务端解析的当前 union ID 查询并返回有界待办列表，不创建确认意图

#### Scenario: 只读列表请求超限
- **WHEN** Agent 请求超过代码允许的页大小、时间窗或响应字节
- **THEN** 系统在 Provider I/O 前拒绝或截断为明确的有界分页语义，并记录安全错误或结果摘要

### Requirement: 通讯录和部门结果必须受企业可见范围和字段白名单限制
联系人与部门 Tool SHALL 只使用来源 Connector 所属企业的 App Credential，并依赖该应用在钉钉侧的可见范围。用户响应 MUST 只包含工作所需的稳定 ID、名称和有界组织字段，不得返回手机号、邮箱、家庭地址或原始完整 Provider 对象。

#### Scenario: 搜索可见范围内用户
- **WHEN** 用户调用 `dingtalk_search_users` 且 Provider 返回匹配成员
- **THEN** 系统仅返回字段白名单内的有界结果和分页事实

#### Scenario: Provider 返回额外敏感字段
- **WHEN** 钉钉响应包含手机号、邮箱或未声明的扩展字段
- **THEN** 系统在 Tool 结果和审计前删除这些字段

### Requirement: 待办和日历 Tool 必须固定为当前用户资源
待办 Tool 的 union ID、日历 Tool 的 union ID 和 `calendarId=primary` SHALL 由当前 Principal 注入。模型 MAY 提供有界 task ID、event ID 和业务字段，但 MUST NOT 提供或覆盖用户、日历、企业或 Connector 身份。

#### Scenario: 查询当前用户主日历
- **WHEN** 用户调用 `dingtalk_list_calendar_events` 并提供合法时间范围
- **THEN** 系统只查询当前 Principal 的 primary calendar

#### Scenario: 参数携带其它用户或日历
- **WHEN** Agent 参数包含 union ID、user ID、任意 calendar ID 或 Connector ID
- **THEN** Tool schema 或参数规范化在 Provider I/O 前拒绝请求

### Requirement: AI 表格 Tool 必须使用当前 operator 并限制记录级写入
AI 表格 Tool SHALL 把当前 Principal 的 union ID 作为固定 `operatorId`，并只允许搜索/查询 base、sheet、field、record 以及新增/更新 record。记录 mutation MUST 在准备确认前和确认后写入前分别验证当前 operator 仍可读取目标 base/sheet；单次 mutation 的记录数、字段数和序列化字节 MUST 有界。

#### Scenario: 当前 operator 更新可访问记录
- **WHEN** `dingtalk_update_aitable_records` 的目标预检通过且原用户确认当前 revision
- **THEN** worker 重新预检同一 base/sheet 后按冻结 record ID 与字段值执行一次固定更新

#### Scenario: 确认后目标权限被撤销
- **WHEN** 当前 operator 在确认后已不能读取目标 base/sheet
- **THEN** worker 在写 endpoint 前失败关闭并将 Intent 记录为安全失败

#### Scenario: 请求修改表结构
- **WHEN** Agent 请求创建、更新或删除 sheet/field 或删除 record
- **THEN** 当前工具目录不提供对应 Tool 且不得通过通用 Provider 调用绕过

### Requirement: 工作通知状态只允许查询平台创建的本人通知
`dingtalk_get_work_notification_progress` 与 `dingtalk_get_work_notification_result` SHALL 只接受能够关联到同一 actor、企业、Connector 和成功 `dingtalk_send_work_notification` Intent 的通知 task ID。系统 MUST NOT 使用任意 task ID 探测其它通知任务。

#### Scenario: 查询本人已发送通知状态
- **WHEN** task ID 能关联到当前 actor 在同一企业和 Connector 下的成功发送结果
- **THEN** 系统调用固定状态 endpoint 并返回有界进度或结果

#### Scenario: 查询未知通知任务
- **WHEN** task ID 不存在、属于其它 actor 或来自其它 Connector
- **THEN** 系统在 Provider I/O 前返回统一不可用错误且不泄漏任务是否存在

### Requirement: 新增 mutation 必须逐次确认并固定分派
`dingtalk_update_todo`、`dingtalk_complete_todo`、`dingtalk_create_calendar_event`、`dingtalk_update_calendar_event`、`dingtalk_insert_aitable_records`、`dingtalk_update_aitable_records`、`dingtalk_send_robot_message` 和 `dingtalk_send_work_notification` SHALL 声明 `effect=mutation` 与受支持确认策略。首次调用只准备不可变 Action Intent；原用户确认当前 revision 后，worker MUST 按代码固定 Tool/operation 注册表重新授权并执行一次。

#### Scenario: 用户确认日程创建
- **WHEN** 原用户确认合法 `dingtalk_create_calendar_event` Intent
- **THEN** worker 复核当前授权和目标后调用固定创建日程 endpoint，并更新 Intent 与卡片终态

#### Scenario: 用户拒绝发送消息
- **WHEN** 原用户拒绝 `dingtalk_send_robot_message` Intent
- **THEN** Intent 进入 REJECTED，Provider 发送次数为零且卡片显示不会执行

#### Scenario: operation 与 Tool 不匹配
- **WHEN** Intent 的 operation code 不是代码为其 tool identifier 注册的唯一 operation
- **THEN** worker 在任何 Provider I/O 前失败关闭并记录安全审计

### Requirement: 消息与工作通知必须限制为当前来源和当前用户
`dingtalk_send_robot_message` SHALL 只向当前 Job 冻结的钉钉来源会话发送：群聊目标为当前群，私聊目标为当前发起人。`dingtalk_send_work_notification` SHALL 只向当前发起人发送。模型输入只允许有界标题与正文，不得包含 conversation ID、robot code、user list、department list、全员标志或 Agent ID。

#### Scenario: 当前群发送确认消息
- **WHEN** 群聊 Job 的原用户确认机器人消息 Intent
- **THEN** worker 使用 Job 冻结的当前 open conversation ID 和 Connector robot code 发送消息

#### Scenario: 非钉钉来源 Job 请求发消息
- **WHEN** Job 没有可验证的钉钉来源会话和 Connector
- **THEN** Tool 在准备 Intent 前拒绝且不接受参数补充目标

#### Scenario: 当前用户确认工作通知
- **WHEN** 当前用户确认合法工作通知 Intent 且 Connector 具有固定 Agent ID
- **THEN** worker 只把当前用户 staff ID 作为接收人发送一次通知

### Requirement: Provider 调用和审计必须保持固定与脱敏
所有 Phase 2 Tool SHALL 使用代码固定 host、path、method、body 投影和响应归一化。MCP 审计 SHALL 记录 Server/Tool/schema、operation、授权、耗时、大小、状态和安全目标摘要，MUST NOT 保存 Secret、Access Token、Authorization Header、原始 Provider 正文、联系人敏感字段、消息正文、日程正文或 AI 表格值。

#### Scenario: Provider 返回未声明字段
- **WHEN** 固定 Provider endpoint 返回超出输出合同的字段
- **THEN** 系统只投影允许字段并在审计中记录有界响应事实

#### Scenario: Agent 尝试提交网络控制参数
- **WHEN** Tool 输入包含 URL、Method、Header、Token、Secret 或 Profile
- **THEN** schema 校验拒绝且系统不发起网络访问

### Requirement: Phase 2 必须明确排除高风险官方操作
当前目录 MUST NOT 注册删除待办、删除日程、增删参与人、删除 AI 表格记录、修改 AI 表格 sheet/field 结构、撤回消息/通知、自定义机器人 Webhook、DING 或任意目标群发 Tool。官方包升级、Profile 权限或环境变量变化不得改变该排除边界。

#### Scenario: Agent 请求删除或撤回
- **WHEN** Agent 请求当前目录未提供的删除、撤回或 DING 操作
- **THEN** `dingtalk-mcp` 返回 Tool 未发布或能力不支持，且不创建 Intent 或 Provider attempt
