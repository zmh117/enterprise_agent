# channel-ingress-contract Specification

## Purpose
TBD - created by archiving change add-channel-ingress-and-delivery. Update Purpose after archive.
## Requirements
### Requirement: Channel requests are normalized before Agent job creation
系统 SHALL 在创建 Agent Job 前将外部请求归一化为 Channel event，但 requester、业务应用发布、Connector binding 和 Execution Scope MUST 由服务端已发布绑定与身份解析产生，外部 payload 不得覆盖这些授权事实。

#### Scenario: Generic channel request is accepted
- **WHEN** 一个已通过 Connector 认证的请求包含有效事件 ID 和消息内容
- **THEN** 系统从 binding 解析身份、应用、范围和 Delivery，并创建隔离 Session、Job 与 Outbox

#### Scenario: Payload attempts to override scope
- **WHEN** 请求 payload 提交与 binding 不同的 user、application、environment、base 或 workshop
- **THEN** 系统必须拒绝或忽略越权字段，且不得扩大 Execution Scope

#### Scenario: Missing required channel fields
- **WHEN** 入口请求缺少事件 ID、消息或 adapter 必需字段
- **THEN** 系统拒绝请求、记录安全错误摘要，且不创建 Job 或 Outbox

### Requirement: Channel ingress is idempotent by external event identity
系统 SHALL 基于 Channel 类型、connector、外部事件 ID 和事件语义生成稳定幂等键，避免 webhook 重试创建重复 Agent job。

#### Scenario: Duplicate channel delivery is received
- **WHEN** 同一个 connector 重复投递相同外部事件 ID 的请求
- **THEN** 系统返回已有 Agent job acknowledgement，不创建第二个 Agent job 或第二条队列消息

#### Scenario: Different channel events use different idempotency keys
- **WHEN** 同一个 connector 收到两个不同外部事件 ID 的请求
- **THEN** 系统为两个请求创建不同幂等键并允许分别创建 Agent job

### Requirement: Grafana alert ingress only creates jobs for firing alerts
系统 SHALL 只为 Grafana `status=firing` 告警创建 Agent job；`resolved` 或其他状态 MUST 被忽略并审计。

#### Scenario: Grafana firing alert creates job
- **WHEN** Grafana webhook payload 的状态为 `firing` 且包含必填专用 routing labels
- **THEN** 系统创建 Agent job、持久化告警摘要并发布 `job_id` 到消息总线

#### Scenario: Grafana resolved alert is ignored
- **WHEN** Grafana webhook payload 的状态为 `resolved`
- **THEN** 系统返回 ignored acknowledgement、记录 `channel.grafana.ignored` 审计事件，且不创建 Agent job

### Requirement: Grafana routing uses dedicated Enterprise Agent labels
系统 SHALL 把 Grafana `ea_*` labels 作为告警分类和诊断元数据，但授权身份、业务应用发布和允许的 Execution Scope MUST 来自已发布 Webhook binding。Payload labels 不得选择任意应用或扩大 scope。

#### Scenario: Grafana labels match binding scope
- **WHEN** firing alert 的 `ea_*` labels 位于 binding 允许范围
- **THEN** 系统持久化安全告警摘要并使用 binding 固化的应用与 Execution Scope 创建 Job

#### Scenario: Grafana label exceeds binding scope
- **WHEN** alert label 指向 binding 未授权的 environment、base 或 workshop
- **THEN** 系统拒绝创建 Job 并记录范围不匹配

#### Scenario: Optional diagnostic label is missing
- **WHEN** alert 缺少非授权用途的诊断 label
- **THEN** adapter 可以按已发布 binding 的 schema 决定拒绝或记录缺失，但不得从 payload 猜测授权范围

### Requirement: Channel adapters verify source-specific authentication
系统 SHALL 在解析和持久化前认证来源。所有外部 HTTP Webhook MUST 使用各 binding 唯一的强 Bearer Token；DingTalk Stream 等非 HTTP Webhook Channel 继续使用其受支持的 Provider 认证。

