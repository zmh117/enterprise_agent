## 部署范围

本变更同时影响控制面/Agent Worker 与 Python Runtime：

- 控制面/Agent Worker：读取 `runtime_timeout`、还原结构化超时、禁止该错误自动重试并将 Job 转为 `TIMEOUT`。
- Python Runtime：工具调用预算硬中断、本地墙钟超时分类、failure envelope 的非瞬时投影。

不涉及数据库 migration、Runtime 协议 schema、Publication/Job 快照结构或 Sandbox 容量。既有 Job 继续使用创建时冻结的 `max_tool_calls`、`max_turns` 和 `timeout_seconds`。

## 发布顺序

1. 停止领取新的长任务或等待在途长任务结束。
2. 先发布控制面和 Agent Worker，使其能够按稳定错误码识别新旧 Runtime 返回的 `runtime_timeout`。
3. 再发布 Python Runtime，使新的 invocation 使用工具预算硬中断和非瞬时 timeout envelope。
4. 恢复领取任务并执行下述受控验证。

不得只更新 Python Runtime 后长期保留旧 Worker；否则 Worker 可能仍把 timeout 终态解释为普通失败。无需重新发布 Agent 或 Business Application 才能获得错误分类修复，但调整 `timeout_seconds` 等策略仍必须按既有 Publication 流程发布，并且只对新建 Job 生效。

## 发布后验证

### 工具预算

创建一个仅允许安全只读测试工具、有效 `max_tool_calls=1` 的新 Job，让测试提示触发第二次工具请求：

- 第一次请求按既有授权执行。
- 第二次请求不得进入 ToolRegistry，Runtime 返回 `execution_policy_max_tool_calls_exhausted`。
- Job 不重试，终态为 `FAILED`，`execution_policy_exhausted=true`。

### 墙钟超时

在非生产测试应用中创建一个使用短 `timeout_seconds` 且确定会超过该预算的新 Job：

- Runtime 取消当前 SDK session并返回 `runtime_timeout`。
- Job 的 `retry_count` 不增加，不创建 retry dispatch，终态为 `TIMEOUT`。
- 已观察到的安全工具事件仍可查询，失败通知最多投递一次。

验证完成后恢复测试应用的正常 Execution Policy。不要通过修改既有 Job 快照进行验证。

## 回滚

按相反顺序回滚 Python Runtime，再回滚控制面/Agent Worker。没有数据回滚步骤；已经进入 `FAILED` 或 `TIMEOUT` 的 Job 保持终态，既有冻结策略和文件版本不变。
