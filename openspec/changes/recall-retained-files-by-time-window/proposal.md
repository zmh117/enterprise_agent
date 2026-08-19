## Why

工作区按自然周到期后，聊天附件仍按约 360 天独立保留，但当前 Job 只冻结 ACTIVE 工作区里的文件。用户问「上周的图」时，Agent 只能在本周清单上按 `source_received_at` 筛选，于是把「当前工作区看不见」说成「没发过」。需要把**代码可解析的时段**做成绑定硬证据，让这一次 Job 的 Manifest 召回仍在保留期的精确版本，而不把旧工作区救活成 ACTIVE。

## What Changes

- File Context Resolver 增加时段硬证据：在既有「本条附件 → 引用 → 完整文件名 → 近指代」之后，若文字命中代码注册的时段词，且同时命中文件指代词，则绑定该时段内仍可访问的精确版本。不上隐式 LLM 日期分类器。
- 「上周 / 这周」按 Asia/Shanghai **自然周**（周一 00:00 含，下周一 00:00 不含），与工作区 `WEEK` 到期时钟对齐；另支持「上月 / 今天 / 昨天」和代码可解析的日历日期或日期区间。过滤字段 MUST 是 `source_received_at`。
- 召回范围：同一 Session、同一私聊或同群归属边界、聊天附件保留未到期。命中版本写入 **本 Job Manifest**，默认不自动物化；**MUST NOT** 把旧工作区改回 `ACTIVE`，也 MUST NOT 把历史文件重新 `link` 进当前工作区。
- 窗口内唯一且所需能力已就绪 → 可自动物化以便阅读；多份 → 澄清或只提供元数据，不得把整窗正文全部预加载。窗口为空 → 固定说明「该时段没有仍可访问的文件」，不让模型断言「没发过」。
- 正文已按保留策略清理、ID 仍在的版本：可进清单元数据；物化返回内容不可用，不得编造正文。
- 提交/编辑仍只落在当前 ACTIVE 工作区。历史召回项默认只读（元数据、按需物化、交付），不授予把修改写回已清理工作区的 COMMIT。
- File MCP `list_files` 继续只列出本 Job 快照（含历史召回项），不把「整段 360 天附件库」暴露给模型。调试用全量目录不在本 change 范围。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `channel-conversation`: 在确定性文件绑定中增加时段硬证据；无文件指代词的时间闲聊不得召回文件；空窗与多份歧义走系统说明。
- `execution-delivery`: Job File Manifest 可以包含「不在当前 ACTIVE 工作区、但仍在附件保留期内」的精确版本；自动物化仍只覆盖本轮绑定且能力就绪的条目。
- `task-file-workspace`: 区分「不恢复旧 ACTIVE 工作区」与「本 Job 只读召回保留附件」；历史项不占用把旧区救活的语义，提交仍打当前活动工作区。
- `builtin-tool-resource`: 快照内历史项可列元数据；内容已清理时物化返回稳定「内容不可用」；不得把空窗说成从未发送。

## Impact

- 主要改动在 File Context Resolver、`CreateAgentJobService` 准入、Job File Manifest 冻结（允许引用未挂在当前 `task_workspace_file` 上的保留版本）、File MCP 物化对 `CONTENT_UNAVAILABLE` 的错误码，以及固定中文系统说明。
- 不新增队列、进程或第二套文件表。召回查询走现有 `message_attachment` / `managed_file_version` / `file_retention_fact`。
- 若无活动工作区但时段召回命中，可为 File MCP 创建本周空的 ACTIVE 工作区作为 Job 容器，仍不把历史文件 link 进去。
- 测试：自然周「上周」、日历日、日期区间、无文件指代词不召回、空窗说明、多文件澄清、内容已清理只元数据、不恢复旧工作区、提交仍落当前区。
- 与仍未 archive 的 `decouple-document-readiness-from-agent-turns` 衔接：时段证据接在近指代之后；不削弱「无硬证据不绑文件」。
