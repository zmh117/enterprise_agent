## ADDED Requirements

### Requirement: Dashboard 提供权限裁剪的聚合概览
系统 SHALL 提供单一 Dashboard 只读查询，返回当前用户有权查看的用户、启用 Agent、Channel、当日任务和异常事件摘要，并标明统计窗口和生成时间。

#### Scenario: 管理员查看全局概览
- **WHEN** 具备全局管理权限的用户打开 Dashboard
- **THEN** 系统返回全局范围内的汇总卡片和统计窗口

#### Scenario: 范围受限用户查看概览
- **WHEN** 仅具备部分项目或基地权限的用户打开 Dashboard
- **THEN** 系统只聚合其授权范围内的数据
- **AND** 不通过数量差异泄露未授权资源的存在

### Requirement: Dashboard 展示 Agent 任务和 Delivery 运行状态
系统 SHALL 展示最近 24 小时或显式选择窗口内的任务状态分布、重试等待、最终失败、超时、Delivery 失败和最近异常任务，并允许跳转到有权限的只读详情。

#### Scenario: 存在失败任务
- **WHEN** 统计窗口内存在失败或超时任务
- **THEN** Dashboard 返回按状态汇总的数据和脱敏后的最近异常任务引用

### Requirement: Dashboard 展示队列和入口事件摘要
系统 SHALL 展示 Agent 主队列、重试队列、死信队列及相关 Webhook/附件处理队列的消息数、消费者数、采集时间和可用性状态，并展示最近 Webhook 事件和会话入口活动。

#### Scenario: RabbitMQ 管理数据不可用
- **WHEN** Dashboard 无法读取 RabbitMQ 管理状态
- **THEN** 系统将队列区域标记为 unavailable 并返回安全错误摘要
- **AND** 其他 Dashboard 区域仍可正常展示

### Requirement: Dashboard 不执行隐式外部连接测试
系统 SHALL 使用数据库状态、审计、队列管理读模型和已有健康快照构建 Dashboard，MUST NOT 在每次页面刷新时解析 Secret 或主动连接数据库、Redis、Loki、钉钉等外部系统。

#### Scenario: 用户刷新 Dashboard
- **WHEN** 用户刷新概览页面
- **THEN** 系统只执行受控只读聚合查询，不触发资源连接测试或外部消息发送
