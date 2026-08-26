## Context

Canonical `execution-delivery` 已规定真实 Claude Agent 必须受 Job 冻结的 `max_tool_calls` 与 `timeout_seconds` 约束，并规定 Worker 超时后进入 `TIMEOUT`。当前实现存在两处落差：

- `FixedMcpClaudeSdkClient` 的权限回调在第 `max_tool_calls + 1` 次请求时仅返回普通拒绝，且 `interrupt=false`，模型可以继续请求工具或继续推理，最终由墙钟预算兜底。
- `ClaudeSdkClient` 把自身墙钟监视器触发的 `asyncio.TimeoutError` 转为 `RetryableExecutionError(runtime_timeout)`；Python Runtime 协议将其投影为 `TRANSIENT`，Job retry service 因而重新创建空白沙盒执行，重试耗尽后又因异常类型而落为 `FAILED`。

这项修复横跨 Python Runtime 权限边界、Runtime 协议失败投影、Worker 重试与 Job 终态，因此需要一个端到端设计；不需要数据库或协议 schema migration。

## Goals / Non-Goals

**Goals:**

- 使 `max_tool_calls=N` 精确允许前 N 次受治理工具请求，并在第 N+1 次请求进入 ToolRegistry 前硬终止当前 attempt。
- 无论 Claude Agent SDK 如何包装权限回调的中断，都向控制面返回稳定的 `execution_policy_max_tool_calls_exhausted` 非瞬时错误。
- 将 Runtime 自身 Job 墙钟监视器触发的 `runtime_timeout` 与 provider/network transient timeout 区分，直接终结为 Job `TIMEOUT`，不自动重试。
- 保留终止前已经正规化的安全工具事件、Runtime 事件和执行策略耗尽证据。

**Non-Goals:**

- 不改变 Execution Policy 的默认值、可配置上限、Publication/Job 快照规则或既有 Job 的冻结策略。
- 不扩大 Job Sandbox，不跨 attempt 保留或复用沙盒，不改变 File Service 提交边界。
- 不为大日志引入解析器、分片编排、断点续跑或任意脚本执行能力。
- 不改变 provider/network、429/5xx、CLI transport 等真实瞬时故障的有限重试语义。

## Decisions

### 1. 复用单一 attempt 级工具预算守卫，并采用硬中断拒绝

每次 Runtime invocation 创建一个独立的 `ToolCallBudget`，权限回调收到每个 SDK 工具请求时先消费预算。前 N 次请求继续执行既有精确工具集、参数和沙盒授权；第 N+1 次请求先把守卫标记为耗尽，再返回带 `interrupt=true` 的策略拒绝，且不得调用 ToolRegistry 或文件工具授权后的副作用路径。

计数覆盖进入统一权限回调的所有工具请求，包括最终因工具集、参数或沙盒策略被拒绝的请求。这保持当前“attempted”安全预算语义，避免模型通过重复非法请求绕过总调用上限。`max_tool_calls=0` 时首个请求即触发耗尽。

替代方案是继续返回 `interrupt=false` 的普通拒绝，但它无法阻止模型继续循环，正是本次故障的放大因素。只调高 `timeout_seconds` 也不能建立工具预算终止边界。

### 2. 在 Claude client 边界规范化预算耗尽，避免依赖 SDK 异常形态

预算守卫保存明确的 `exhausted` 状态。权限回调发出硬中断后，`ClaudeSdkClient` 在 SDK consume 的成功、错误和包装异常路径上都优先检查该状态；一旦耗尽，统一抛出 `ExecutionPolicyExceeded`，使用稳定错误码 `execution_policy_max_tool_calls_exhausted`，并附带当前已收集的安全工具事件。

这样不依赖某个 Claude Agent SDK 版本是否原样传播权限回调异常，也不会把 SDK 的中断包装误判为 transport transient。不得为未观察到的 Tool 结果合成成功事件；执行策略的 `exhausted=true` 是预算终止的权威证据。

### 3. 用结构化超时类型和稳定错误码贯通 Runtime 到 Worker

只有 `_consume_with_cancellation` 自身墙钟监视器达到 Job 冻结 `timeout_seconds` 时，Claude client 才产生 `ExecutionTimeout(error_code=runtime_timeout)`。Python Runtime 将其投影为 `retry_class=NEVER` 的失败终态并保留工具/Runtime 事件；Runtime HTTP client 根据稳定错误码还原 `ExecutionTimeout`，不依赖中文消息或 Python 远端类名。

Job retry service 将 `ExecutionTimeout` 明确排除在可重试集合之外，并把该结构化异常或 `runtime_timeout` 稳定错误码映射为 Job `TIMEOUT`。provider/network 层的普通连接 timeout 仍先由既有错误映射归入瞬时故障，避免把外部抖动误判为 Job 预算耗尽。

替代方案是在 Job retry service 中仅按消息文本特判；该方案跨语言不稳定且容易把 provider timeout 混入，因此不采用。

### 4. 保持现有协议和存储结构，以端到端测试证明语义

现有 Runtime failure envelope 已包含 `code`、`retry_class`、`safe_message` 和工具事件，足以表达两类终止，不新增协议字段或数据库列。实现只调整错误分类与消费方映射：

- 工具预算耗尽：Job 仍为 `FAILED`，`retry_count` 不增加，错误码稳定，执行策略审计为 `exhausted=true`。
- 本地墙钟耗尽：Job 为 `TIMEOUT`，`retry_count` 不增加，错误码为 `runtime_timeout`，失败通知最多投递一次。

测试同时覆盖 Runtime 内部守卫、HTTP failure envelope/还原、Agent executor 证据持久化以及 Worker retry/终态，避免单层 mock 通过但跨进程语义漂移。

## Risks / Trade-offs

- [SDK 对 `interrupt=true` 的行为随版本变化] → 预算守卫状态由 Runtime 自己持有，consume 结束或报错后再次检查并规范化；增加当前 SDK 真实权限回调集成测试。
- [第 N+1 次请求可能没有完整 Tool 结果事件] → 不伪造结果，仅保留已经观察并正规化的事件，使用 `execution_policy_exhausted=true` 表达确定终止原因。
- [取消盲目重试会减少偶然成功机会] → 仅对 Runtime 自身冻结墙钟预算耗尽关闭重试；网络/provider 瞬时故障继续沿用既有有限重试。
- [部署期间新旧 Runtime/Worker 分类不一致] → 先部署兼容读取现有 failure envelope 的 Worker，再部署 Python Runtime；发布期间排空或停止领取新的长任务。

## Migration Plan

1. 先发布包含新 failure 映射与 Job retry/终态逻辑的控制面和 Agent Worker；它们仍能读取旧 Runtime envelope。
2. 再发布包含工具预算守卫和 `ExecutionTimeout` 投影的 Python Runtime。
3. 用受控 Job 分别验证 `max_tool_calls=1` 的第二次工具请求和短 `timeout_seconds` 的慢 SDK fixture，确认无重试、终态和审计证据。
4. 无数据迁移；回滚时按相反顺序回滚 Runtime 与 Worker。回滚会恢复旧重试行为，但不会修改既有 Job 的冻结策略或已产生终态。

## Open Questions

无。日志提取和大文件分段属于后续独立 change。
