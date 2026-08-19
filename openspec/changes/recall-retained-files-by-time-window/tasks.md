## 1. Resolver 时段硬证据

- [x] 1.1 在 `file_context.py` 增加 `BindReason=TIME_WINDOW`、文件指代词表、时段模式表，以及纯函数 `parse_time_window(text, now, tz=Asia/Shanghai)`：自然周（上周/这周）、上月、今天/昨天、日历日与闭区间；缺年用当前上海年，未来日回退上一年；「附近」不扩窗。
- [x] 1.2 扩展 `WorkspaceFileCandidate` / `FileDependency`，带上 `source_received_at` 与内容是否仍可用（版本/文件非 `CONTENT_UNAVAILABLE`）。
- [x] 1.3 调整 `resolve_file_context` 顺序为：本条附件 → 引用 → 当前工作区完整文件名 → 时段窗口（须同时命中文件指代词）→ 工作区近指代。有时段词时 MUST NOT 再走工作区近指代。
- [x] 1.4 窗口 0 命中返回可区分的空窗结果（不得当成「无硬证据」入队）；多份 + `READABLE_CONTENT` 澄清；多份 + `METADATA` 且 ≤20 全部绑定且不预加载；>20 走过多说明；唯一 + 要读正文 + 内容已清理走内容不可用说明。
- [x] 1.5 扩展 `evaluate_file_gate` 与 `system_notice_markdown`：`time_window_empty`、`time_window_ambiguous`、`time_window_too_many`、`content_unavailable`。空窗文案 MUST NOT 写成「没发过」。
- [x] 1.6 为时段解析和绑定补纯函数测试：自然周边界、日历日/区间、无文件指代词不绑、时段优先于近指代、空窗、多份内容澄清、多份元数据、缺年回退、无硬证据回归。

## 2. 会话保留附件候选与 Job 准入

- [x] 2.1 新增按 Session 列出仍在保留期附件的查询（不要求 `task_workspace_file` 为 `ACTIVE`），过滤租户/私聊或同群归属、`file_retention_fact` 未到期、版本记录仍在，带上 `source_received_at`。`list_file_turn_candidate_rows` 在 `workspace_id` 为空时不得再直接返回空而挡住时段召回。
- [x] 2.2 改 `CreateAgentJobService._file_turn_gate`：把当前工作区候选与会话保留附件一并交给 Resolver；时段命中后再决定是否需要工作区。
- [x] 2.3 时段召回命中且当前没有 `ACTIVE` 工作区时，创建本周期空工作区作为 File MCP 容器，MUST NOT `link` 历史文件。空窗或无文件指代词 MUST NOT 因此建工作区。
- [x] 2.4 把 `TIME_WINDOW` 依赖并入 `file_references` / `register_request`，使 finalize 能冻进本 Job Manifest；认领仍只覆盖本轮绑定的附件 ID。

## 3. Manifest 与授权

- [x] 3.1 扩展 `JobFileManifestService._reference_row`（或并列查找）：允许引用未挂接当前工作区、但仍在保留期且归属边界一致的精确版本；找不到仍返回 `file_reference_denied`。
- [x] 3.2 历史召回项 `source_kind=EXPLICIT_REFERENCE`；`allowed_actions` 去掉 `EDIT`/`COMMIT`；默认 `auto_materialize=false`；窗口唯一且能力就绪且内容 `AVAILABLE` 才自动物化。
- [x] 3.3 确认 `finalize` 按 `(file_id, version_id)` 合并时，历史项不会被当前工作区候选覆盖丢掉，也不会把旧工作区改回 `ACTIVE`。
- [x] 3.4 `require_manifest_action`：`READ_METADATA` 允许快照内 `CONTENT_UNAVAILABLE` 返回有界元数据；`MATERIALIZE`/`DELIVER`/`COMMIT` 仍失败关闭。`COMMIT` 对未挂接当前工作区的 File ID 必须拒绝。
- [x] 3.5 物化快照内已清理版本必须返回 `file_content_unavailable`，不得返回 `file_manifest_item_denied`。`task_workspace_list_files` 继续只列本 Job 快照（含历史项，role 可空）。

## 4. 测试与回归

- [x] 4.1 Manifest / 授权单元测试：非当前工作区保留版本可冻进清单；旧工作区状态不变；历史项无 `COMMIT`；清单外历史 ID 仍拒绝；`CONTENT_UNAVAILABLE` 可列不可物化。
- [x] 4.2 合成验收：周一后问「上周的图」召回唯一上周 PNG；「8月12日的文件」与「8月10日到15日的附件」按 `source_received_at`；「8月12日附近有什么安排」不召回、不建工作区。
- [x] 4.3 合成验收：窗口多份问内容 → 系统说明且无 `agent.jobs`；窗口多份问「发了哪些文件」→ Job 元数据清单且不自动物化；空窗固定说明且禁止「没发过」。
- [x] 4.4 合成验收：无 ACTIVE 工作区但召回命中 → 新建空工作区且不 link；卸挂但仍 `AVAILABLE` 的版本可按需物化；正文已清理时列表可见、物化 `file_content_unavailable`。
- [x] 4.5 回归：无硬证据不绑文件、近指代/文件名/引用、本周「今天发的图片」、`list_files` 仍不等于整段工作区或 360 天库。

## 5. Agent 可见文件时间

- [x] 5.1 File MCP、Runtime Manifest 与自动物化元数据的 `source_received_at` / `version_created_at` / `observed_at` / `representation_created_at` 出站投影为 Asia/Shanghai RFC 3339；存储与 Manifest hash 保持原瞬时；覆盖时钟、授权、清单与 Agent 限制语测试。
