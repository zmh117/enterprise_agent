## 1. 回归测试基线

- [x] 1.1 在 Python Runtime 测试中新增工具预算边界用例：`max_tool_calls=N` 时前 N 次请求沿用既有授权，第 N+1 次硬中断，`max_tool_calls=0` 时首个请求终止，且超预算请求不进入 ToolRegistry 或文件副作用路径。
- [x] 1.2 新增 Claude client 测试，覆盖 SDK 正常结束、原样抛错和包装中断三条路径，均将已耗尽预算规范化为 `ExecutionPolicyExceeded(execution_policy_max_tool_calls_exhausted)` 并保留此前安全工具事件。
- [x] 1.3 新增 Runtime failure envelope 与 HTTP client 测试，证明本地墙钟耗尽使用 `runtime_timeout`、非瞬时 retry class，并在控制面还原为结构化 `ExecutionTimeout`；provider/network transient timeout 仍保持可重试。
- [x] 1.4 新增 Worker/Job 测试，证明 `runtime_timeout` 不安排 retry dispatch、`retry_count` 不增加、Job 进入 `TIMEOUT` 且失败通知最多投递一次；工具预算耗尽仍为非重试 `FAILED` 并记录 `execution_policy_exhausted=true`。

## 2. Runtime 工具预算硬终止

- [x] 2.1 扩展并复用 attempt 级 `ToolCallBudget` 状态，在统一权限回调入口消费预算并记录耗尽；保持每次 Runtime invocation 独立、前 N 次请求的既有授权语义不变。
- [x] 2.2 将第 N+1 次工具请求改为 `interrupt=true` 的策略拒绝，并确保守卫检查发生在精确工具集、ToolRegistry、文件沙盒授权和任何业务副作用之前。
- [x] 2.3 在 Claude client consume 边界检查预算耗尽状态，以稳定的 `ExecutionPolicyExceeded` 覆盖 SDK 的普通完成或包装异常，并附带已观察到的安全工具事件，不合成未观察到的成功结果。
- [x] 2.4 在 Python Runtime outcome 中把工具预算耗尽投影为稳定错误码和非瞬时 retry class，同时保留 Runtime/工具事件及 Tool contract 证据。

## 3. Runtime 超时与 Job 终态

- [x] 3.1 将 `_consume_with_cancellation` 自身达到 Job 冻结墙钟预算的路径改为 `ExecutionTimeout(runtime_timeout)`，继续取消 SDK task、等待取消完成并保留已有安全事件。
- [x] 3.2 在 Python Runtime failure envelope 和 Runtime HTTP client 中增加 `runtime_timeout` 的非瞬时投影与结构化还原，不改变现有协议 schema。
- [x] 3.3 调整 Job retry service：`ExecutionTimeout` 不可重试，结构化异常或稳定 `runtime_timeout` 错误码均映射为 `TIMEOUT`；保留网络/provider 瞬时错误的现有有限重试。
- [x] 3.4 核对 Agent executor 的失败事件持久化，确保预算耗尽和超时都保留此前工具事件，且只有预算耗尽设置 `execution_policy_exhausted=true`。

## 4. 验证与交付证据

- [x] 4.1 运行 Python Runtime、Runtime HTTP client、Job execution policy、Agent worker 相关定向测试，并修复全部本变更回归。
- [x] 4.2 运行受影响模块的完整测试与静态检查，执行 `git diff --check`，确认无数据库 migration、协议 schema、Sandbox 容量或 Publication 快照变更。
- [x] 4.3 严格校验 `enforce-runtime-execution-budgets` OpenSpec change，并用受控测试 Job 验证 `max_tool_calls=1` 的第二次请求无越界执行、短墙钟任务无重试且终态为 `TIMEOUT`，记录可复核证据。
- [x] 4.4 更新部署说明，明确先发布兼容新失败映射的控制面/Agent Worker，再发布 Python Runtime，并说明既有 Job 策略保持冻结、无需数据迁移。
