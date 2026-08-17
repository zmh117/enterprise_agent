# 冻结版本化文本格式策略而不是扩大全局后缀白名单

任务文件格式能力采用代码注册且不可由管理端编辑的 `text-v1/text-v2` 策略。Business Application Publication、Job 路由事实与 Job File Manifest 冻结策略版本；Manifest 还冻结每个精确文件版本的规范化 format code 和允许操作。历史 Publication 缺失该字段时稳定解释为 `text-v1`，不会因代码升级追溯获得新格式能力。

`text-v1` 保持 TXT 全生命周期。`text-v2` 固定 TXT 全生命周期、LOG 只读及既有精确版本交付、Markdown 全生命周期；`.markdown` 不进入工作区。三者必须同时通过扩展名、允许 MIME、严格 UTF-8 内容与 15 MiB 上限校验。输入可带 UTF-8 BOM，Agent 输出禁止 BOM；NUL、无效 UTF-8 和二进制伪装失败关闭。Markdown 始终作为不可信纯文本存储与附件交付，不渲染 HTML、不解析链接、不抓取远程资源。

Python 与 TypeScript Runtime 都从 Runtime protocol v1.3 取得策略、format 和操作集合。Read/Glob/Grep 可作用于 TXT/LOG/Markdown，Write/Edit/Commit 只允许 TXT/Markdown；LOG 拒绝发生在文件系统或对象存储副作用前。File Service 在提交意图、上传接收和事务终结三处继续复核，不把 Job Snapshot 当作长期授权。

选择版本化策略是为了避免把 `.log` 的证据性只读边界降格为提示词，并防止旧 Publication、旧 Runtime 或旧 File MCP schema 被静默升级。启用 `text-v2` 前必须排空或隔离所有引用旧 File MCP schema hash 的活动、待重试 Job，发布声明 Runtime protocol v1.3 与当前精确 File MCP schema 的新 Agent/Application Publication。回滚通过激活新的 `text-v1` Publication完成，不删除已经创建的 Markdown 版本，也不把现有 `text-v2` Job 路由给旧 Runtime。
