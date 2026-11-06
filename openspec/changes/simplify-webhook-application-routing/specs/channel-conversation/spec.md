## MODIFIED Requirements

### Requirement: Webhook Trigger 使用真实草稿和不可变发布
管理端 SHALL 提供通用 JSON 与 Grafana Trigger 的创建、编辑、校验、发布、启停及凭据轮换。新配置 MUST 只包含固定适配器、Bearer 引用与业务角色，MUST NOT 配置 Agent、投递、自定义映射或路由。保存草稿不改变运行版本；发布前检查启用来源、机器身份、可委派业务角色与唯一强 Bearer。

#### Scenario: 两人并发修改 Trigger
- **WHEN** 后提交者使用过期 expected revision
- **THEN** 返回冲突，不覆盖草稿或发布版本

#### Scenario: 独立发布入口
- **WHEN** 管理员配置合法认证和业务角色
- **THEN** Webhook 可以在尚未绑定 Agent 或应用时发布，实际请求仍须命中活动应用后才能执行

#### Scenario: 无副作用报文预览
- **WHEN** 管理员提交示例 JSON
- **THEN** 仅返回有界安全预览，不保存原 body、不创建 Job、不发送消息

### Requirement: Webhook 映射不能覆盖授权和目标事实
Webhook SHALL 只使用平台固定的通用 id/message 解析或 Grafana firing 告警解析；MUST NOT 接受自定义变量、模板、过滤与路由规则。外部消息是非可信内容，不能覆盖机器身份、角色、应用、Agent、Tool、Connector 或投递目标。

#### Scenario: 通用 JSON 缺少字段
- **WHEN** id 或 message 缺失、为空或类型不合法
- **THEN** 请求被拒绝，不创建 Job

#### Scenario: payload 声明权限或目标
- **WHEN** 请求包含 actor、Agent、角色、资源或投递覆盖字段
- **THEN** 系统拒绝未声明字段，不扩张授权，也不把原 payload 写入 Prompt

### Requirement: Webhook 持久受理与业务授权分阶段完成
系统 SHALL 在认证、报文和限流校验后解析唯一活动应用，并原子固定 Trigger、应用和 Agent Publication 到事件与 Outbox，返回 202 仅表示受理。Dispatcher MUST 重新检查入口、机器身份、当前应用路由与角色授权；路由版本变化时拒绝，不静默替换事件版本。

#### Scenario: 排队期间发布新应用
- **WHEN** 事件固定的应用版本与当前活动路由版本不同
- **THEN** 事件明确失败，不以新 Agent 或投递配置执行

#### Scenario: 排队期间账号或入口停用
- **WHEN** Dispatcher 检查发现机器身份或入口停用
- **THEN** 不创建 Job，记录安全失败原因

#### Scenario: Broker 故障或重复消息
- **WHEN** Outbox 首次发送失败或重复分发已有关联 Job 的事件
- **THEN** 通过有界重试或幂等成功恢复，不重复创建 Job
