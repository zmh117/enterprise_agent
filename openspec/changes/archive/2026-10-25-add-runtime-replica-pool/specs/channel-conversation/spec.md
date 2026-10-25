## MODIFIED Requirements

### Requirement: 连续上下文有界且摘要失败可降级
系统 SHALL 只读取 Job 所属 Session 的最近消息与滚动摘要，排除本轮重复输入和 attachment_intake 消息，并遵守消息数、摘要和总字符预算。当前默认摘要器是确定性的有界消息摘录，不额外调用模型。摘要更新 MUST 使用版本与 sequence 游标并发控制；失败时使用受限最近窗口，不阻断当前 Job。首次冻结执行上下文 MUST 在取得 Session 头部执行资格后完成，包含前序 Job 已提交的可见结果，排除后续排队 Job 的输入；同一 Invocation 恢复使用原冻结正文，不重读最新历史改写摘要。

#### Scenario: 用户追问前一轮
- **WHEN** 同一允许 Session 中的头部 Job 构建上下文
- **THEN** 获得带发送人归属的前序已提交消息或摘要，不混入其他 Project、私聊或 Session

#### Scenario: 私聊请求人不匹配
- **WHEN** Job requester 与私聊 Session requester 不同
- **THEN** 拒绝上下文读取，不返回摘要或消息

#### Scenario: 历史超过预算或摘要失败
- **WHEN** 会话消息超出预算或摘要推进异常
- **THEN** 按配置裁剪并保留截断状态，降级到最近窗口；完整文件表示不直接拼接进会话上下文

#### Scenario: 后续输入早于前序回复入库
- **WHEN** 同一 Session 的 A 正在执行，B、C 的输入先后排队，而 A 的回复稍后才提交
- **THEN** B 冻结上下文时能读取 A 的回复，不能读取 C 的后续输入
- **AND** 不用消息 sequence 小于 B 输入这一单独条件错误排除 A 的回复

#### Scenario: 接管期间新增历史
- **WHEN** 原 Invocation 已冻结请求，新 Worker 接管时会话又新增消息
- **THEN** 原执行仍使用同一冻结请求和 digest，不因接管改变模型可见上下文

## ADDED Requirements

### Requirement: 同Session任务必须按输入顺序串行执行
系统 SHALL 在既有完整 Session 隔离边界内，按输入消息 sequence 和 Job ID 的稳定顺序决定头部任务。Dispatcher SHALL 避免发布明显不具备资格的后续任务，Worker MUST 在短事务中原子复核头部资格。前序 WAITING_INPUT、RUNNING、RETRY_WAIT 或未确认本地停止的 Invocation MUST 阻止后续执行。只有前序结果/助手消息/终态已持久化且本地执行已停止，后续任务才能进入模型执行；不同 Session SHALL 可由不同 Runtime 并行处理。

#### Scenario: 两个Worker竞争同一会话
- **WHEN** 两个 Worker 分别收到同一 Session 的相邻 Job
- **THEN** 只有头部任务取得执行资格，后续任务持久化等待，不占用 Runtime 槽或长期持有数据库锁

#### Scenario: 不同会话并行
- **WHEN** 两个完整隔离键不同的 Session 均有就绪头部任务且有空闲节点
- **THEN** 两个任务可以在不同 Runtime 同时执行，不建立全局会话锁

#### Scenario: 前序等待文件或业务重试
- **WHEN** 头部处于 WAITING_INPUT 或未到期 RETRY_WAIT
- **THEN** 后续任务不能越过；输入和等待超时由相应有界策略收敛，不能无限占据 Worker

#### Scenario: 前序终结后唤醒下一条
- **WHEN** 前序成功、明确失败或取消的结果已提交且本地执行已停止
- **THEN** Outbox 唤醒下一条，周期扫描可补偿丢失的唤醒，不依赖进程内回调

#### Scenario: 逻辑失败但停止不确定
- **WHEN** 前序已标记 FAILED，但原 Invocation 没有可信停止证据
- **THEN** 本 Session 保持阻塞并报告安全原因，其他 Session 不受其互斥影响

#### Scenario: 群聊中不同外部身份
- **WHEN** 同群消息因现有完整隔离键归属于不同 Session
- **THEN** 分别执行会话内串行规则，不扩大为整个群或 Connector 的全局串行
