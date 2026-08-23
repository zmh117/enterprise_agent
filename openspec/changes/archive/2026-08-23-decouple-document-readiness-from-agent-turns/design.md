## Context

当前 checkout 已经把 PDF/Office/图片导入 File Service，并用独立 `file-processing-worker` 调 `docling-serve` 写 Markdown 表示。卡住用户的不是处理车道，而是准入：

1. `claim_staged_attachments()` 把同一 Session/工作区下全部 `job_id is null` 的附件挂到下一条非空文字的 Job 上。
2. `_release_if_ready()` 和 readability 对账把 `readability_status=PENDING` 视为继续 `WAITING_INPUT`。
3. 门禁失败时走 `enqueue_job_failure`，用户看到 `agent_runtime_error` JSON。
4. 钉钉引用只把被引正文拼进 prompt（`_agent_input_message`），`originalMsgId` 没有进入 Job 命令，无法绑定文件。
5. File MCP 没有稳定的「表示未就绪」错误码；`file_get_metadata` 也不投影可读性。

并行的 `add-governed-docling-file-representations` 仍把「认领文档后 Job 等待表示」写成 Requirement。本设计是该准入模型的修正，不重做处理管线。Canonical 基线里「第一条后续文字认领全部未消费附件」同样要改。

约束：不新增 chat-orchestrator 进程、不新增文件表家族、不把 Docling 暴露给模型、Secret/正文不得进入日志和工具 JSON。系统说明必须走现有钉钉 `sessionWebhook` Markdown，而不是失败 JSON。

## Goals / Non-Goals

**Goals:**

- 每条用户文字独立决定本轮 `file_version` 依赖和能力；处理状态只挂在精确版本上。
- 无关问答在 Docling 运行时仍能创建并执行 Agent Job。
- 需要正文但表示未就绪或失败时，用固定中文说明结束本轮，不调用模型、不占用 `agent.jobs`。
- 用确定性 Resolver 绑定文件；File MCP 作为第二道失败关闭闸。
- 曾被挡轮次在表示就绪后最多通知一次，不自动重放。

**Non-Goals:**

- 不引入隐式 LLM 分类器、向量检索、`SEARCH_INDEX` 或 chunk/embedding 队列。
- 不新建 `fs_file_*`、独立 File API、chat-orchestrator、file-index-worker。
- 不改 Docling profile、异步 convert、staging 发布、Manifest v4 表示字段或 Compose 拓扑。
- 不把 `WAITING_INPUT` 从渠道来源下载场景里删除。
- 不自动重放被挡问题，不在每次上传完成时发解析通知。

## Decisions

### 1. Resolver 和门禁放在 CreateAgentJobService 之前的应用步骤，不新建进程

在 `CreateAgentJobService.create()`（及同消息附件+文字路径）进入 Job 持久化之前调用 `FileContextResolver` + `FileCapabilityGate`。纯附件继续走现有 `stage_attachments()`，不跑 Resolver。

未选择独立 chat-orchestrator：渠道入站已经是 channel → create job / stage attachments，再拆进程只增加拓扑和身份边界。未选择让 Agent 先启动再自己判断：未就绪轮次根本不该进模型。

### 2. 绑定只认四条硬证据，能力与绑定分开

Resolver 输出 `dependencies: [{version_id, attachment_id?, required_capability, reason}]`。顺序：

1. 当前命令 `attachments`
2. `quoted_external_message_id` → 同 Session `agent_message.external_message_id` → 该消息附件对应版本
3. 用户文字中出现工作区 `display_name` 规范化全等且唯一（Unicode NFC + 大小写折叠后仍要求完整显示名含扩展名）
4. 代码注册近指代词（至少覆盖「这个文件/这个表/刚才那个/上面的附件/这张图/该文档」）且工作区 `last_source_ready_at` 最新的唯一版本

没有第 5 条「刚传完就问延期任务」。`file_references` 若渠道将来填了精确 ID，插入为与第 1 条同级的显式绑定。

能力：小封闭模式表（中英）映射 `METADATA` / `ORIGINAL`；其余已绑定默认 `READABLE_CONTENT`。模式表放代码常量，不放 Publication 可配。

未选择分类器：误绑会挡住无关问题；漏绑只是多一轮澄清。

### 3. 认领 API 改为「本轮绑定集合」，废除整包 update

`claim_staged_attachments(session, workspace, job, attachment_ids)` 只更新传入 ID。未传入的保持 `job_id is null`。工作区候选不依赖「已被文字消费」；自动物化只看本轮绑定且能力就绪。

同消息附件在创建用户消息时写入，是否挂 `job_id` 由门禁决定：需要等待来源导入时才挂到 `WAITING_INPUT` Job；未就绪直接系统说明时不挂 Job。

### 4. WAITING_INPUT 只覆盖来源导入；表示未就绪走系统终结

`_release_if_ready()` 不再把 `readability_status=PENDING` 当作继续等待的条件。来源终态后：

- 依赖为空或不需要 `READABLE_CONTENT` 且原件可用 → `PENDING` 并 finalize Manifest（自动物化不含未就绪文档）
- 需要 `READABLE_CONTENT` 且 PENDING → 投递系统说明，Job 以 `file_capability_not_ready` 安全终结，**delivery_kind 为 `system_notice`**，不得写 `failure_notification` JSON
- 需要 `READABLE_CONTENT` 且失败终态 → 同样系统说明，错误码 `file_processing_failed`

