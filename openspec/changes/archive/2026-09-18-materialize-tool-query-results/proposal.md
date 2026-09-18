## Why

Loki 查询上限只在服务端生效，Agent 无法提前获知；日志正文还会被 4000 字符摘要裁剪。数据库、Redis、Loki 查询结果应沿用 ONES 的 Job 临时只读结果文件模式，使模型按需读取完整的有界查询结果，而不是扩大上下文或绕过授权。

## What Changes

- 数据库查询默认 100 行、显式最多 10000 行；Redis 保留现有 GET/SCAN 和分页限制。
- Loki 资源默认 1000 行，新建/编辑最多 10000 行；时间配置最多 43200 分钟，默认 60 分钟与已有发布值不变。
- 资源目录暴露安全的有效限制；超限拒绝说明具体上限；区分达到行数上限与完整结果。
- 取消 Loki 正文 4000 字符裁剪，保留脱敏、响应字节限制和查询超时。
- 删除 Loki 资源的最大响应字节设置；统一采用代码级 8 MiB 上游响应保护，兼容忽略旧版本字段，不修改历史发布事实。
- 数据库/Redis/Loki 业务查询正文由 Runtime 写入 Job 只读临时 Markdown 文件，模型只接收有界元数据、路径与读取提示；复用 Sandbox 原子预算及终态/恢复清理，不自动持久化。
- 保留 sandbox-v2 标识和 Runtime 协议；单 Job 配额扩至 512 MiB/128 文件，work/outputs 合计 80 个，inputs 40/tmp 8/单文件 15 MiB 不变。容器 tmpfs 配套 1 GiB；新增迁移仅放宽快照配额 CHECK 并更新新行默认值，不改旧快照。

## Capabilities

### New Capabilities

无新增领域。

### Modified Capabilities

- `builtin-tool-resource`: 查询行数/时间配置、有效限制发现、查询完整性与有界正文返回。
- `task-file-workspace`: 将 ONES 临时只读结果机制扩展到 tool-mcp 业务查询，沿用隔离与清理。

## Impact

涉及 tool-mcp Provider、工具 schema/描述、Runtime MCP bridge 与派生 Read/Grep 权限、Web 资源表单、测试和运行说明。保持资源授权、固定 Loki 标签、SQL 只读/表范围、Redis namespace 不变；不新增通用数据库/Loki 分页，不修改 ONES Provider，不修改独立审计保留策略。新增 136 配额扩容迁移，历史快照值、hash、schema/version 不变。
