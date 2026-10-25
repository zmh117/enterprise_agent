## MODIFIED Requirements

### Requirement: Job 状态转换由 Worker 控制
系统 MUST 使用 `WAITING_INPUT`、`PENDING`、`RUNNING`、`RETRY_WAIT`、`SUCCEEDED`、`FAILED` 和 `TIMEOUT` 状态。Worker MUST 通过数据库原子领取、有效控制租约及递增领取版本取得 Job 推进权，并在首次模型调用或新 attempt 前复核当前用户、业务应用权限、Publication/hash、Runtime 与执行策略。只有控制租约到期或原 owner 显式交接，其他 Worker 才能接管 RUNNING Job；Broker redelivery 标记 MUST NOT 单独授予接管权。业务状态、重试、结果、助手消息和 Delivery Outbox 的写入 MUST 校验当前控制 owner/version；成功结果和终态时间 MUST 持久化，终态不得重新 claim。文件准入的 WAITING_INPUT 仅用于来源下载/导入，详见 task-file-workspace。仅在当前 Invocation 尚未准入且可靠延期已提交时，系统 SHALL 允许 RUNNING 返回 PENDING，不改变原 attempt。

#### Scenario: 排队期间权限被撤销
- **WHEN** Worker claim 前发现用户停用、成员到期或应用授权已撤销
- **THEN** Job 以非重试中文安全原因失败，不调用模型或工具

#### Scenario: 重复消息到达
- **WHEN** 两个 Worker 收到同一 PENDING 或到期 RETRY_WAIT Job
- **THEN** 只有一个取得有效控制权，另一个依据数据库状态和可靠恢复事实处理消息
- **AND** 已终态 Job 不重新执行、不重复生成成功结果或失败通知

#### Scenario: 文件提交部分失败
- **WHEN** 两个文件提交成功、一个冲突，但 Runtime 正常产出准确最终回复
- **THEN** Job 为 SUCCEEDED，各 Commit 独立记录结果，不新增 PARTIAL Job 状态

#### Scenario: 重投不能抢占活跃控制者
- **WHEN** 新 Worker 收到 redelivered 消息但旧 Worker 控制租约仍有效
- **THEN** 新 Worker 不覆盖 owner/version、不启动第二次执行，并保证后续观察机会持久化后才确认消息

#### Scenario: Worker接管与迟到提交
- **WHEN** 旧租约失效，新 Worker 取得更高领取版本，旧 Worker 随后提交结果或安排重试
- **THEN** 旧写入被拒绝；新 Worker 恢复原 Invocation，而不是创建新 attempt
- **AND** 结果、助手消息、Job 终态和逻辑 Delivery 意图只按当前控制版本幂等提交

### Requirement: 重试调度必须由数据库事实驱动
可重试执行失败 SHALL 原子保存 RETRY_WAIT、retry metadata、next_retry_at 与 retry dispatch 事实；Dispatcher 使用 durable 版本化延迟队列和消息 expiration，经 dead-letter 回主队列。重试不得改变 Job ID、原请求人、Publication、入口 routing context、冻结模型来源或 reply route；实际工具目标、Provider 身份与当前凭据仍按各自调用合同复核和解析。只有前一 Invocation 具有明确允许重试的失败终态且已确认停止，才 SHALL 创建新的 attempt。容量、会话或控制恢复延期 MUST 保持原 attempt/digest，不消耗业务重试次数。次数耗尽或确定性权限、参数、配置、只读策略拒绝 MUST 进入终态失败/dead-letter，不重新执行。Broker requeue 不得自行增加数据库业务 retry count；结果不确定或恢复正文过期 MUST NOT 自动重跑模型。

#### Scenario: 重试到期
- **WHEN** retry 消息从延迟队列回到主队列
- **THEN** Worker 以数据库 RETRY_WAIT、next_retry_at、前序终态和停止证据决定是否 claim，同一 Job 不产生并发 attempt

#### Scenario: 重试耗尽
- **WHEN** 瞬时错误达到 Job 重试上限
- **THEN** Job 为 FAILED，持久化根因与 retry_exhausted，最多创建一次安全失败 Delivery

#### Scenario: 业务重试已提交
- **WHEN** Worker 保存重试事实并正常返回 consumer
- **THEN** consumer 确认原消息，不再基于 Broker delivery 增加重试

