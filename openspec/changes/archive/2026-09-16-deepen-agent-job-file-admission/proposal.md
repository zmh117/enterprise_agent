## Why

Agent Job 创建路径目前分别在文件工作区、文件上下文解析和 Job 编排中判断文件输出意图、文件依赖、Task Workspace 需求与 Job File Manifest 绑定，调用方还需要理解 `TIME_WINDOW`、能力类型和候选数量等内部语义。该浅层 seam 已导致输出文件请求被时间词误绑定为历史附件的真实回归，因此需要在不改变任何用户可见行为的前提下，将本轮文件准入收敛为单一、可验证的决策。

## What Changes

- 引入一个 deep 的 Agent Job 文件准入 module，以当前消息事实、冻结的 Business Application Publication 文件策略和有界文件候选为输入，形成单一不可变准入结果。
- 将输出文件意图识别、文件来源绑定优先级、能力需求、Gate 结果、Task Workspace 需求、Manifest binding plan 与等待恢复事实集中到该 module。
- 让 Agent Job 创建、附件完成恢复和 File Service adapter 消费同一准入语义；保留 ingress 提供的输出意图 hint，但删除调用方向 resolver 与 Workspace 分别传递有效意图预判、解释 `TIME_WINDOW` 补建条件及重算 Manifest 自动物化规则的 seam。
- 增加覆盖 Agent Job 创建完整链路的行为冻结测试，并保留现有解析器、Gate、Manifest 与附件恢复回归测试。
- 严格保持现有文件意图词表、绑定优先级、中文通知、Job/非 Job 结果、Task Workspace 生命周期、Manifest schema v5、授权复检和时间窗口 `METADATA` 约束不变。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `task-file-workspace`：增加 Agent Job 本轮文件准入必须由单一不可变决策承载的架构与一致性要求；现有外部行为和安全语义不变。

## Impact

- 主要影响 `backend/app/modules/job/application/file_context.py`、`backend/app/modules/job/application/create_agent_job_service.py`、`backend/app/modules/attachments/service.py` 与 `backend/app/modules/file_workspace/manifest_service.py`。
- 测试影响文件上下文解析、Agent Job 创建、附件完成恢复和 Job File Manifest 冻结相关用例。
- 不新增数据库 migration、外部依赖或公开协议，不改变 Runtime、File MCP、Channel、Business Application 或 File Service 的对外契约。
