## Why

任务文件工作区目前只允许 UTF-8 `.txt`，导致用户发送的诊断 `.log` 不能进入受治理工作区，也导致 Agent 无法创建、编辑、版本化和交付 Markdown 文档。需要在不扩大为任意文件系统或通用文档执行器的前提下，把现有文件闭环扩展为明确的文本格式矩阵。

## What Changes

- 保持 `.txt` 的上传、读取、创建、编辑、版本提交和精确版本交付能力不变。
- 允许用户发送 UTF-8 `.log` 进入任务工作区，由 Agent 在 Job Sandbox 内读取、Glob 和 Grep，并允许按既有精确版本原样交付；禁止 Agent 创建、编辑或提交新的 `.log` 版本。
- 允许 UTF-8 `.md` 进入任务工作区，并允许 Agent 在 Job Sandbox 内创建、读取、编辑、显式选择、提交不可变版本和交付。
- 三种文本格式继续执行安全相对路径、常规文件、无符号链接、UTF-8、二进制拒绝、15 MiB 单文件上限、工作区配额、Job Manifest、实时授权和两阶段流式提交约束。
- 两个 Runtime 使用同一格式策略和契约夹具；不开放 Shell、任意路径、目录扫描、任意扩展名、任意 MIME 或独立 `file-mcp` 服务。
- 更新窄范围的显式输出请求识别：只有明确要求 Markdown/`.md` 且包含创建、编辑或导出动作时，才为无既有工作区的请求启用文件能力；提及 Markdown 概念本身不触发写能力。
- **BREAKING**：引入新的冻结文件格式策略版本和对应 File MCP schema hash；既有 TXT-only Publication 与非终态文件 Job 不会被静默升级，启用 `.log`/`.md` 前必须完成兼容预检、排空旧 Job 并发布引用新策略和新 Tool schema 的 Agent/Application Publication。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `task-file-workspace`: 将 TXT-only 文件类型矩阵扩展为 TXT 全能力、LOG 只读证据、Markdown 全能力，并规定统一编码、配额、版本和交付边界。
- `business-application`: 让 Application Publication 冻结文件格式策略版本，并要求只有新发布版本才能启用扩展格式能力。
- `channel-conversation`: 允许 `.log` 和 `.md` 通过新任务工作区附件链路导入，同时保持纯附件暂存、真实内容校验和受限 File Worker 处理。
- `execution-delivery`: 扩展两个 Runtime 的 Sandbox 路径策略、文件工具权限、输出选择、提交与交付规则，并强制 `.log` 不可写。

## Impact

- 受影响代码包括 File Service 格式验证与流式服务、File MCP contracts、Job File Manifest、Channel/File Worker 附件分类、Python/TypeScript Runtime Sandbox 与文件传输桥、Agent 文件上下文和钉钉文件交付。
- 需要把现有 TXT 专用常量和验证器收敛为代码注册的封闭文本格式策略，避免各模块分别维护扩展名判断。
- 需要更新后端、两个 Runtime、MCP、File Worker、Delivery、Compose 合成验收和严格 OpenSpec 测试；不新增容器、数据库权限模型、MCP Server 或对象存储入口。