#### Scenario: 明确失败后换节点重试
- **WHEN** 原 Invocation 已保存允许重试的失败终态且 SDK 已停止
- **THEN** 新 attempt 可以选择其他健康节点，但原 Invocation 的 owner、digest 和终态不变

#### Scenario: 网络错误未证明执行失败
- **WHEN** 请求超时或流中断但尚未取得可靠终态
- **THEN** Worker 查询归属并恢复原 Invocation，不以“未收到事件”为理由增加 retry_count

### Requirement: Runtime 与 Worker 必须隔离执行职责
唯一生产 Runtime SHALL 通过 FixedMcpClaudeSdkClient/ClaudeSdkClient 使用 Python Claude Agent SDK；公共编排只依赖 AgentRuntimeClient。Worker MUST 独占 Job claim、授权与快照校验、重试/业务终态、结果和安全事件持久化、Delivery Outbox 与 RabbitMQ ack。Runtime 只执行单次 attempt，不消费 RabbitMQ、不写 Job/Delivery 业务状态；它 SHALL 通过受限 Invocation/账本权限管理自身执行归属和终态。SDK/CLI 和模型明文凭据只存在所需 Runtime 边界，Worker 镜像不得包含 SDK/CLI；测试 stub 必须显式注入。

#### Scenario: Runtime 成功但本地提交失败
- **WHEN** Runtime 已 completed，而 Worker 的 Job/结果/Delivery 事务回滚
- **THEN** Worker 不错误 ack，并以相同 invocation/digest 恢复既有终态，不启动第二次模型执行

#### Scenario: Runtime 内部模块组装
- **WHEN** 系统装配请求边界、SDK、事件规范化、工具策略、文件桥与 Sandbox
- **THEN** 使用静态代码端口，不注册任意 Runtime/MCP URL、动态插件或 Worker 进程内 SDK

#### Scenario: 默认部署
- **WHEN** 当前 Compose 装配 Agent 执行链
- **THEN** 多个 Worker 通过同一 PostgreSQL、真实 RabbitMQ 和内置池客户端调用固定成员的 Python Runtime 池
- **AND** 对外业务入口保持统一，不提供其它 Runtime 实现或跨实现 fallback

### Requirement: Python Runtime必须实现版本化执行协议
当前 Runtime SHALL 为独立 python-v1 服务，新执行使用 protocol 1.5；Worker 与 Runtime 同时接受代码已实现的 1.4、1.5，不得协商或投影 1.0 至 1.3。请求 MUST 固定 invocation、attempt、request digest、Job/Publication/model revision 与 hash、执行限制、MCP bindings、correlation 和 schema v5 文件上下文。协议 schema、limits、errors 与 fixtures MUST 位于仓库级 contracts/agent-runtime/，Runtime 节点 URL 只能来自平台静态装配。池控制状态、最小恢复请求、取消、归属冲突和预期启动实例校验 MUST 有明确合同；物理选路和可刷新认证材料不得改写原执行请求摘要。

#### Scenario: 新执行使用 1.5
- **WHEN** Worker 构造当前默认 invocation
- **THEN** 请求、Runtime 健康声明和工具观测以 1.5 为当前版本，并校验 v5 Manifest

#### Scenario: 已固定 1.4 执行
- **WHEN** Job 合法冻结 protocol 1.4
- **THEN** 继续使用其已支持合同并遵守相同池归属规则，不伪造 1.5 完整审计或改写 Job 请求摘要

#### Scenario: 旧或非法合同
- **WHEN** 请求包含未知 Runtime、1.0 至 1.3、未知字段、超限内容、错误 digest 或非 v5 Manifest
- **THEN** Runtime/Worker 在模型和 MCP 调用前以稳定协议错误拒绝

#### Scenario: 流式事件
- **WHEN** 合法调用返回事件流
- **THEN** accepted 后的事件 sequence 连续且有界，最终只有一个 completed 或 failed 终态
- **AND** Worker 校验事件行数、字节、身份与唯一终态，拒绝超限或缺失终态

#### Scenario: 物理节点变化不改变逻辑请求
- **WHEN** PREPARED 请求改投另一候选节点或已完成执行从另一节点恢复
- **THEN** invocation/digest/冻结请求保持一致，实例校验通过控制合同完成

