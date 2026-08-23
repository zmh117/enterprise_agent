## Context

当前文件工作区把 `.txt` 规则分散在 File Service validator、File MCP schema、Manifest 过滤、Python/TypeScript Runtime Sandbox、输出选择器、Agent prompt 和测试中。canonical 与代码都把任务工作区限制为 UTF-8 TXT；Markdown 只存在于旧附件抽取链路，`.log` 不在允许格式中。直接把多个 `endswith(".txt")` 改为宽松扩展名集合会导致两个 Runtime 漂移、旧 Publication 行为被追溯扩大，以及 `.log` 被模型改写后仍被误认为原始诊断证据。

本变更沿用 File Service 唯一事实入口、Job File Manifest、短时 Principal JWT、Runtime tmpfs Sandbox、两阶段流式提交和精确版本 Delivery，不新增容器或第二个文件入口。

## Goals / Non-Goals

**Goals:**

- 提供代码注册、版本化、失败关闭的文本格式策略：TXT 全能力、LOG 只读、Markdown 全能力。
- 让 Channel、File Service、Job Snapshot、两个 Runtime 和 Delivery 对格式及允许操作得到同一结论。
- 保留 UTF-8、15 MiB、工作区配额、路径隔离、幂等提交、版本冲突和实时授权边界。
- 让旧 TXT-only Publication/Job 保持原冻结语义，并通过显式发布切换到新策略。

**Non-Goals:**

- 不支持 `.markdown`、Office、PDF、图片、压缩包或任意文本扩展名进入任务工作区。
- 不允许 Agent 创建、编辑、提交或伪造 `.log`；不提供日志追加、tail、索引或外部日志采集。
- 不渲染 Markdown、不执行内嵌 HTML、不抓取远程资源，也不引入 `docling-serve`。
- 不增加格式级 RBAC、管理员自定义 MIME/扩展名、独立 `file-mcp`、共享宿主机目录或 MinIO 直连。

## Decisions

### 1. 使用封闭且版本化的文件格式策略

平台 SHALL 定义不可由管理端编辑的 `text-v1` 与 `text-v2`：`text-v1` 保持现有 TXT-only 语义；`text-v2` 固定 `.txt=READ/CREATE/EDIT/COMMIT/DELIVER`、`.log=READ/DELIVER_EXISTING`、`.md=READ/CREATE/EDIT/COMMIT/DELIVER`。策略以规范化 format code、扩展名、允许声明 MIME、内容类型、最大字节和操作集合表达，不以任意字符串或前端配置表达。

选择该方案而不是全局扩展名常量，是为了让 `.log` 的不可写边界能够贯穿 Manifest、Runtime 和 File Service，并能审计使用了哪个策略版本。选择版本化策略而不是直接改变现有 TXT 语义，是为了避免旧 Publication 在无新发布的情况下获得新增文件能力。

### 2. Application Publication 与 Job 冻结策略，调用时继续复核

Business Application Publication SHALL 冻结 `file_format_policy_version`；旧 Publication 缺失时稳定解释为 `text-v1`。只有显式发布的新 Application Publication 才能使用 `text-v2`。Job Snapshot 和 Job File Manifest SHALL 冻结同一策略版本、每个条目的规范化 format code 与允许操作摘要；File Service 在物化、提交和交付时仍按当前代码支持、精确版本归属和实时授权复核，不把快照当作长期授权。

新策略需要与支持该策略的 Agent Runtime protocol 和 File MCP Tool schema hash 同时通过发布校验。任何版本/hash 不匹配都在 Job dispatch 或外部 I/O 前失败关闭。

### 3. MIME、扩展名和内容必须三方一致

三种格式均只接受不超过 15 MiB 的 UTF-8 文本；输入可以包含 UTF-8 BOM，Agent 新输出不得包含 BOM，NUL、无效 UTF-8、GBK、UTF-16 和二进制内容必须拒绝。`.txt` 接受 `text/plain`；`.log` 接受 `text/plain`，并只在真实内容通过严格文本验证时兼容上游声明的 `application/octet-stream`；`.md` 接受 `text/markdown` 或 `text/plain`。扩展名、允许 MIME 与内容探测任一冲突都失败关闭。