#### Scenario: Valid Webhook Bearer Token
- **WHEN** 请求使用标准 `Authorization: Bearer <token>` 且与 binding 的平台 Secret 匹配
- **THEN** 系统继续解析、幂等和权限检查

#### Scenario: Invalid or missing credential
- **WHEN** Token、Provider credential 或 Connector ID 无效
- **THEN** 系统拒绝请求，且不持久化 Session、Job、消息或 Outbox

#### Scenario: Webhook binding has no resolvable Secret
- **WHEN** binding 的 Token Secret 缺失或禁用
- **THEN** binding 必须为 MISCONFIGURED，入口不得 fail open

### Requirement: Channel附件信封保护短期凭证
系统 SHALL 只在受控媒体下载边界使用附件短期来源凭证。为支持可恢复异步下载，系统 MAY 使用平台主密钥短期加密凭证并保存类型和过期时间，但 MUST NOT 持久化明文或把明文/密文写入RabbitMQ、日志、审计、API或调试输出；终态或过期后 MUST 清除密文。

#### Scenario: Adapter receives temporary media credential
- **WHEN** 外部payload包含下载附件所需的短期凭证
- **THEN** 数据库只可保存短期密文、类型和过期时间，其他持久化输出只保留内部attachment ID及安全来源摘要

### Requirement: Channel附件事件保持端到端幂等
系统 SHALL 将Channel、connector、外部事件、外部消息和附件序号纳入稳定幂等语义。

#### Scenario: Attachment event is redelivered
- **WHEN** connector重复投递同一附件事件
- **THEN** 系统返回已有确认且不新增message、attachment、对象或任务

### Requirement: 受管 Webhook 在进入 Channel 前固定来源配置
系统 SHALL 从已发布 Trigger 生成 Channel event，并 MUST 固定 Trigger publication、Agent publication、服务账号、routing policy 和 Delivery 引用后再调用通用 Channel ingress。

#### Scenario: 受管 Webhook 生成 Channel event
- **WHEN** Webhook event 通过认证、映射、过滤、幂等和服务账号权限预检
- **THEN** dispatcher 使用事件中固定的 publication 引用生成 Channel event 并创建 Agent job

#### Scenario: Trigger 在排队期间发布新 revision
- **WHEN** event 已进入 Inbox 后管理员发布新的 Trigger revision
- **THEN** 该 event 仍使用接收时固定的 Trigger 和 Agent publication，不读取新草稿或当前指针

### Requirement: 标准化 Channel event 不携带原始 Webhook payload
系统 SHALL 只把有界 message、受控 routing、来源标识和固定 reply route 交给 Channel ingress，MUST NOT 将完整原始 payload、认证 header、nonce 或 secret 写入 session、job、消息队列或 Agent prompt。

#### Scenario: 第三方 payload 包含敏感扩展字段
- **WHEN** Webhook body 除映射字段外还包含 token、URL、个人信息或大对象
- **THEN** 标准化 Channel event 排除这些未声明字段，只保留脱敏安全摘要

### Requirement: Channel入口在创建Job前解析业务应用路由
系统 SHALL 在完成 Channel event 规范化和外部身份解析后、创建 Agent Job 前执行受信 Business Application route 解析，并 MUST 将业务应用解析与用户业务 routing context 分开。

#### Scenario: 规范化事件命中业务应用
- **WHEN** 受信 Channel event 的部署环境、Trigger type、connector ID 和 routing key 命中活动应用
- **THEN** Channel ingress 使用解析得到的不可变应用运行快照创建 Job
- **AND** 用户消息或模型不能修改应用路由键

#### Scenario: 业务数据环境与部署环境不同
- **WHEN** 事件 routing context 包含 `environment=sanjiu` 且服务运行环境为 `local`
- **THEN** 应用解析使用 `local`
- **AND** Job 业务 routing context 仍包含 `sanjiu`

### Requirement: Channel入口执行明确的配置优先级
系统 MUST 在命中 Business Application 时采用应用 Publication 固定的 Agent 与已支持策略，并 MUST 在未命中应用时失败关闭，不得使用事件或默认 Agent 配置创建 Job。

#### Scenario: 应用和事件Agent一致
- **WHEN** 事件命中应用且两处 Agent 固定信息一致
- **THEN** 系统创建使用应用 Publication Agent 的 Job

