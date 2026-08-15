## Why

当前系统能接收并保存聊天附件，但缺少可跨连续追问使用的任务级文件上下文、不可变版本、受控编辑沙盒和统一文件生命周期。需要建立由 File Service 管理的文件事实中心，让 Claude Code Agent 能在隔离 Job 沙盒中安全处理文件，同时保持身份、权限、审计、MinIO 凭据和钉钉交付边界。

## What Changes

- 新增任务工作区、文件、不可变文件版本、Job 文件清单、冲突候选、保留文件和文件提交意图等领域能力。
- 新增 `file-service`，同时提供内部 REST API 和受治理 File MCP 接口，并作为 PostgreSQL 文件元数据及 MinIO 对象操作的唯一事实入口。
- 以 `file-worker` 替换现有 `attachment-worker`，兼容原附件队列，并承担附件导入、工作区过期、内容保留和提交暂存清理；现有 Delivery Worker 继续负责渠道交付。
- 第一阶段仅为新的任务工作区链路支持 UTF-8 `.txt`，单文件最大 15 MiB、每个工作区最多 20 个逻辑文件和 100 MiB 临时内容；现有聊天附件兼容能力继续保留，`docling-serve` 延后到下一阶段。
- Business Application Publication 新增并冻结 `DAY`、`WEEK` 或 `MONTH` 任务工作区保留策略，默认 `WEEK`，按 Asia/Shanghai 自然周期计算，不因活动滚动延期。
- 私聊工作区归当前内部用户；群聊工作区由同一受信群会话共享，但每次调用仍复核实际发送人的身份、应用访问和同群边界，不复制钉钉逐成员 ACL。
- Agent Job 创建时冻结精确 Job 文件清单；本次消息附件自动物化，其他文件由 Agent 按需选择，文件访问权限在调用时实时复核。
- 文件元数据明确区分平台收到原始聊天附件的 `source_received_at`、精确版本产生的 `version_created_at` 和本次查询边界 `observed_at`，使 Agent 能可靠判断“最近一小时上传”等相对时间请求；不得继续用含义模糊的 `created_at` 冒充上传时间。
- **BREAKING**：允许 Claude Code Runtime 只在单 Job 沙盒内使用 `Read`、`Glob`、`Grep`、`Write` 和 `Edit`，替代当前“所有文件修改工具一律禁用”的规范；Bash、Web、沙盒外路径和其它开放执行能力仍保持拒绝。
- 文件提交使用显式、两阶段、流式和严格幂等的提交协议；File Service 校验 Job、工作区、基础版本、类型、大小、哈希、编码和配额后才创建不可变版本，冲突不覆盖也不自动合并。
- 钉钉中明确修改或生成文件默认提交并把成功的精确版本作为新钉盘文件交付回当前会话；提交、Job 和 Delivery 使用独立状态与重试语义。
- 消息附件默认保留 360 天；工作区临时内容按 Publication 冻结周期清理；明确保存或成功交付的精确版本按独立平台或租户文件内容保留策略默认保留 360 天。
- **BREAKING**：File MCP 作为部署固定的第二类专用 MCP Server，接受平台签发的短时 Principal JWT；该 JWT 只携带主体、Job、Publication 和精确 scope，不携带 MinIO 凭据。File Service 在基础设施层解析平台 Secret Reference。

## Capabilities

### New Capabilities

- `task-file-workspace`: 定义任务工作区、文件与版本、Job 文件清单和沙盒、两阶段提交、冲突、配额、保留、清理及 File Service 事实边界。

### Modified Capabilities

- `business-application`: 在应用草稿、发布快照、前端和解析结果中加入冻结的任务工作区自然周期保留策略。
- `channel-conversation`: 扩展 `.txt` 消息附件导入、私聊/群聊工作区归属、360 天附件保留以及 File Worker 兼容处理规则。
- `execution-delivery`: 增加 Job 文件快照、隔离沙盒、受限文件工具、显式提交结果和精确文件版本交付语义。
- `builtin-tool-resource`: 允许代码固定的 File MCP Server 使用 Principal JWT，并保持精确 Tool Manifest、Job scope、Secret 隔离和任意 MCP 地址拒绝。
- `platform-operations`: 增加 `file-service`，以 `file-worker` 替换 `attachment-worker`，并纳入 Secret、Compose、健康检查、迁移和端到端验收。

## Impact

- 后端：新增文件工作区域模型、仓储、服务、内部 API、File MCP、Principal JWT scope、Outbox/队列和清理状态机；调整附件处理、Job 创建、Runtime 编排和 Delivery。
- Runtime：Python 与 TypeScript Runtime 增加 Job 沙盒物化、受限文件工具、流式上传桥、显式提交和终态清理；现有 32 MiB tmpfs 与全局写工具 deny 需要受控调整。
- 数据与存储：新增 PostgreSQL 表及索引、MinIO 受控对象前缀和暂存对象；历史附件只补齐到期事实，不在 migration 事务中删除对象。
- 控制面：Business Application 草稿、Publication、管理 API 和前端增加任务工作区保留策略；平台或租户级文件内容保留策略独立治理。
- 部署：净新增 `file-service` 一个容器，`file-worker` 替换 `attachment-worker` 并继续消费原附件队列；不新增独立 `file-mcp` 容器，不部署 `docling-serve`。
- 安全：MinIO Access Key/Secret Key 只在 File Service 基础设施层解析，Agent、Runtime、JWT、MCP 参数/响应、Job、日志和审计均不得接收原始凭据。