### Requirement: Runtime执行必须支持幂等终态恢复
Runtime MUST 以 invocation_id + request_digest 标识一次逻辑执行，并 SHALL 保存有界的安全终态与独立完整审计块以支持 Worker 断线或本地事务失败后的恢复。相同 invocation 与不同 digest 的请求 MUST 被拒绝，恢复不得启动第二次 SDK 执行链。运行中的恢复 MUST 定向不可变 node_id/instance_id；另一节点未在内存发现调用 MUST NOT 被当作孤儿证明。已完成终态 SHALL 可由任一合规节点基于持久化身份和有效 Grant 重放；所有恢复保留原事件内容与 sequence。

#### Scenario: Runtime完成后Worker提交失败
- **WHEN** Runtime 已产生 completed 终态但 Worker 的本地 Job 事务回滚
- **THEN** 原 Worker 或接管者使用相同 invocation/digest 获取既有终态并重新提交本地事务
- **AND** Runtime 不再次调用模型，读取既有终态不占新执行槽

#### Scenario: 重复请求摘要冲突
- **WHEN** 相同 invocation ID 携带不同 request digest 到达 Runtime
- **THEN** Runtime 返回不可重试的 digest conflict 且不复用或覆盖旧终态

#### Scenario: Runtime在模型执行中重启
- **WHEN** 原启动实例已替换或执行租约失效，恢复扫描再次检查仍没有可靠终态
- **THEN** 以条件事务保存并返回 runtime_invocation_outcome_unknown 不可自动重试终态，且不得再次调用模型
- **AND** 只有确认原本地执行已停止后，才允许操作者创建新 Job/invocation 显式重试

#### Scenario: 重连到非所属节点
- **WHEN** B 收到由仍在运行的 A 持有的 Invocation
- **THEN** B 返回安全的 owner mismatch，客户端使用部署映射定向 A
- **AND** B 不创建失败终态、不接管 SDK、不跟随任意响应 URL

#### Scenario: Worker在流读取时退出
- **WHEN** Worker 控制租约失效，而原 Runtime 执行租约有效
- **THEN** 接管 Worker 使用持久化冻结请求或最小恢复合同读取原流，不重新构建上下文或增加 attempt

### Requirement: Runtime取消与超时必须产生确定终态
系统 SHALL 先持久化 Job/Invocation 的取消意图，再通知原 Runtime；Worker 内存和一次 HTTP 通知不得作为唯一取消事实。Runtime MUST 将取消、墙钟超时、最大轮次和最大 Tool Call 映射为稳定错误码和 retry class，并最终只产生一个终态。取消入口 MUST 复用 jobs.manage、当前目标 Job 业务范围校验及适用的 CSRF，记录安全 actor/reason；不得接受调用者覆盖 owner、digest 或任意节点 URL。用户取消 SHALL 使用 FAILED + runtime_cancelled，执行超时使用 TIMEOUT + runtime_timeout，不增加业务重试。

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
- **WHEN** 调用者无管理或目标业务权限，或同一受权取消请求重复提交
- **THEN** 无权请求被拒绝且不泄露目标；重复请求返回相同取消事实且不创建重复失败通知

### Requirement: Runtime Grant必须绑定单次执行
Worker SHALL 为每个 attempt 签发短期 Runtime Grant，至少绑定 issuer、audience、authorized party、Job、invocation、Publication/hash、request digest、JTI 和 expiry。Runtime MUST 验证全部 claims 和重放状态，不得仅依赖私有网络位置。最小恢复/取消请求 SHALL 从受保护的持久化绑定校验身份，不要求重建原模型请求；恢复时可按当前平台访问授权重新签发短期 Grant，但不得改变原 digest、业务主体或执行截止时间。

#### Scenario: 有效Grant启动执行
- **WHEN** Grant 的 audience、Job、invocation、digest 和有效期与请求完全一致，且池准入和持久化状态允许
- **THEN** Runtime 允许该 invocation 原子进入执行

#### Scenario: Grant被重放或篡改
- **WHEN** JTI 已被不同摘要使用、Grant 已过期或任一绑定不一致
- **THEN** Runtime 在读取 Secret、调用模型或连接 MCP 前拒绝请求

#### Scenario: 接管者刷新恢复Grant
- **WHEN** 原 Grant 已过期且新 Worker 已取得有效 Job 控制权与读取权限
- **THEN** 新 Grant 只恢复同一 Invocation 的事件/终态，不延长执行、不重新访问模型或工具