无 Job 的门禁失败（文字到达时来源已入库、表示仍 PENDING）：不创建 Agent Job，直接走 Session 级 `system_notice` Outbox（复用现有 Delivery 适配器和 reply route 快照，不强制 `job_id`）。若现有 Delivery 表以 Job 为外键，允许创建一个立即终结、从不入 `agent.jobs` 的占位 Job，但对外投递语义必须是系统说明而不是 Agent 失败。优先无 Job 路径；占位 Job 只在投递模型无法脱离 `job_id` 时使用，并在设计评审实现时二选一写死。

**实现选择（锁定）**：扩展 Delivery Outbox，允许 `job_id` 为空但必须绑定 `session_id` + 冻结 reply route 的 `system_notice`。这样管理面不会出现假失败 Job。被挡事实单独落表，不依赖 Job。

### 5. 引用目标与最近活动是现有事实上的投影，不造文件平台

- 入站把 `originalMsgId` 写入 `CreateAgentJobCommand.quoted_external_message_id`，并写入当前 `agent_message.safe_metadata`（或专用列，若 metadata 不便查询则加可索引列 `quoted_external_message_id`）。用现有 `agent_message(session_id, external_message_id)` 反查。
- 最近活动：来源导入成功时更新工作区条目或附件上的 `source_ready_at`；Resolver 读最新一条。不维护独立 `active_file` 表。

### 6. 被挡轮次用窄表，就绪通知复用 processing 完成钩子

新增 `file_readiness_blocked_turn`：`id, session_id, workspace_id, user_message_id, file_version_ids, reason_code, status(OPEN/NOTIFIED/EXPIRED), created_at, expires_at, notified_at`。不含正文。窗口固定 24 小时或工作区结束（先到为准）。

`reconcile_attachment_readability` 在表示变为 AVAILABLE/PARTIAL 后，除现有（将删除的）WAITING_INPUT 释放外，扫描 OPEN 且包含该 `version_id` 的被挡行，写 `system_notice` Outbox，状态改为 NOTIFIED。不创建 Agent Job。

未选择自动重放：用户可能已换话题，重放会打乱回复顺序。

### 7. File MCP 收口错误码，列表暴露有界状态

`prepare_materialization` 在无冻结可物化表示时返回 `file_readable_content_not_ready` 或 `file_processing_failed`，而不是宽泛的 `file_lifecycle_not_ready`。`task_workspace_list_files` / `file_get_metadata` 增加可选 `readability_status` 有界字段；未启用文档处理的文本文件为 `NOT_REQUIRED`。Agent 文件提示词增加四条禁令（不推测、不据文件名编造、告知未生成、可答无关问题）。不新增 `file_read` 工具。

### 8. 与并行 Docling change 的权威关系

本 change 的 channel-conversation / execution-delivery / task-file-workspace 准入条款覆盖 `add-governed-docling-file-representations` 中「Job 保持 WAITING_INPUT 直到表示终态」的 delta。apply 本 change 前必须改写该 change 剩余任务 6.3 及对应 spec 句子，改为「来源等待 + 能力门禁」。不得在 sync 时把两套互相矛盾的 WAITING_INPUT 规则一并合入 canonical。

## Risks / Trade-offs

- [无硬证据的内容问题会被当成闲聊] → 接受；Agent 应要求指明文件。后续若误伤过大，另开 change 加分类器，不在本阶段做。
- [近指代绑错文件] → 多文件时强制澄清；单一最近活动文件才绑定。
- [同名文件] → 全等显示名必须唯一，否则澄清。
- [钉钉引用解析失败] → 引用存在但找不到本平台消息时视为无引用证据，不降级成最近活动（避免静默绑错）。
- [Delivery 无 job_id 需要改 Outbox 约束] → 这是本 change 的主要 schema 风险；migration 必须保持既有 Job 结果投递不变，system_notice 走显式 kind。
- [并行 Docling change 回写 WAITING_INPUT] → 任务 1 明确改写对方剩余任务/spec，apply 前再对账。
- [Agent 仍可能 list 到处理中文件并尝试物化] → MCP 第二道闸 + 提示词；主路径仍是不把未就绪项标 auto_materialize。
- [占位失败 Job 若实现滑回 JSON] → 契约测试锁定投递正文为中文 Markdown，禁止 `{` 开头的 error_code JSON。

## Migration Plan

1. apply 前核对 dirty tree、本 change 与 `add-governed-docling-file-representations` 的冲突句，改写对方剩余准入任务。
2. 追加 expand migration：被挡轮次表、消息引用列（若需要）、Delivery Outbox 允许 session 级 `system_notice`（`job_id` 可空仅当 kind 为该值）。不改 MinIO，不 down-migrate 旧认领数据。
3. 部署 API/Worker：Resolver + 门禁 + 认领集合收窄 + 释放逻辑 + MCP 错误码。旧 `WAITING_INPUT` 且仅因 PENDING 表示而挂起的 Job，由一次性和解扫描按新门禁终结或释放，避免永挂。
4. 合成测试通过后再用钉钉私聊验证四条路径：只上传、处理中问无关、处理中问内容、就绪后再问。
5. 回滚：关闭 Resolver 会回到整包认领，属于行为回退且会再次堵住无关问答；因此回滚应保留 Resolver、仅关闭就绪通知。不得删表。

## Open Questions

- 非阻塞：近指代词表在实现时按现网中文习惯补全，不在 proposal 阶段冻结完整词表。
- 非阻塞：`system_notice` 标题统一为「文件尚未可阅读」/「文件已可继续提问」，具体用词实现时与现有中文安全提示风格对齐。
- 已关闭：不使用隐式分类器；不自动重放；不新增编排进程。
