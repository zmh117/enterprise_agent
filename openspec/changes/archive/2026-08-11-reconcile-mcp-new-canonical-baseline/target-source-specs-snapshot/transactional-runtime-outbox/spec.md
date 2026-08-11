# transactional-runtime-outbox Specification

## Purpose
TBD - created by archiving change stabilize-platform-runtime-foundation. Update Purpose after archive.
## Requirements
### Requirement: Job 创建与 dispatch event 必须原子持久化
系统 MUST 在同一个 Unit of Work 中持久化 Agent Job 与唯一的 Job Dispatch Outbox event，API 不得在数据库提交后直接依赖一次 RabbitMQ publish 保证投递。

#### Scenario: Job 事务提交成功
- **WHEN** 入口请求成功创建 Job
- **THEN** Job 与对应 PENDING Outbox event 必须同时可见

#### Scenario: Job 事务回滚
- **WHEN** Job 创建事务失败
- **THEN** Job 和 Outbox event 必须都不可见，且不得发布 RabbitMQ 消息

### Requirement: Outbox Dispatcher 必须提供 at-least-once 发布
Dispatcher SHALL 以多副本安全方式领取到期 event，并在 RabbitMQ publisher confirm 后记录发布结果；系统 MUST 允许重复消息但不得丢失已提交 event。

#### Scenario: 发布后确认前 Dispatcher 崩溃
- **WHEN** RabbitMQ 已接收消息但 Dispatcher 尚未提交 published 状态即崩溃
- **THEN** event 可以再次发布，消费者必须用持久化幂等键避免重复业务副作用

#### Scenario: 多个 Dispatcher 同时运行
- **WHEN** 多个 Dispatcher 轮询同一批到期 event
- **THEN** 数据库领取机制必须避免它们同时拥有同一次处理权

### Requirement: Agent 执行与 Delivery 必须使用独立状态机
Agent Job 的 `SUCCEEDED` MUST 只表示 Agent 已产生并持久化结果；外部投递必须由同事务创建的 Delivery Outbox 驱动，Delivery 失败不得改变 Job 成功状态或重跑 Agent。

#### Scenario: Agent 成功但 DingTalk 暂时不可用
- **WHEN** Job 已保存结果并进入 SUCCEEDED，Delivery adapter 返回瞬时错误
- **THEN** Delivery 必须进入自身的 RETRY_WAIT，Job 保持 SUCCEEDED

#### Scenario: Delivery 最终进入 DEAD
- **WHEN** Delivery 已耗尽最大重试次数
- **THEN** Delivery 必须进入 DEAD 并保留安全错误与审计，Agent Job 不得重新执行

### Requirement: Outbox 与 Delivery 消费必须端到端幂等
Job dispatch、Delivery attempt 和 Delivery chunk MUST 使用稳定唯一键及原子状态转换，重复 RabbitMQ 消息不得产生重复 Agent 成功结果或重复成功投递。

#### Scenario: 同一 Delivery event 被重复消费
- **WHEN** 两个消费者先后收到同一 Delivery event
- **THEN** 已成功的 attempt/chunk 不得再次发送，重复消息被安全确认

### Requirement: 运维恢复必须显式、有限且不可改写 payload
系统 SHALL 提供只读状态/指标及按 event、job 或 delivery 精确定位的 CLI replay；MUST NOT 提供任意 payload replay、无限重试或本次 Web 运维页面。

#### Scenario: 运维重放 DEAD delivery
- **WHEN** 授权运维人员使用 CLI 指定一个 DEAD delivery ID
- **THEN** 系统校验当前状态、记录审计并创建一次有次数上限的重放

#### Scenario: 运维提交自定义消息体
- **WHEN** CLI 请求用任意 payload 替换原事件内容
- **THEN** 系统必须拒绝该请求

### Requirement: Outbox 切换必须一次完成且删除精确旧拓扑
切换期间 MUST 停止相关 Worker/Dispatcher、排空或幂等转换待处理记录并隔离无法转换的记录；切换后不得长期双写旧新路径。

#### Scenario: 旧消息拓扑确认已排空
- **WHEN** 旧 queue/exchange/binding 无消息且无消费者
- **THEN** 维护操作可以按精确名称删除旧拓扑、配置和代码

#### Scenario: 存在无法转换的旧消息
- **WHEN** backfill 无法确定某条旧消息的幂等身份或目标
- **THEN** 该消息必须进入隔离清单并阻止宣告切换完成