### Requirement: Runtime必须提供无副作用健康与模型探针
Runtime SHALL 提供 health、ready、version 和受服务授权保护的模型 probe。健康检查 MUST NOT 调用模型或业务 MCP；模型 probe MUST 固定连接 revision/config hash、禁止 Tool、单轮、短超时且只返回脱敏结果。节点 SHALL 报告安全 node_id、instance_id、构建/协议身份、池能力、依赖就绪、排空和占用状态；真实 probe MUST 与新业务执行共用单个执行槽，普通健康和恢复控制接口不得占该槽。

#### Scenario: Readiness检查
- **WHEN** 编排系统调用 Runtime readiness
- **THEN** Runtime 报告协议、SDK、配置、Secret/DB 依赖和池节点的脱敏状态且不产生模型费用

#### Scenario: 模型连接Probe
- **WHEN** Python 服务提交通过 RBAC/SSRF 校验的固定模型连接 probe 且节点空闲
- **THEN** Runtime 使用 active Secret 完成无 Tool 探测并只返回版本、脱敏 host/model、耗时和稳定错误码

#### Scenario: Probe与业务执行竞争
- **WHEN** 节点正在执行 Job 或其他真实 probe
- **THEN** 新 probe 返回稳定 busy，真实 SDK 执行总数不超过一个，不在后台无限排队

## ADDED Requirements

### Requirement: Invocation必须先持久化准备再原子绑定执行实例
系统 SHALL 在模型执行前持久化不可变请求快照和 PREPARED Invocation，并以唯一 invocation_id 和唯一 job_id/attempt 防止重复身份。Runtime MUST 在取得本地唯一执行槽后，以短事务从未取消且未过准入期限的 PREPARED 转为 RUNNING，固定 node_id、instance_id、accepted_at、execution_deadline_at 和执行租约；仅事务提交成功者可启动 SDK。RUNNING owner MUST 不可转移，不得回退为 PREPARED；终态不得重新准入。状态或摘要不符时必须拒绝，不能收到 HTTP 请求就自动创建缺失身份。

#### Scenario: 两节点竞争同一调用
- **WHEN** A、B 同时收到相同 PREPARED Invocation
- **THEN** 只有一个节点取得持久化归属并启动 SDK，另一个释放本地槽并返回既有归属

#### Scenario: 领取后启动前崩溃
- **WHEN** RUNNING 事务已提交但进程在 SDK 启动前退出
- **THEN** 恢复按可能已开始处理，保守终结，不自动重新启动该 Invocation

#### Scenario: 迟到请求与节点重启
- **WHEN** 请求携带旧 instance_id 到达同 node_id 的新启动实例
- **THEN** 请求被拒绝并返回实例变化信息，原执行归属不被改写

### Requirement: Invocation冻结正文与执行标识必须保持恢复安全
系统 SHALL 在首次准备事务保存 canonical 请求及 digest，正文按受保护执行材料管理且不可编辑。接管、重连、容量延期 MUST 使用原冻结事实；认证材料 MUST 独立按当前授权签发，不进入正文快照、队列或普通日志。活动调用及未提交结果的恢复正文不得提前清理；Job 生命周期内必须保留不可再次执行的身份标识，即使大块终态正文已清理。

#### Scenario: 等待或接管期间配置及历史变化
- **WHEN** 新消息到达、Publication 指针改变或短期认证到期后恢复原 Invocation
- **THEN** 原 request digest、Prompt、Manifest 和模型来源不变，只有认证材料按合同刷新

#### Scenario: 恢复正文已过期
- **WHEN** 查询已终态身份但完整恢复正文已按策略清理
- **THEN** 返回 runtime_recovery_expired，不能把它当作未执行或创建新的 PREPARED

#### Scenario: 受控正文被普通路径访问
- **WHEN** 日志、消息队列、列表或无权调用请求冻结执行正文
- **THEN** 只返回允许的安全元数据或拒绝，不能返回 Prompt、原始业务内容或认证材料

### Requirement: 执行租约失效必须阻止迟到写入并保留停止证据
Invocation 续租、事件和终态写入 MUST 校验 owner 实例、当前状态和有效执行租约，使用数据库时间仲裁；过期 lease 不得自行续活。Runtime SHALL 在续租失败超过有效期或 deadline 到期时停止新增执行并中止 SDK。失联扫描和正常完成 MUST 原子竞争唯一终态；逻辑终态与本地执行停止证据 MUST 分开保存。缺少停止证据时不得复用节点槽、启动该 Session 后续任务或自动重跑原调用。