Markdown 始终作为不可信纯文本存储和传输；File Worker、File Service、管理端和 Delivery 不渲染、不解释 HTML、不解析链接。`.markdown` 继续留在旧附件兼容链路，不进入 `text-v2` 工作区。

### 4. Runtime 按操作授权，而不是只按路径后缀授权

Python 与 TypeScript Runtime 的 `Read`、`Glob`、`Grep` 可以作用于当前 Job Manifest 已授权的 `.txt/.log/.md` 常规文件；`Write`、`Edit` 和 `select_sandbox_output` 只允许 `.txt/.md`。对 `.log` 的写入必须在文件系统副作用前拒绝，即使路径仍位于 Sandbox 内。

Manifest schema 与 Runtime protocol 需要携带 format policy version、format code 和允许操作，并由语言无关 schema 生成两端类型；跨 Runtime 契约夹具必须对相同路径、MIME、BOM、NUL、符号链接、大小和操作产生等价结果。不得只靠 prompt 告知模型 `.log` 只读。

### 5. 只有 TXT/Markdown 可以创建提交意图

`select_sandbox_output` 与 File MCP commit schema SHALL 接受安全相对 `.txt/.md` 文件，并把 format code 绑定到不透明 sandbox handle 和 Commit Intent。修改既有文件时，新版本必须保持原 format code 和逻辑扩展名；不得把 `.log` 改名为 `.txt/.md` 后作为原日志的新版本提交。File Service 在接收流和终结事务中再次校验策略、handle、格式、编码、大小、基础版本和配额。

`.log` 只能交付 Manifest 中当前获授权的既有精确版本；交付不会创建新版本或改变内容。TXT/Markdown 的新提交继续支持 `DEFAULT` 自动交付和 `WORKSPACE_ONLY`。

### 6. 显式 Markdown 输出触发保持窄范围

无现有工作区时，平台只有在消息同时包含 Markdown/`.md` 格式标记和创建、生成、编辑、保存或导出动作标记时，才可预启用任务文件能力。仅讨论 Markdown、要求在聊天中使用 Markdown 排版或提及日志分析不自动授予写能力。用户发送受支持附件时仍按纯附件暂存与后续文字认领流程创建工作区。

## Risks / Trade-offs

- [旧 File MCP schema hash 与新代码不一致] → 切换前枚举非终态、待重试和可恢复文件 Job，排空或显式隔离；要求新 Agent/Application Publication 引用新 hash，禁止自动替换旧快照。
- [上游把 `.log` 声明为通用二进制 MIME] → 只对白名单扩展名兼容 `application/octet-stream`，仍执行 UTF-8、NUL、大小和真实内容校验。
- [Markdown 被前端或外部系统主动渲染] → 平台只以附件交付并标记不可信文本；本变更不新增预览或 HTML 渲染面。
- [两个 Runtime 对 Glob 或绝对路径归一化不一致] → 使用同一协议 schema 和参数化契约夹具，分别执行真实权限回调测试。
- [格式规则继续散落] → 以单一策略 registry 为事实源，旧 TXT helper 只可作为迁移兼容层并最终删除，禁止调用方自行判断后缀。

## Migration Plan

1. 先增加 `text-v2` 策略、Manifest/Runtime protocol 新版本和兼容读取；`text-v1` 继续默认，入口不接受新格式。
2. 更新 File Worker、File Service、两个 Runtime、File MCP schema、Agent上下文和 Delivery，并完成跨语言/负向测试。
3. 预检并排空或隔离所有引用旧 File MCP schema hash 的非终态、待重试和可恢复 Job；确认旧 Publication 仍解析为 `text-v1`。
4. 发布支持新 Runtime protocol 与 File MCP schema 的 Agent Publication，再发布冻结 `text-v2` 的 Business Application Publication，按应用灰度启用。
5. 使用合成 `.txt/.log/.md` 完成 Channel→File Worker→File Service→Runtime→Commit/Delivery 验收，确认 `.log` 写入在副作用前拒绝。

回滚时停用 `text-v2` Application Publication并恢复上一个 `text-v1` Publication；已经创建的 Markdown 版本继续按保留策略只读保存和交付，不删除对象或改写历史。回滚不得把新 Job 路由到不理解其冻结策略的旧 Runtime。

## Open Questions

- 无；格式矩阵、编码、大小、`.log` 只读和 `.md` 全生命周期已由用户确认。
