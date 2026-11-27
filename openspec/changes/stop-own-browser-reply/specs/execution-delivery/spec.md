# Spec Delta

## MODIFIED Requirements

### Requirement: Runtime取消与超时必须产生确定终态
系统 SHALL 先持久化 Job/Invocation 的取消意图，再通知原 Runtime；Worker 内存和一次 HTTP 通知不得作为唯一取消事实。Runtime MUST 将取消、墙钟超时、最大轮次和最大 Tool Call 映射为稳定错误码和 retry class，并最终只产生一个终态。管理端取消入口 MUST 校验 jobs.manage、目标 Job 的业务范围及适用的 CSRF。浏览器插件本人取消入口 MUST 只允许调用者取消本人从浏览器插件发出的任务，包括没有 `jobs.manage` 的普通用户，并校验插件凭据、平台来源、插件渠道、消息回执、会话与 Job 的发起人以及当前应用授权。两类入口 SHALL 复用同一任务取消流程并记录操作人和原因，目标执行实例由平台确定，调用方不得指定 owner、digest 或节点 URL。用户取消 SHALL 使用 FAILED + runtime_cancelled，执行超时使用 TIMEOUT + runtime_timeout，不增加业务重试。

#### Scenario: Worker取消运行中attempt
- **WHEN** Job 被显式取消或 attempt 超过固定墙钟时间
- **THEN** 持久化对应意图并通知原 Runtime；Runtime 中止 SDK 会话，保留可证明的事件并保存规范取消/超时结果
- **AND** 未确认本地执行停止时只报告处理中或结果不确定，不报告取消成功

#### Scenario: 取消与完成并发
- **WHEN** cancel 与 SDK completed 几乎同时发生
- **THEN** 终态先提交则取消返回已完成，取消意图先提交则阻止成功终态并收敛取消
- **AND** ledger 只接受一个终态，后续读取返回同一结果

#### Scenario: 取消尚未准入的任务
- **WHEN** Job 尚未创建 Invocation 或 Invocation 仍为 PREPARED
- **THEN** 取消与准备/领取原子互斥，取消先提交时 SDK 启动次数为零

#### Scenario: 取消通知丢失
- **WHEN** 取消意图已提交但 HTTP 通知失败
- **THEN** 原 Runtime 通过续租或控制轮询发现取消并执行清理，取消意图不丢失

#### Scenario: Worker正常退出或HTTP断线
- **WHEN** Worker 排空退出、被接管或 HTTP 流断开但没有显式取消/执行超时
- **THEN** 系统交接或恢复观察权，不因传输/消费者退出自动取消原模型执行

#### Scenario: 无权取消与重复取消
- **WHEN** 管理端调用者缺少管理权限、任一入口的调用者缺少目标业务权限，或同一受权取消请求重复提交
- **THEN** 无权请求被拒绝且不泄露目标；重复请求返回相同取消事实且不创建重复失败通知

#### Scenario: 普通用户停止本人插件任务
- **GIVEN** 用户有当前业务应用的使用授权，且没有 `jobs.manage`
- **WHEN** 用户从原平台通过插件请求停止自己发出的、具有匹配消息回执的任务
- **THEN** 平台以当前用户为操作人受理取消，已准入任务返回 `cancel_requested`，最终由任务快照或流确认结果

#### Scenario: 插件不能取消其他用户的任务
- **WHEN** 插件用户持有同一业务应用中另一位用户的 Job 标识并请求取消
- **THEN** 本人取消接口返回 404，目标任务的状态和取消意图保持原值

#### Scenario: 插件不能取消本人从其他渠道发起的任务
- **WHEN** 用户通过插件请求停止自己在调试入口或其他渠道发起的任务
- **THEN** 本人取消接口返回 404，目标任务的状态和取消意图保持原值
