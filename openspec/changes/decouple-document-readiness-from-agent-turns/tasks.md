## 1. 并行变更对账与前置

- [ ] 1.1 核对 dirty worktree、migration head 和 `add-governed-docling-file-representations` 剩余任务；记录准入语义冲突句。
- [ ] 1.2 改写该 change 中「Job 因表示 PENDING 保持 WAITING_INPUT」的剩余任务与 delta 措辞，使其服从本 change 的来源等待 + 能力门禁模型。
- [ ] 1.3 盘点仍断言「后续文字认领全部暂存附件并等待 Docling」的测试，列入第 8 节替换清单。

## 2. 数据模型与投递扩展

- [ ] 2.1 追加 expand migration：`file_readiness_blocked_turn`（会话、消息、version 集合、原因码、OPEN/NOTIFIED/EXPIRED、过期时间），不含正文。
- [ ] 2.2 为用户消息增加可查询的引用目标（专用列或等价索引），并保证可用 `session_id + external_message_id` 反查被引附件。
- [ ] 2.3 扩展 Delivery Outbox：允许 `kind=system_notice` 且 `job_id` 为空，但必须绑定 `session_id` 与冻结 reply route；既有 Job 结果/失败投递约束保持不变。
- [ ] 2.4 在 SQLite 单测库和 PostgreSQL 迁移测试上验证 upgrade 与旧数据兼容；不 down-migrate。

## 3. 确定性 Resolver 与能力门禁

- [ ] 3.1 实现 `FileContextResolver`：当前附件、引用消息、精确显示名、近指代+唯一最近来源就绪版本；无证据返回空集合。
- [ ] 3.2 把钉钉 `originalMsgId` 从 Stream 入站传入 `CreateAgentJobCommand` 并持久化，停止只把引用正文拼进 prompt。
- [ ] 3.3 实现能力判定：代码注册元数据/原件模式，其余已绑定默认 `READABLE_CONTENT`；歧义绑定返回澄清结果而不是猜测。
- [ ] 3.4 为 Resolver 补充纯函数测试：同消息附件、引用命中/找不到、重名、多文件近指代、无硬证据。

## 4. 认领集合与 Job 准入

- [ ] 4.1 将 `claim_staged_attachments` 改为只更新本轮绑定的 attachment ID，禁止整 Session 空 `job_id` 批量认领。
- [ ] 4.2 在 `CreateAgentJobService` 创建 Job 前执行 Resolver + 门禁：无依赖或 METADATA/ORIGINAL 且原件可用则创建可执行 Job；READABLE_CONTENT 未就绪或失败则不入 `agent.jobs`。
- [ ] 4.3 纯附件路径保持 `stage_attachments()`，不创建 Job、不跑门禁回复。
- [ ] 4.4 Manifest 自动物化只包含本轮绑定且能力已就绪的版本/表示；处理中文档最多作为元数据候选。
- [ ] 4.5 修正 `_release_if_ready`：来源未终态才继续 `WAITING_INPUT`；来源终态后重跑门禁，PENDING 表示不再阻塞释放或无关 Job。
- [ ] 4.6 增加一次性扫描：把仅因表示 PENDING 挂起的存量 `WAITING_INPUT` Job 按新门禁终结或释放，避免永挂。

## 5. 系统说明投递

- [ ] 5.1 实现 Session 级 `system_notice` 投递：固定中文 Markdown，走原 sessionWebhook，禁止 `failure_notification` JSON 和 `agent_runtime_error`。
- [ ] 5.2 覆盖文案：表示生成中、处理失败、绑定歧义澄清；只含安全文件名和允许状态短语。
- [ ] 5.3 为门禁失败写审计事件（原因码、version id、session），不含正文和内部处理器标识。

## 6. File MCP 第二道闸

- [ ] 6.1 `file_prepare_materialization` 在无可用 Markdown 表示时返回 `file_readable_content_not_ready` 或 `file_processing_failed`，不创建传输。
- [ ] 6.2 `task_workspace_list_files` 与 `file_get_metadata` 投影有界 `readability_status`；处理中文件不得给出可物化路径。
- [ ] 6.3 `file_deliver_version` 在原件已保存且有 `DELIVER` 时不因表示 PENDING 拒绝。
- [ ] 6.4 更新 Agent 文件提示词：未就绪/失败码下不得臆造正文。
- [ ] 6.5 补充 File MCP 契约测试：PENDING 物化拒绝、失败拒绝、元数据可见、原件交付不挡。

## 7. 被挡轮次与就绪通知

- [ ] 7.1 门禁因 READABLE_CONTENT 未就绪结束时写入 `file_readiness_blocked_turn`（OPEN，24h 或工作区结束先到为准）。
- [ ] 7.2 在 readability 对账到 AVAILABLE/PARTIAL 后扫描匹配 OPEN 行，发送一次就绪通知并标记 NOTIFIED。
- [ ] 7.3 过期扫描将超时或工作区已清理的行标为 EXPIRED，不补发、不创建 Agent Job、不重放原问题。
- [ ] 7.4 普通上传完成且从未被挡时不发解析完成通知。

## 8. 回归与合成验收

- [ ] 8.1 替换工作区/连续会话测试：后续无关文字不再认领全部暂存附件，Job 立即 PENDING。
- [ ] 8.2 合成场景：处理中问内容 → 系统说明且无 `agent.jobs`；处理中问元数据 → Job 可执行；引用/文件名绑定命中。
- [ ] 8.3 合成场景：近指代歧义澄清；无硬证据不绑定；同消息附件+问题在来源导入期间仅 WAITING_INPUT 等来源。
- [ ] 8.4 合成场景：被挡后表示就绪只通知不重放；MCP 第二道闸在漏绑时 fail-closed。
- [ ] 8.5 确认既有 TXT/MD/LOG 快路径、纯上传不建 Job、Manifest 时间字段和原件 Delivery 回归仍然通过。
