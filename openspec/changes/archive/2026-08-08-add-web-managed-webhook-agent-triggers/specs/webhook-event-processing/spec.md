## ADDED Requirements

### Requirement: 公共 Webhook 入口只接收有界 JSON 请求
系统 SHALL 通过不可预测的 `public_id` 解析已启用 Trigger publication，并 MUST 在处理前执行 HTTPS 部署约束、Content-Type、请求大小、JSON 结构深度和集合数量限制。

#### Scenario: 合法 JSON 请求
- **WHEN** 已发布 Trigger 收到符合上限的 `application/json` 请求
- **THEN** 系统继续执行该 Trigger 的认证和映射流程

#### Scenario: 超大或非 JSON 请求
- **WHEN** 请求超过配置上限或 Content-Type/JSON 结构不受支持
- **THEN** 系统拒绝请求、记录安全错误摘要且不创建 Agent job

#### Scenario: 未知 public ID
- **WHEN** 请求使用不存在或已轮换的 public ID
- **THEN** 系统返回统一拒绝响应且不泄漏 Trigger 是否曾经存在

### Requirement: Webhook 认证必须 fail closed 并支持防重放
系统 SHALL 支持 Bearer Token 和 HMAC-SHA256 认证，MUST 使用 secret reference 解析密钥并做常量时间比较；HMAC 请求还 MUST 校验时间窗和一次性 nonce。

#### Scenario: Bearer Token 验证成功
- **WHEN** Authorization header 中的 Bearer Token 与已发布配置引用的 secret 匹配
- **THEN** 系统记录认证成功并继续解析事件

#### Scenario: Secret 缺失或解析失败
- **WHEN** Trigger 的 secret 无法解析或请求未提供必需凭证
- **THEN** 系统拒绝请求且不得退化成匿名允许

#### Scenario: HMAC 请求被重放
- **WHEN** 相同 Trigger 在有效时间窗内再次收到相同 nonce
- **THEN** 系统拒绝重放、记录安全错误且不创建第二个 event/job

#### Scenario: HMAC 时间戳过期
- **WHEN** 请求时间戳超出已发布的允许时间窗
- **THEN** 系统拒绝签名，即使摘要本身匹配

### Requirement: 第三方 payload 通过声明式配置归一化
系统 SHALL 使用 Trigger publication 中的 typed adapter、JSON Pointer、声明式条件和有界模板生成内部 Channel event，MUST 将提取内容标记为不可信外部数据。

#### Scenario: 通用 JSON 映射成功
- **WHEN** payload 满足必填路径、类型、过滤条件和 routing allowlist
- **THEN** 系统生成有界 message、稳定 external event ID、受控 routing 和固定来源/投递引用

#### Scenario: 必填映射字段缺失
- **WHEN** payload 缺少事件 ID、消息或 Trigger 要求的 routing 值
- **THEN** 系统记录映射拒绝状态并且不创建 Agent job

#### Scenario: payload 试图覆盖控制字段
- **WHEN** payload 包含 Agent、工具、服务账号、Connector、secret 或 Delivery endpoint 字段
- **THEN** 系统忽略这些控制字段并只使用 Trigger publication 中的固定值

### Requirement: Grafana 只为 firing 告警创建一个 group 级事件
系统 SHALL 对 `grafana_alertmanager_v1` 只执行 `status=firing`，并 MUST 使用 `groupKey` 或稳定排序后的 fingerprints 表示一个告警组。

#### Scenario: Grafana firing group
- **WHEN** 一个已认证 firing payload 包含 groupKey 和多条 alerts
- **THEN** 系统创建一个 Webhook event 和一个 Agent job，并使用有界告警组摘要作为消息

#### Scenario: Grafana resolved group
- **WHEN** 一个已认证 payload 的状态为 resolved
- **THEN** 系统持久化或审计 `IGNORED` 结果、返回 ignored acknowledgement 且不创建 Agent job

#### Scenario: Grafana 重复发送同一 firing group
- **WHEN** 同一 Trigger 重试相同 groupKey/fingerprint firing 事件
- **THEN** 系统返回已有事件 acknowledgement，不创建第二个 job

### Requirement: 接收成功后通过持久化 Inbox 异步分发
系统 SHALL 在同一 PostgreSQL 事务中保存 Webhook event 和 outbox dispatch 记录，提交成功后 MUST 返回 `202 Accepted`，再异步创建 Agent job。

#### Scenario: Inbox 事务成功
- **WHEN** firing 事件通过认证、过滤、映射、权限预检和幂等校验
- **THEN** 系统保存固定 Trigger/Agent publication 引用并返回 event ID、correlation ID 和 `202 Accepted`

#### Scenario: RabbitMQ 临时不可用
- **WHEN** Inbox 已提交但首次 outbox 发布失败
- **THEN** 系统保留 `DISPATCH_PENDING` 状态并由恢复扫描器重试，不要求来源系统重新生成事件

#### Scenario: Dispatcher 重复收到 event ID
- **WHEN** RabbitMQ 重投递已经关联 job 的 Webhook event
- **THEN** dispatcher 返回幂等成功且不创建或执行第二个 job

### Requirement: Webhook 入口执行限流、并发和冷却策略
系统 SHALL 按 Trigger publication 执行请求速率、在途并发和相同事件冷却限制，并 MUST 在超限时避免创建额外 Agent job。

#### Scenario: 告警风暴超过速率上限
- **WHEN** Trigger 在配置窗口内接收数量超过发布上限
- **THEN** 系统返回限流响应、记录指标和安全摘要且不继续创建事件/job

#### Scenario: 不同 Trigger 同时接收事件
- **WHEN** 一个 Trigger 达到限流而另一个 Trigger 未达到自身限制
- **THEN** 系统只限制前者，不共享或扩大后者权限

### Requirement: 事件历史可审计且不保存原始 payload
系统 SHALL 保存 payload hash、受控提取字段、脱敏有界摘要、认证/过滤结果、Trigger/Agent publication、correlation ID、job ID 和安全错误，MUST NOT 保存或传播完整原始 body。

#### Scenario: 管理员查看成功事件
- **WHEN** 授权管理员打开 Webhook event
- **THEN** 页面展示来源、固定版本、映射摘要、job/tool/delivery 链接和状态，不展示原始 payload 或 secret

#### Scenario: 认证失败事件
- **WHEN** 已知 Trigger 收到无效凭证
- **THEN** 系统只记录 payload hash、大小、远端安全摘要和错误码，不记录正文

#### Scenario: 清理过期事件摘要
- **WHEN** Webhook event 超过配置保留期
- **THEN** 系统清理可删除摘要，同时保留 Agent job、审计和 Delivery 的独立事实记录
