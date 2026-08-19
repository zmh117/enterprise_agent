## Context

当前 File Context Resolver 只在**当前活动工作区**和本条消息上找硬证据；Job File Manifest 的显式引用路径 `_reference_row` 要求 `task_workspace_file.status=ACTIVE`。工作区按 Asia/Shanghai 自然周到期后，活动文件被标 `REMOVED`，但 `message_attachment` 仍按约 360 天独立保留。用户问「上周的图」时，Agent 只能看见本周快照，于是把「当前工作区没有」说成「没发过」。

本 change 不恢复旧 `ACTIVE` 工作区，也不把 360 天附件库交给模型筛选。它把代码可解析的时段做成第五类硬证据，把命中的精确版本写入**这一次** Job Manifest。`list_files` 继续只列本 Job 快照。

约束：简体中文规范；不新增队列或文件表；不扫描无关 archive；与未 archive 的 `decouple-document-readiness-from-agent-turns` 衔接——时段证据不得削弱「无硬证据不绑文件」。该 sibling change 里的 Resolver / Manifest 自动物化语义视为 Confirmed-current，本设计按它落地，不回退到 canonical 里「后续文字认领全部暂存附件」。

## Goals / Non-Goals

**Goals:**

- Resolver 用代码注册的时段词 + 文件指代词绑定仍在保留期的精确版本。
- 「上周 / 这周」与工作区 `WEEK` 使用同一套上海自然周边界；日历日和闭区间按 `source_received_at` 过滤。
- 命中版本进入本 Job Manifest；默认不自动物化；唯一且要读正文且内容可用时才预加载。
- 空窗、多份内容问题走固定系统说明；禁止模型把空窗说成「没发过」。
- 正文已清理：元数据可列，物化返回既有 `file_content_unavailable`。
- 提交仍只打当前 `ACTIVE` 工作区；历史项去掉 `EDIT`/`COMMIT`。

**Non-Goals:**

- 不把旧工作区改回 `ACTIVE`，不 `link` 历史文件进本周工作区。
- 不上 LLM 日期分类器，不解析「前几天 / 月初那会儿」等未注册模糊说法。
- 不把 File MCP `list_files` 改回整段工作区或 360 天附件库；调试全量目录另开 change。
- 不改工作区到期时钟、不改 360 天附件保留、不接线 `start_new_task` / `end_current_task`。
- 不新增 `SnapshotSourceKind`；历史召回复用 `EXPLICIT_REFERENCE`，用 `BindReason=TIME_WINDOW` 区分来源。
- 不在本 change 解决「图片无 Markdown 表示时如何理解像素」；召回后的可读能力沿用现有格式规则。

## Decisions

### 1. 绑定顺序：显式身份优先，时段覆盖近指代

**选择**：`当前消息附件 → 引用 → 完整文件名（当前工作区）→ 时段窗口（若同时有文件指代词）→ 近指代（当前工作区）`。命中即停。文件名查找仍只扫当前工作区，避免一句「report.xlsx」去 360 天库里撞名。

**备选**：严格把时段放在近指代之后。否决原因：「上周这张图」会被本周最近一张图抢走。

**备选**：时段存在时把近指代池限制在窗口内。效果接近，但实现分叉更多。采用「有时段词则走窗口、不再走工作区近指代」。

### 2. 必须叠文件指代词

**选择**：日期闲聊（「8月12日附近有什么安排」）不查附件。文件指代词是代码常量表，至少含「文件 / 附件 / 图 / 图片 / 文档 / 表 / 材料」和常见扩展名。近指代表已覆盖的「发的图片」等仍只用于无时段时的工作区近指代。

### 3. 窗口算法与数据源

**选择**：在 Resolver 增加纯函数 `parse_time_window(text, now, tz=Asia/Shanghai) -> (start, end] | None`。候选由 `CreateAgentJobService` 按 Session + 归属边界加载：`message_attachment` ⋈ 版本 ⋈ `file_retention_fact`，`source_received_at` 落在窗口内，保留未到期，版本记录仍在。不要求 `task_workspace_file` 为 `ACTIVE`。

