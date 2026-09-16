## 部署范围

本变更不新增数据库 migration、环境变量、外部服务或持久化索引，也不改变 64 文件、224 MiB、单文件 15 MiB、最多 40 个 inputs 与 16 个 work/outputs 的 Job Sandbox 边界。

受影响组件：

- 控制面与 Agent Worker：需要接受新的 Runtime 派生 Tool 合同、`agent-system-prompt-v3` 合同身份与安全 Tool 事件摘要。
- Python Runtime：提供进程内 `scan_log_evidence`、证据包生命周期、Sandbox 完整性检查和提示约束。
- File Service：不新增远端 Tool；其 `tools/list` 出现 `scan_log_evidence` 反而会触发同名冲突并失败关闭。

证据包只是当前 Job Sandbox 中的只读中间文件，不会自动选择、提交或交付。用户要求报告时，Agent 仍需另写 Markdown，并显式执行 `select_sandbox_output` 和 `file_create_commit_intent`。

## 发布顺序

1. 暂停领取新的大日志任务，或等待在途长任务结束。
2. 先构建并发布控制面和 Agent Worker，使其先能记录新 Tool 合同与事件投影。
3. 再构建并发布 Python Runtime；不得让新 Runtime 长期搭配旧 Worker。
4. 创建新的 Agent Revision，确认冻结的 File Tool 集包含 `file_prepare_materialization`，并按需要调整 `timeout_seconds` 后发布。
5. 创建新的 Business Application Revision，绑定上一步的新 Agent Publication，发布并激活目标环境。
6. 用新会话创建新 Job，执行受控的大日志扫描与显式报告提交验证。

如果现场仍使用 300 秒：本次约 200 MiB 合成扫描核心耗时约 25 秒，但模型核验、报告生成和提交仍共享 Runtime 墙钟，因此应按现场模型与日志密度留出余量。提高有效超时必须同时新建并发布 Agent Revision 与 Business Application Revision；只改 `.env`、只重启容器、只改旧 Publication 或直接改既有 Job 快照都不会可靠改变已冻结策略。

## 发布后验证

- File MCP 合同观测为 `MATCH`，并出现来源为 `runtime_derived`、依赖为 `file_prepare_materialization` 的 `scan_log_evidence`。
- 对约 20×10 MiB 已物化 UTF-8 LOG 发起一次扫描；确认输入/扫描字节相等、`coverage_complete=true`、证据包不超过 4 MiB，且没有重复物化。
- Tool 事件只包含计数、hash、限制与稳定错误码；不得出现字面词、路径、原始片段、证据正文、凭据或对象位置。
- 让 Agent 生成独立 Markdown 报告，确认只有显式选择和提交后才产生 Commit/Delivery；`delivery_status=PENDING` 只能声称已排队。
- 以真实 Job 终态、Tool 合同、扫描覆盖和 Commit/Delivery 证据判定成功；容器 `healthy` 只表示进程就绪，不是批次成功。

## 回滚

1. 停止新的大日志 Job。
2. 先回滚 Python Runtime，再回滚 Agent Worker 与控制面。
3. 新建并发布不暴露扫描器的新 Agent 与 Business Application Revision，再激活目标环境。
4. 保留已完成或失败 Job、文件版本、Commit 和 Delivery 记录，不改写历史快照。

没有数据库或对象存储数据回滚步骤。Sandbox 证据包随 Job Runtime 清理；已显式提交的报告属于正常 File Service 版本，是否保留按既有文件生命周期处理。
