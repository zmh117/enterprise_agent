## Why

源码 Grep 只能逐文件返回文件名，导致重复定位；纯代码问答没有可写笔记，容易反复分析。复用现有 Job 沙盒可保留阶段性结论并批量定位，仍保持 SVN 原文只读和证据可追溯。

## What Changes

- 代码问答精确派生 Write，仅允许当前执行 `work/notes/` 下 Markdown/TXT 笔记；已有文件 Job 权限独立保持。
- Grep 支持授权目录及文件名 glob，Runtime 从 SVN 受管文件中核验有界候选，生成临时 UTF-8 只读搜索副本，返回原路径、行号和受限上下文。
- 笔记不成为代码证据；命中仍需 Read 原源码取得证据 ID。搜索副本不作为独立源码快照，不跨 Job 共享或持久化。
- 同步冻结工具派生合同、提示词版本、安全审计和终态清理；保持 Read/Glob/Grep 免计轮次与工具总预算。

## Capabilities

### New Capabilities

无新增领域。

### Modified Capabilities

- `execution-delivery`: 代码任务临时笔记权限、批量源码检索与精确工具派生。
- `task-file-workspace`: 笔记和只读搜索缓存的预算、隔离、清理与证据边界。

## Impact

影响 Runtime 的源码守卫、读取器、JobSandbox、工具合同及提示词；需要协调更新控制面、Worker 与两个 Runtime。不增加服务、数据库表、MCP 工具或真实模型提取任务。
