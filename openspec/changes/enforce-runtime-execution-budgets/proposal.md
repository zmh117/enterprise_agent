## Why

当前 Python Runtime 在达到 `max_tool_calls` 后只拒绝单次工具调用，模型仍可继续循环直至墙钟超时；同时本地 `runtime_timeout` 被当作可重试错误，会从空白沙盒重复执行并最终落为 `FAILED`。这使冻结的执行预算不能形成可靠终止边界，也让大文件任务产生无效重试和重复物化成本。

## What Changes

- 当当前 attempt 已达到 `max_tool_calls` 时，拒绝下一次内部工具调用并立即以稳定、非瞬时的 `execution_policy_max_tool_calls_exhausted` 结束本次 Runtime，不再让模型通过连续被拒调用消耗剩余墙钟时间。
- 保留预算耗尽前已产生的安全工具事件，并将本次 attempt 的执行策略证据记录为 `exhausted=true`；超预算调用不得进入 ToolRegistry 或产生业务副作用。
- 将 Job 固定 `timeout_seconds` 导致的本地墙钟超时归类为终态超时：取消当前 SDK session、保留已有安全工具事件、直接把 Job 转为 `TIMEOUT`，且不进入自动重试。
- 增加 Runtime、重试服务和执行审计回归测试，覆盖工具预算边界、稳定错误码、无越界工具执行、超时不重试、`TIMEOUT` 终态及证据保留。
- 本次不调整 timeout 默认值或上限，不扩大 Job Sandbox，不跨 attempt 复用沙盒，也不引入日志专用提取工具。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `execution-delivery`: 明确内部工具调用预算耗尽必须终止当前 attempt，并明确由 Job 固定墙钟预算触发的本地 Runtime timeout 是不自动重试的 `TIMEOUT` 终态。

## Impact

- Python Runtime 的工具授权回调、SDK timeout 异常分类与安全工具事件传播。
- Job retry service 的重试判定和终态映射。
- Agent execution policy 使用量审计及相关单元/集成测试。
- 不涉及数据库 migration、外部 API schema、发布快照结构或文件工作区容量变化。