#### Scenario: 应用和事件Agent冲突
- **WHEN** 事件命中应用但事件指定了不同的 Agent Publication
- **THEN** Channel ingress 阻止 Job 创建并记录配置冲突
- **AND** 不按事件值或默认值继续执行

#### Scenario: 未命中应用
- **WHEN** 路由结果为 `not_matched`
- **THEN** Channel ingress 不创建 Job 或发布 RabbitMQ 消息
- **AND** 请求向钉钉原会话发送安全配置错误

### Requirement: 应用会话上下文按业务应用隔离
系统 MUST 将命中的稳定 Business Application ID 纳入会话复用边界，并 SHALL 按应用 Publication 中已接线的 Session Policy 构造会话。

#### Scenario: 同一钉钉会话命中不同应用
- **WHEN** 两条事件具有相同外部 conversation ID 但命中不同 Business Application
- **THEN** 系统创建或复用不同的 Agent Session
- **AND** 两个应用的最近消息与会话摘要不相互泄露

#### Scenario: 同一应用升级Publication
- **WHEN** 同一应用激活新 Publication 后收到同一外部会话的新消息
- **THEN** 系统可继续复用该应用的会话
- **AND** 新 Job 单独保存新 Publication provenance

### Requirement: Channel入口对路由阻塞发送安全失败结果
系统 SHALL 将命中后的非重试配置错误交给已注册的 Channel 拒绝通知能力，MUST NOT 因失败通知异常而创建 Agent Job 或将配置错误改为可重试执行错误。

#### Scenario: 应用路由完整性失败
- **WHEN** Channel ingress 收到 `blocked` 路由结果
- **THEN** 系统记录路由失败并请求向原 Channel 发送安全错误
- **AND** 不创建 Job 或发布 RabbitMQ 消息

#### Scenario: 失败通知本身失败
- **WHEN** 原 Channel 失败通知无法送达
- **THEN** 系统记录独立 Delivery 或通知失败审计
- **AND** 不回退执行 Agent

### Requirement: 钉钉身份拒绝事件生成安全发现记录

系统 SHALL 在已认证且已持久化的钉钉 Channel event 明确因身份从未绑定、身份停用或解绑、或所属用户停用而拒绝时，幂等生成安全的未绑定身份发现记录，并 SHALL 保持拒绝响应、不创建 Agent session、Agent Job、user message 或 RabbitMQ Job 消息。

#### Scenario: 未绑定身份事件被拒绝

- **WHEN** 一个有效钉钉 Channel event 无法解析到任何历史外部身份
- **THEN** 系统 SHALL 在返回现有未授权结果前持久化安全发现记录，且不得进入 Agent 调度链路

#### Scenario: 历史身份不可用事件被拒绝

- **WHEN** 一个有效钉钉 Channel event 对应停用、已解绑身份或停用系统用户
- **THEN** 系统 SHALL 持久化可关联原人员的安全发现记录，且不得把身份解析为其它用户

#### Scenario: 重复拒绝事件

- **WHEN** 同一来源渠道事件因重试再次进入身份拒绝处理
- **THEN** 系统 SHALL 幂等确认已有发现记录，不得创建重复发现消息、Agent Job 或 RabbitMQ Job 消息

#### Scenario: 发现投影提交失败

- **WHEN** 系统无法在身份拒绝事务中安全提交发现投影
- **THEN** 系统 SHALL 保持 fail-closed、不得创建 Agent Job，并返回不含消息正文或敏感信息的可重试错误分类

### Requirement: 外部 Webhook 本次不得要求 HMAC 或 HTTPS
本地/Compose 阶段 Webhook 契约 MUST 只要求强 Bearer Token，不实现 HMAC、timestamp、nonce 或 HTTPS；运行边界必须标明仅限本地功能测试。

#### Scenario: Grafana 在本地 Compose 调用 HTTP
- **WHEN** Grafana 使用有效 Bearer Token 调用本地 HTTP endpoint
- **THEN** 系统可以正常处理，且验收不得将其表述为公网生产安全
