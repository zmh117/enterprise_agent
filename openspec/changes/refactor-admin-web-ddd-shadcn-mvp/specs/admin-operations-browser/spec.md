## ADDED Requirements

### Requirement: 队列页面提供安全只读状态
系统 SHALL 展示配置允许的 RabbitMQ 队列名称、用途、ready/unacked 消息数、消费者数、重试/死信关系、采集时间和可用性；MVP MUST 不提供 purge、delete、publish 或 replay 操作。

#### Scenario: 查看队列积压
- **WHEN** 授权运维用户打开队列页面
- **THEN** 系统返回允许展示的主队列、延迟重试队列和死信队列状态

#### Scenario: 尝试执行破坏性操作
- **WHEN** 用户尝试调用未授权的队列清空、删除或消息重放接口
- **THEN** 系统不存在该 MVP 写接口或明确拒绝请求并记录审计

### Requirement: 历史对话页面支持分页检索和关联追踪
系统 SHALL 按权限范围分页查询会话，并支持按时间、Channel、内部用户、外部会话标识、Agent 和任务状态筛选；详情 SHALL 展示消息、附件、Agent Job、步骤、工具调用和 Delivery 的脱敏关联信息。

#### Scenario: 查看会话详情
- **WHEN** 用户打开其有权访问的会话
- **THEN** 系统按稳定时间顺序返回消息，并提供相关任务、工具调用、附件和 Delivery 引用

#### Scenario: 查询无权访问的会话
- **WHEN** 用户查询超出其租户、项目或资源范围的会话
- **THEN** 系统返回安全的 not found 或 forbidden 响应且不泄露会话元数据

### Requirement: 历史内容在 MVP 中不可修改
系统 SHALL 将历史会话、消息、Agent 步骤、工具调用和 Delivery 作为审计只读数据展示；MVP MUST 不允许从管理页面编辑或删除这些记录。

#### Scenario: 用户查看历史消息
- **WHEN** 用户打开消息详情
- **THEN** 页面仅提供只读内容和关联信息，不提供编辑或删除动作

### Requirement: 附件页面安全展示元数据和处理状态
系统 SHALL 支持按会话、用户、文件类型、时间和处理状态分页查询附件，返回文件名、MIME、大小、对象存储引用摘要、提取状态和关联消息；响应 MUST 不包含对象存储凭据或无限期公开 URL。

#### Scenario: 查看附件详情
- **WHEN** 授权用户查看附件
- **THEN** 系统返回脱敏元数据、处理状态和安全文本预览（若已存在）
- **AND** 不因本页面访问而启动暂停中的 DOCX/XLSX/PPTX/Markdown 提取链路

#### Scenario: 附件超出权限范围
- **WHEN** 用户请求其无权访问的附件
- **THEN** 系统拒绝访问且不返回文件名、对象 key 或关联会话信息

### Requirement: Webhook 和 Delivery 运维事件可以关联查询
系统 SHALL 在运维页面提供 Webhook 事件、Agent Job、重试状态和 Delivery attempt 的关联查询，所有请求/响应摘要 SHALL 脱敏并受分页及大小限制。

#### Scenario: 排查钉钉消息未回复
- **WHEN** 运维用户从 Webhook 或会话事件进入详情
- **THEN** 系统允许沿事件、Job、重试和 Delivery 关联链路定位最终状态及安全错误摘要