#### Scenario: 数据库断开后原进程恢复
- **WHEN** 原实例已失去 lease 并在数据库恢复后尝试续租、追加事件或覆盖终态
- **THEN** 条件写入拒绝，原实例停止 SDK，不能夺回执行权

#### Scenario: 租约超时但无法确认停止
- **WHEN** 平台已保存中断终态，却没有本地 SDK 停止或可信容器替换证明
- **THEN** 对应节点槽和 Session 保持安全阻塞，其他 Session 可使用其他健康节点
- **AND** 平台不宣称已撤销外部系统中可能在途的请求

#### Scenario: SDK不能在清理宽限内停止
- **WHEN** Runtime 在有界取消宽限后仍无法确认 SDK/子进程停止
- **THEN** 节点隔离并退出容器，经受管重启清理后以新 instance 接单，不只释放内存信号量

### Requirement: Runtime池必须有界准入并区分等待与执行重试
池客户端 SHALL 从静态配置的同发布健康节点中轮转选择新执行候选；每个 Runtime 进程的新执行/真实 probe 合计 MUST 不超过一个。满载、排空或无可用节点时 SHALL 返回稳定控制码并持久化有界延期；延期保持原 invocation/digest、业务 retry_count 和准入截止时间。运行中的重连、取消、终态读取不得等待新的执行槽。准入等待、实际执行和取消清理 MUST 有独立且不可被重连重置的截止边界。

#### Scenario: 三槽满载后第四任务进入
- **WHEN** 三个节点分别执行一个不同 Session 的任务，第四个任务就绪
- **THEN** 第四任务持久化等待，无第四条 SDK 执行，业务 retry_count 不变

#### Scenario: 延期与迟到接受交错
- **WHEN** Worker 尝试容量延期同时 Runtime 可能接受原 PREPARED 请求
- **THEN** 数据库条件事务确定实际状态；已 RUNNING 必须恢复原 owner，延期后的迟到领取仍只执行同一身份
- **AND** 不生成替代 Invocation，也不因丢失 HTTP 响应增加 attempt

#### Scenario: 等待期限耗尽
- **WHEN** 尚未准入的 attempt 到达冻结 admission deadline
- **THEN** 原子阻止迟到领取并以 TIMEOUT/runtime_admission_timeout 终结，最多生成一次失败通知

#### Scenario: 忙节点上的控制操作
- **WHEN** 原节点满载时收到重连、取消或已完成终态查询
- **THEN** 控制操作不申请新执行槽，能够在自身有界超时内处理

### Requirement: 池调度和恢复必须保留可靠消息与短事务边界
Agent Job consumer SHALL 保持每 Worker 一个在途 Job 和 prefetch=1，同时让连接 I/O 与 Job 续租独立于长时间模型调用。ACK/NACK MUST 在原连接/channel 的合法线程执行；ACK 前必须已持久化业务终态或可靠延期/恢复事实。现有 Dispatcher SHALL 有界扫描失去控制者的非终态 Job，并通过 Outbox 恢复同一 Invocation 的观察权；不得依赖单次 Broker redelivery 保证恢复，也不得通过立即重投形成热循环。

#### Scenario: 长模型调用期间维护心跳
- **WHEN** SDK 执行时间超过多个 Broker/Job 心跳周期且没有模型事件
- **THEN** 连接 I/O 和 Job 续租持续工作，prefetch 仍为1，没有第二个在途业务执行

#### Scenario: 控制者崩溃但没有可用重投
- **WHEN** Job 仍非终态且控制 lease 到期，Broker 没有再次投递
- **THEN** 有界扫描建立唯一的恢复调度，接管者恢复原 Invocation，不丢失观察责任

#### Scenario: 数据库无法保存延期
- **WHEN** Worker 无法提交延期或结果事务
- **THEN** 不 ACK 唯一消息，不在内存中假装已重新排队

#### Scenario: 运行期间数据库锁边界
- **WHEN** Worker 或 Runtime 等待模型、MCP 或 HTTP 事件
- **THEN** 不持有 Session/Job/Invocation 的跨网络事务锁，其他 Session 可以独立推进