缺省年份取当前上海年；若该日尚未开始，回退上一年。单日窗口为 `[当天 00:00, 次日 00:00)`。「附近」不扩窗。

### 4. Manifest 查找不再强制当前工作区挂接

**选择**：扩展 `register_request` / `_reference_row`：对本轮 `TIME_WINDOW`（以及将来同样不在当前工作区的显式 ID）走「会话保留版本」查找。归属校验与物化时相同（租户、私聊所有者或群 `owner_conversation_id`）。`source_kind` 仍为 `EXPLICIT_REFERENCE`，避免改协议枚举。

历史项 `allowed_actions`：在该格式既有动作上去掉 `EDIT`/`COMMIT`。文本仍可 `MATERIALIZE`；文档/图沿用 `DOCUMENT_MANIFEST_ACTIONS` + 可选 Markdown 表示。`auto_materialize` 仅当窗口唯一且能力就绪且内容 `AVAILABLE`。

**备选**：增加 `HISTORICAL_WINDOW` source_kind。更清晰，但要改 schema 与投影。本 change 不值得。

### 5. 空窗与歧义走 system_notice，不让模型编造

**选择**：复用已有无 Job 的 `system_notice` Outbox。新增文案：

- `time_window_empty`：该时段没有仍可访问的文件。其他问题可以继续发送。
- `time_window_ambiguous`：列出有界安全文件名，请引用消息或写完整文件名。
- `time_window_too_many`：超过 20 份，请缩小到某一天或具体文件名。
- `content_unavailable`（唯一且要读正文）：内容已按保留策略清理，请重新发送文件。

空窗说明禁止「没发过 / 从来没有文件」。元数据列举（≤20）创建 Job，`auto_materialize=false`。

### 6. 无 ACTIVE 工作区时只为命中召回建空容器

**选择**：召回命中且无 `ACTIVE` 工作区 → 创建本周期空工作区，供 File MCP Principal 绑定。历史文件不 `link`。空窗或无文件指代词 → 不创建工作区。

### 7. 物化错误码保持「内容不可用」语义

授权层已对非 `AVAILABLE` 版本返回 `file_content_unavailable`。必须保证历史项**已在快照中**时走这条，而不是因 `_reference_row` 找不到被当成 `file_manifest_item_denied`。`list_files` 继续 left join 当前工作区角色，历史项 role 可为空。

### 8. 与 sibling change 的 archive 顺序

本 change 的 `Job 创建时冻结精确文件清单` / `Agent Job 固定文件清单但实时复核访问` 按 sibling 已落地语义撰写（只自动物化本轮绑定）。archive 时应先同步 `decouple-document-readiness-from-agent-turns`，再同步本 change，避免把 canonical 旧「认领全部暂存附件」盖回来。

## Risks / Trade-offs

- [「上周这张图」绑错本周图] → 时段词存在时跳过工作区近指代。
- [一句「文件」误召回整周] → 必须同时命中时段模式；无时段的「文件」仍不绑。
- [窗口内几十份 METADATA 撑爆 Manifest] → 超过 20 份改说明，不入队。
- [跨群 File ID] → 查找与物化都复核会话归属；失败关闭。
- [缺年日期落在未来] → 回退上一年；测试覆盖 1 月问「12月的文件」。
- [sibling 未 archive 导致 spec 合并冲突] → design 锁定 archive 顺序；tasks 不依赖改 sibling 目录。
- [图片无表示仍无法「看懂」] → 不在本 change 扩大视觉理解；唯一图片且无表示时按现有能力门禁（元数据可答，正文可能系统说明）。

## Migration Plan

- 无 schema / 队列迁移。部署后新 Job 立即按新 Resolver 生效；已冻结 Manifest 不变。
- 回滚：回退 Resolver 与 `_reference_row` 即可，历史 Job 快照仍合法。
- 监控：`time_window_empty` / `time_window_ambiguous` / `file_content_unavailable` 计数；确认 `file_manifest_item_denied` 不在「清单内历史项」上激增。

## Open Questions

- 英文 `last week` / `yesterday` 是否纳入第一批词表：默认不做，避免半套 locale；需要时再加代码常量。
- 「前天 / 本月」是否纳入：本 change 不纳入，避免和日历日规则纠缠。
