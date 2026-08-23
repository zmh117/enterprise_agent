## Why

当前受治理文件链路存在几类会直接造成错误路由或延迟失败的实现偏差：机器协议时间被投影为上海时区、非法日期被解释成今天、保留文件查询可能在清理延迟期间放行过期内容，以及 Docling Profile 的必要依赖只在 Job 创建时兜底。需要在不改写既有 Runtime 1.2/1.3 协议语义、不新增 Job 终态且不追溯修改历史数据的前提下，使控制面和运行时共同 fail closed。

## What Changes

- 将 Job File Manifest、File MCP 和 Runtime 文件上下文的机器可读时间统一恢复为带时区的 UTC RFC 3339；Asia/Shanghai 只用于管理端展示和自然周期计算。
- 对显式但非法的日期或日期区间返回安全澄清，不再回退为当天，也不据此选择或绑定文件。
- 将时间窗口和非精确文件名匹配限制为最多 20 个不含正文的元数据候选；仅当前消息附件、引用消息、显式 File/Version ID 和完整文件名可以在 Agent 执行前形成内容依赖。
- 历史附件候选在每次查询时重新校验附件状态、文件/版本状态以及有效保留事实；清理 Worker 延迟不得扩大访问期。
- 当草稿选择 `docling-text-v1` 时，后端保存与发布校验同时要求任务工作区、File MCP、消息附件、连续会话、必要 File MCP Tool 子集以及兼容 Runtime 能力；管理前端选择 Profile 时自动联动同一组配置并展示缺失依赖。
- 修复受影响模块的静态检查问题并增加后端、前端和协议回归测试。
- 不修改 Runtime protocol 1.2/1.3 的版本号或字段含义，不新增 `INPUT_UNAVAILABLE` 等 Job 终态，不重放或回填历史 Job。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `task-file-workspace`: 明确机器时间、非法时间表达、候选选择和保留期查询的 fail-closed 行为。
- `business-application`: 将文档处理 Profile 的工作区、会话、工具和 Runtime 依赖前移到草稿保存与发布校验，并要求前后端联动一致。

## Impact

- 后端：文件时间序列化、Job 文件上下文解析、历史附件仓储查询、Business Application 组合校验和 Agent 文件提示。
- 前端：Business Application 组成配置中 Docling Profile 的联动与错误提示。
- 协议：保持现有 schema/version，不新增字段；只修正时间值和已有依赖的选择语义。
- 数据与运维：不新增 migration，不修改历史 Publication、Job、Manifest 或保留事实，不触发历史数据重处理。
