## MODIFIED Requirements

### Requirement: 失败处理必须路由到 retry 或 dead-letter
系统 SHALL 在 Worker 执行失败时根据结构化错误类型和已使用重试次数执行 retry 或 dead-letter 决策，并使 retry 消息在配置延迟后实际回到 Agent Job 主队列再次消费；状态、消息和审计 MUST 关联同一 Job 与 correlation ID。

#### Scenario: 可重试失败延迟后重新执行
- **WHEN** Job 出现可重试错误且未达到最大重试次数
- **THEN** 系统增加 retry metadata、将 Job 持久化为等待重试、发布带配置 expiration 的最小 retry 消息，并在消息到期后由 RabbitMQ dead-letter 回主队列供 Worker 再次 claim

#### Scenario: 不可重试失败进入 dead-letter 路径
- **WHEN** Job 出现不可重试错误
- **THEN** 系统将 Job 标记为 `FAILED`、发布 dead-letter 消息、记录安全失败原因并触发一次终态失败投递

#### Scenario: 重试次数耗尽进入 dead-letter 路径
- **WHEN** 可重试 Job 已使用全部配置重试次数
- **THEN** 系统不再发布 retry 消息，将 Job 标记为 `FAILED`、发布 dead-letter 消息并触发一次终态失败投递

#### Scenario: Retry 发布未被 RabbitMQ 确认
- **WHEN** 数据库已记录等待重试但 RabbitMQ publisher confirm 失败或连接中断
- **THEN** 系统记录可恢复的 retry dispatch failure，Job 不得被误报为成功，并能被滞留 Job 对账识别和重新调度

### Requirement: Docker Compose 必须可验证完整闭环
系统 SHALL 提供 Docker Compose 级验证方式，证明 `api-server`、PostgreSQL 18、RabbitMQ 4 Management 和 `agent-worker` 能协同完成成功 Job、真实延迟重试、dead-letter 和终态失败投递闭环。

#### Scenario: curl 验证成功闭环
- **WHEN** 使用 Docker Compose 启动服务并通过 curl 提交调试问题
- **THEN** 系统返回 `job_id`，Worker 经 RabbitMQ 4 消费后将 Job 更新为 `SUCCEEDED`，查询 Job 能看到最终诊断报告

#### Scenario: 验证 RabbitMQ 4 延迟重试回流
- **WHEN** 集成 smoke 首次触发可重试错误并配置短延迟
- **THEN** 测试观察 retry queue 入队、到期、dead-letter 回主队列、同一 Job 再次被 Worker claim，并最终成功或耗尽重试进入终态

#### Scenario: 验证 RabbitMQ 4 最终失败路径
- **WHEN** 集成 smoke 持续触发可重试错误直到次数耗尽或直接触发不可重试错误
- **THEN** Job 状态、retry count、dead-letter 消息、审计和一次安全失败 delivery attempt 保持一致

## ADDED Requirements

### Requirement: Agent Job retry queue 拓扑必须可延迟回流且可兼容升级
系统 SHALL 使用版本化 durable retry delay queue，并为其配置 dead-letter 到 Agent Job 主队列；系统 MUST NOT 使用不等价参数重新声明已经存在的无 DLX retry queue。

#### Scenario: 新部署声明 retry delay queue
- **WHEN** Publisher、Worker 或拓扑检查初始化 RabbitMQ 4 队列
- **THEN** 版本化 retry queue 带有指向主队列的 DLX/routing key，Publisher 按消息设置 expiration，且该延迟队列不需要消费者

#### Scenario: 旧无参数 retry queue 已存在
- **WHEN** 部署环境中已存在 durable `agent.job.retry.queue` 且没有 DLX 参数
- **THEN** 系统使用新版本队列名，不触发 `PRECONDITION_FAILED`，并在运维检查中报告旧队列消息数供对账

### Requirement: 滞留 retry Job 恢复必须显式、幂等且可审计
系统 SHALL 提供默认 dry-run 的恢复工具，识别旧实现遗留的等待任务；只有管理员显式应用后才能重新调度候选 Job，恢复过程 MUST 不默认 purge 旧队列。

#### Scenario: 管理员执行 dry-run
- **WHEN** 管理员运行滞留 Job 对账而未指定 apply
- **THEN** 系统只输出安全候选摘要和原因，不修改 Job、不发布消息、不删除队列消息

#### Scenario: 管理员显式恢复 Job
- **WHEN** 管理员确认候选并显式指定 Job 执行恢复
- **THEN** 系统幂等写入等待重试状态、发布到新拓扑并记录操作者、Job、前后状态和 publish 结果

#### Scenario: 同一 Job 被重复恢复
- **WHEN** 管理员或自动化重复提交已经恢复、运行或终态的 Job
- **THEN** 系统不重复调度可执行副本，并返回当前持久化状态和审计结果
