# Mutation 真实验收计划与不变性基线

取证时间：2026-08-31（Asia/Shanghai）

## 安全与执行边界

- 本计划覆盖新 Publication 纳入的全部 10 个 mutation Tool；每次调用必须先创建独立 Action Intent，并由原钉钉用户在操作发生前通过确认卡同意。
- 未确认、取消、过期或目标发生漂移时不得执行 Provider 写入；不得把“创建确认卡”或异步请求被钉钉受理表述为最终业务成功。
- 每一步只记录 Tool 标识、Action Intent 状态、Provider 安全错误码、稳定目标 ID、计数、摘要 hash 和回查结论；不得记录消息正文、用户目录、凭据或 Provider 原始响应。
- 待办和日程分别创建一个验收对象，后续更新/完成复用同一 ID；AI 表格插入一条验收记录并由更新 Tool 复用同一 record ID。当前目录没有纳入删除 Tool，因此不得虚构清理步骤。
- 群消息必须从用户明确选定的真实钉钉群发起，以受信 route 解析 `openConversationId`；当前机器人私聊不能替代群来源。批量单聊只使用同一 Job 中搜索并核实的稳定 `user_id`，不得按姓名猜测。

## 执行顺序

| 序号 | Tool | 确认卡冻结目标 | Provider 成功边界 | 回查 |
|---|---|---|---|---|
| 1 | `dingtalk_create_todo` | 当前用户；subject、description、due_time | 返回稳定 task ID | `dingtalk_list_todos` 找到同一 subject/task ID |
| 2 | `dingtalk_update_todo` | 步骤 1 task ID；新 subject/due_time | 回显同一 task ID | `dingtalk_list_todos` 显示新 subject/时间 |
| 3 | `dingtalk_complete_todo` | 步骤 1 task ID；当前用户本人执行者 | 同一 task ID 的完成请求成功 | 未完成列表不再返回该 task ID，或详情状态证明完成 |
| 4 | `dingtalk_create_calendar_event` | 当前用户主日历；title、起止时间、时区 | 返回稳定 event ID | `dingtalk_get_calendar_event` 返回同一 event ID/时间 |
| 5 | `dingtalk_update_calendar_event` | 步骤 4 event ID；新 title/location | 回显同一 event ID | `dingtalk_get_calendar_event` 返回更新后的字段 |
| 6 | `dingtalk_insert_aitable_records` | 明确 base ID、sheet ID、单条字段映射 | 返回且仅返回一个新 record ID | `dingtalk_get_aitable_record` 读取同一 record ID |
| 7 | `dingtalk_update_aitable_records` | 步骤 6 base/sheet/record ID；更新字段映射 | 回显 record ID 集合与请求完全一致 | `dingtalk_get_aitable_record` 返回更新后的字段 |
| 8 | `dingtalk_send_message_to_group_by_robot` | 受信当前来源群；固定 title/text | `processQueryKey` 只证明请求已受理 | 记录受理标识摘要；群内事实由原用户核验，不宣称已送达 |
| 9 | `dingtalk_batch_send_message_to_users_by_robot` | 同一 Job 搜索并核实的全部目标 user ID；固定 markdown | `processQueryKey` 与受理/过滤/流控/无效计数 | 计数集合自洽；不回显收件人 ID，不宣称已送达 |
| 10 | `dingtalk_send_work_notification` | 当前用户本人；固定 title/text | task ID 只证明异步任务已提交 | `dingtalk_get_work_notification_progress/result` 查询同一 task ID |

## 依赖与当前阻塞

- 步骤 6、7 的旧 Publication 使用 notable v2 无 operator 契约。2026-08-31 的重试 Job `job_0b5c106f32564195b01a79b69b6b35de` 已证明平台 Job/角色授权为 `ALLOW`，但钉钉 Provider 对 `dingtalk_list_aitable_sheets` 返回 `dingtalk_permission_denied`，官方错误码为 `AccessTokenPermissionDenied`。最初的“继续补权限”判断已被后续官方 MCP v1 + operator 成功对照推翻；必须先发布修正后的契约再重试。
- 步骤 8 必须由原用户在一个真实群会话中发送验收请求；机器人私聊 route 不具备可验证的群目标。
- 其余步骤可在当前私聊按顺序发起，但每个 Provider 写入仍等待独立确认卡。

## 写入前不变性基线

- Agent r27：`agent_publication_f4e9634f4cf34debb09dda0e97798679`，config hash `39aa24f4511d9b942ea04eda0a2f2fa12e9b0ba653f56d6336071e9d59408c85`，当前为 inactive。
- Agent r28：`agent_publication_e90646e86d884c758777ca882d4bb4fb`，config hash `7f78cc1a830f890a8c315d43a4533535f5104fe19b4eebed68de4dd5accaaed8`，当前为 active。
- Application r42：`business_app_publication_6165c86f70d149c48728780e76228211`，config hash `5ba7c7e741f85546811e17ba06d9e61980d2d6d885b9c7330b4b75c2ee7c92b3`。
- Application r43：`business_app_publication_3c5ee20803cb445db48fe0fe9cfbaeb8`，config hash `e478f0879b6b622d32adfb2e7599e1efcea0d4c3237b26bd97eb8cd2115288cf`。
- 历史 Job `job_df08fb56b75a4f58b203a5363a79787a`：状态 `SUCCEEDED`，旧 Agent/Application Publication 保持不变，MCP snapshot hash `e577169ea6dffbb56d29473b2a83d5fa09f0fb61ec7679a413448839372db0d6`，authorization hash `44b0aa7729bcd556fa71867df8470b73520915d615256133f7b061a36571b7cd`，冻结 31 个 Tool。
- 5.4 四个新只读 Job 均冻结 r28/r43、32 个 Tool，authorization hash 均为 `3cb762c58e58887f5dabb74f4505d7468397c6a8adfde6ed5000a863aed8e795`；各自 snapshot hash 已在数据库保留。5.5 结束后必须再次查询上述 hash、Publication ID、Tool 数和 Job 状态并逐项相等比较。

## 首个待办请求（已确认并回查）

在获得代表用户发送钉钉消息的当下确认后，已发送以下短消息，且未被钉钉客户端转换成长文本附件：

> 调用 dingtalk_create_todo 创建当前用户待办：subject=Enterprise Agent 钉钉官方契约 E2E 20260831，description=mutation acceptance，due_time=2026-09-02T18:00:00+08:00。只创建确认卡，确认前不要执行；确认后返回 task_id 供只读回查。

后续请求只有在前一步获得稳定 ID 且回查成功后才生成，不预先猜测 task/event/sheet/record/user/conversation ID。

- 入口创建 `job_d5164cef989e46c2ba6daaae6cbe0d01`，状态 `SUCCEEDED`，冻结 Agent r28 与 Application r43。
- `dingtalk_create_todo` 先创建 Action Intent `action_966259dff07b4a2d8e66f30c68331a89`；确认前状态为 `PENDING_CONFIRMATION`、`execution_attempts=0`、无错误码。
- 确认卡在原钉钉私聊中可见，原用户随后点击“确认执行”。Intent 最终为 `SUCCEEDED`、`execution_attempts=1`、无错误码，稳定 task ID 为 `task63397341727470c18ddabb100e89f979`；审计记录 `external_action.approved/APPROVED` 与 `external_action.executed/SUCCEEDED`。
- 只读钉钉“待办”页面真实显示同一标题、当前用户执行人、星期三 18:00 截止时间和今天 14:35 创建时间，完成 Provider 事实回查；未修改或完成该待办，也未发送第三条消息。

## 第二个待办请求（已确认并回查）

用户再次给予代表发送的当下确认后，已向原钉钉私聊发送：

> 调用 dingtalk_update_todo 更新当前用户待办：task_id=task63397341727470c18ddabb100e89f979，subject=Enterprise Agent 钉钉官方契约 E2E 20260831 UPDATED，due_time=2026-09-03T18:00:00+08:00。只创建确认卡，确认前不要执行；确认后返回同一 task_id 供只读回查。

- 入口创建 `job_fc181bdc54914b828a863dff5a6c3257`，状态 `SUCCEEDED`，冻结 Agent r28 与 Application r43。
- 更新 Intent `action_b254a7419f8d4b12b5a0ab27fdd0ae65` 首次观测为 `PENDING_CONFIRMATION`、`execution_attempts=0`，没有 Provider request ID 或错误码。
- 卡片 CREATE Outbox 为 `SUCCEEDED`、`attempt_count=1`。原用户确认前未把待办判为已更新。
- 原用户确认后，Intent 为 `SUCCEEDED`、`execution_attempts=1`、无错误码，Provider 返回与创建步骤相同的 task ID；独立审计记录 `external_action.approved/APPROVED` 与 `external_action.executed/SUCCEEDED`。
- 只读钉钉“待办”页面回查到 `UPDATED` 标题和星期四 18:00 截止时间，执行人及创建时间保持不变；创建与更新 Job 都冻结 r28/r43、32 个 Tool和相同 authorization hash，历史基线 Job 的状态、Tool 数及两项 hash 仍不变。

## 第三个待办请求（已确认并回查）

用户再次给予代表发送的当下确认后，已向原钉钉私聊发送：

> 调用 dingtalk_complete_todo 完成当前用户待办：task_id=task63397341727470c18ddabb100e89f979，subject=Enterprise Agent 钉钉官方契约 E2E 20260831 UPDATED。只创建确认卡，确认前不要执行；确认后返回同一 task_id，供未完成列表和待办页面只读回查。

- 入口创建 `job_a25f5115635643c9abc0b9fe74503525`，状态 `SUCCEEDED`，冻结 Agent r28 与 Application r43。
- 完成 Intent `action_b9975649365e4860aef67396c3f6d463` 首次观测为 `PENDING_CONFIRMATION`、`execution_attempts=0`，没有 Provider request ID 或错误码。
- 卡片 CREATE Outbox 为 `SUCCEEDED`、`attempt_count=1`。原用户确认前未把待办判为已完成。
- 原用户确认后，Intent 为 `SUCCEEDED`、`execution_attempts=1`、无错误码，Provider 返回同一 task ID；独立审计记录 `external_action.approved/APPROVED` 与 `external_action.executed/SUCCEEDED`。
- 初次详情仍显示“完成待办”按钮，因此未直接采信缓存视图；退出并重新进入后，目标从“待我处理”消失且出现在“我已处理”，完成事实回查。完成 Job 冻结 r28/r43、32 个 Tool和共同 authorization hash，历史基线 Job 仍未被改写。

## 首个日程创建请求（首次发送未形成 Intent）

- 用户给予代表发送的当下确认后，短消息请求 `dingtalk_create_calendar_event` 创建 2026-09-04 10:00–10:30（Asia/Shanghai）的当前用户主日历测试日程。
- 入口 Job `job_d7a18854183a44b08bbf1dc69f282fc6` 为 `SUCCEEDED` 并冻结 r28/r43，但 Tool Call、MCP 审计、Action Intent 与卡片 Outbox 均为 0；白色最终回复却声称确认卡已创建。该次调用判定为 `failed/unverified_confirmation_claim`，没有日程写入，也没有可点击确认卡。
- 已增加 Prompt v4 的真实 Tool Call 约束与 Worker 最终回复事实守卫；相关 112 项回归通过，`agent-worker` 已重建运行，`python-agent-runtime` 已重建且健康，容器内 Prompt/守卫探针通过。下一次只能在用户再次给予代表发送的当下确认后创建新 Job 重试；不得复用或改写本次 Job，也不得把模型文字当成 Action Intent。
- 用户再次给予当下确认后，新 Job `job_98c51c7cccf447fabc833e5a147ac745` 使用 Prompt v4 并冻结 r28/r43；真实 Tool Call `dingtalk_create_calendar_event` 为 `SUCCEEDED`，MCP 授权为 `ALLOW`，创建 Intent `action_9939fcd1ce9649e2a2f7f0bb5107fd37`。首次观测为 `PENDING_CONFIRMATION`、`execution_attempts=0`，卡片 CREATE Outbox 为 `SUCCEEDED`、`attempt_count=1`。本次卡片已由三类权威事实证明存在，但确认前不得判为日程创建成功。
- 该 Intent 在 15 分钟确认窗口内未获批准，用户稍后操作时已转为 `EXPIRED`；执行次数保持 0，审计只有 `external_action.expired`，没有 Provider 写入。后续重试必须在用户再次给予代表发送的当下确认后创建新的 Job/Intent，并在新卡有效期内由原用户确认。
- 用户重新授权发送后，入口创建全新 Job `job_8ef3bd7e0ecb4980b4b58da3e8e19deb`，冻结 r28/r43 和 32 个 Tool；`dingtalk_create_calendar_event` Tool Call 为 `SUCCEEDED`，创建新 Intent `action_0a89a1dffa614eca807d4e609e625e0f`。确认前 Intent 为 `PENDING_CONFIRMATION`、`execution_attempts=0`，卡片 CREATE Outbox 为 `SUCCEEDED`、`attempt_count=1`，没有复用两个历史失败/过期 Intent。
- 原用户在有效期内确认后，Intent 于北京时间 16:44:30 获批，并在一次 Provider 执行后于 16:44:31 进入 `SUCCEEDED`；返回稳定 event ID `aTJER3BDY3pLUEVlRHlqZ2ZFb28wQT09`，无错误码。审计按序存在 `external_action.prepared/PENDING_CONFIRMATION`、`external_action.approved/APPROVED` 和 `external_action.executed/SUCCEEDED`，结果卡 `RESULT_UPDATE` Outbox 也为 `SUCCEEDED`、`attempt_count=1`。
- 只读打开钉钉“日历”页面，2026-09-04 直接显示 `10:00 Enterprise Agent Calendar E2E 20260831 RETRY`，完成 Provider 事实回查。新 Job 的 snapshot/authorization hash 分别为 `ff0f45af77c6d03a011ce5c266aec12fd62ecff1a700148e05a6b5ab2d2aeab4` 与 `3cb762c58e58887f5dabb74f4505d7468397c6a8adfde6ed5000a863aed8e795`；历史 Job `job_df08fb56b75a4f58b203a5363a79787a` 仍为 `SUCCEEDED`、31 个 Tool，两项 hash 仍为原基线值，未被改写。

## 第二个日程更新请求（已确认并回查）

- 用户给予代表发送的当下确认后，向原钉钉私聊发送 `dingtalk_update_calendar_event` 请求，目标为上述稳定 event ID；标题改为 `Enterprise Agent Calendar E2E 20260831 RETRY UPDATED`，时间改为 2026-09-04 11:00–11:30（Asia/Shanghai），地点改为 `线上-更新`。
- 入口创建 `job_a327f8fab9ab46a1b51944f7c55c5a26`，冻结 r28/r43 和 32 个 Tool；真实 Tool Call `dingtalk_update_calendar_event` 为 `SUCCEEDED`，创建全新 Intent `action_a47aebf7890a4f77a85ae629c19266c8`。确认前状态为 `PENDING_CONFIRMATION`、`execution_attempts=0`，卡片 CREATE Outbox 为 `SUCCEEDED`、`attempt_count=1`。
- 原用户在有效期内确认后，Intent 于北京时间 17:28:30 获批，并在一次 Provider 执行后于 17:28:31 进入 `SUCCEEDED`；Provider 回显与创建步骤完全相同的 event ID `aTJER3BDY3pLUEVlRHlqZ2ZFb28wQT09`，无错误码。审计按序记录 prepared、approved、executed，结果卡 `RESULT_UPDATE` Outbox 一次更新成功。
- 只读钉钉“日历”页面在同一日期显示 `11:00 Enterprise Agent Calendar E2E 20260831 RETRY UPDATED`，完成更新事实回查。该 Job 的 snapshot/authorization hash 分别为 `47f41d68c8f5aae7f188211ecf33f7fc449c458f4322981168ac340576195e64` 与共同授权 hash；历史基线 Job 仍为 `SUCCEEDED`、31 个 Tool，原 snapshot/authorization hash 均未改变。

## AI 表格写入前只读定位（Provider 契约兼容性阻塞）

- 用户授权发送只读定位消息后，入口创建 `job_ff534a9d526143a7b35d4da47ca21963`。`dingtalk_search_aitables(query=新浪热搜)` 为 `SUCCEEDED`，名称精确命中并返回 base ID `Amq4vjg895Oedmm5Tx5MqX5g83kdP0wQ`。
- 随后的 `dingtalk_list_aitable_sheets` 在平台授权审计为 `ALLOW/principal_identity_snapshot_and_tool_grant_allowed` 后，被钉钉 Provider 拒绝为 `DENIED/dingtalk_permission_denied`。因此目标 `sheet_id`、字段类型和现有 `record_id` 均未取得，后续详情/字段/记录调用安全跳过。
- 本 Job 的 Action Intent 数和卡片 Outbox 数均为 0，未调用 AI 表格插入或更新 Tool。用户随后提供官方 MCP `1.1.21` 的真实对照：同一 `baseId` 可通过 v1 + `operatorId` 列出 `sheetId=hERWDMS`、读取字段、插入三条记录并回读。因此不能再把系统失败归因于管理员未补权限；阻塞收敛为本系统把官方 v1 + operator 契约改成 notable v2 无 operator 后产生的兼容性失败。修复前仍不得凭 UI URL、旧响应或猜测 ID 触发写入。

## AI 表格官方契约修正后只读定位（已通过）

- 新 r29/r44 与角色业务授权 r9 生效后，首次只读消息因独立 `channel-dispatch-worker` 旧镜像导致 envelope mismatch，在创建 Job 前安全拒绝；该入口没有 Tool Call、Intent 或 Provider I/O。重建全部独立分发 Worker 后，仅在原用户重新允许发送时创建全新入口和 Job。
- 新 Job `job_3c0c9d05ca35433380c236962be1ac91` 冻结 r29/r44 和 39 个当前上下文实际可用 Tool，其中钉钉 35 个、七个新增 notable Tool 缺失 0；snapshot/authorization hash 分别为 `ed26185158b21b2c74b43bfc6f3d1c15baceb7307d6c60ef9d6f33f59017cbeb` 和 `5d79ca1600db0f1dba933ac22a1e8d40bef28ed1c16842e7079fe382b8814130`。
- 三个静态说明 Tool、搜索 AI 表格、列数据表、读目标数据表、列字段、列记录和读单记录共 9 次调用全部成功。安全摘要为：搜索命中 1 个 AI 表格、列出 2 个 sheet、目标表 3 个字段、分页返回 5 条记录；这与用户可见的两个数据表事实一致，且未读取或持久化记录字段值。
- Job 状态为 `SUCCEEDED`、Action Intent 数为 0；结果一次投递到原钉钉私聊成功。该证据关闭 notable v1 + `operatorId` 的只读兼容性阻塞，但不替代记录写入、数据表创建/改名和字段创建/更新的确认型验收。

## AI 表格数据表创建（已确认，待独立只读回查）

- 用户明确允许在“新浪热搜”中创建并保留验收数据后，向原钉钉私聊发送仅调用 `dingtalk_create_aitable_sheet` 的单 mutation 请求；目标 base ID 为 `Amq4vjg895Oedmm5Tx5MqX5g83kdP0wQ`，名称为 `Enterprise Agent MCP 验收 20260831`，并明确禁止修改或删除任何已有资源。
- 新入口 `channel_event_e9cad91c260b485c81deb953360c5ad9` 创建 Job `job_4e7fd2944aa8441ea6c0cbe55ee80f88`；Job 为 `SUCCEEDED`，冻结 r29/r44、39 个当前上下文 Tool，snapshot/authorization hash 分别为 `56d5673cbc9b5772b25442e6bae54e2495449744ffc1829943c32d62d83fd100` 与 `5d79ca1600db0f1dba933ac22a1e8d40bef28ed1c16842e7079fe382b8814130`。
- 真实 Tool Call `dingtalk_create_aitable_sheet/SUCCEEDED` 创建 Intent `action_5f4f32e88fd642ee9b6595ed0c167558`。审计先记录 `external_action.prepared/PENDING_CONFIRMATION`；卡片 CREATE Outbox 一次投递成功，确认前没有 Provider 执行。
- 原用户随后通过确认卡回调批准；Intent 于 `2026-08-31T11:54:29.853113+00:00` 获批，仅执行 1 次，并于 `2026-08-31T11:54:31.613094+00:00` 进入 `SUCCEEDED`。Provider 严格响应返回新 sheet ID `shhqkza` 和同一名称；结果卡一次更新成功，无错误码。
- 写入后只读复核确认 r28/r43、r29/r44 的 Publication ID、revision 和 config hash 均保持原值；历史基线 Job `job_df08fb56b75a4f58b203a5363a79787a` 与修正后只读 Job `job_3c0c9d05ca35433380c236962be1ac91` 的状态、Tool 数、snapshot/authorization hash 也均未被改写。当前只证明确认后 Provider 创建成功；仍需通过独立只读 Job 回查新 sheet，之后才能在其稳定 ID 上继续改名、字段和记录验收。

## 2026-08-31 完成性审计

- 发送前基线中，r28 外部操作意图数为 0；`PENDING_CONFIRMATION`、`APPROVED`、`EXECUTING` 状态的 r28 意图均为 0，证明验收消息发送前未偷偷准备或执行任何写入。
- 用户明确允许发送两条验收消息后，r28 新增且仅新增上述 1 个待办 Intent；首次观测为 `PENDING_CONFIRMATION`，当时 `APPROVED`/`EXECUTING` 均为 0、执行次数为 0。只读复验 Job 没有创建确认卡或写入 Intent。
- 原用户确认后，该 Intent 仅执行 1 次并成功；写入后复核历史 `job_df08fb56b75a4f58b203a5363a79787a` 和四个 5.4 只读 Job 的状态、Publication ID、Tool 数、snapshot hash 与 authorization hash，均与写入前基线逐项相等。
- 待办创建和更新两个 Intent 现均各执行 1 次并成功，均返回同一稳定 task ID；第二次写入后再次复核历史基线 Job，未发现快照或授权 hash 改写。
- 待办创建、更新、完成三个 Intent 现均各执行 1 次并成功，均返回同一稳定 task ID；第三次写入后再次复核历史基线 Job，仍未发现状态、Tool 数、snapshot hash 或 authorization hash 改写。
- 日程创建的第三次入口使用全新 Job/Intent，在有效期内确认后仅执行 1 次并成功；钉钉日历页面显示同一标题、日期和 10:00 开始时间。此前零 Tool Call Job 和已过期 Intent 均保持原状态，历史基线 Job 的状态、Tool 数及两项 hash 仍不变。
- 日程更新使用同一稳定 event ID 创建独立 Job/Intent，在有效期内确认后仅执行 1 次并成功；钉钉日历页面显示更新后的标题和 11:00 开始时间，历史基线 Job 的状态、Tool 数及两项 hash 再次保持不变。
- AI 表格旧 Job 的 search 成功、list sheets Provider 权限拒绝保持为历史失败证据；新 r29/r44 Job 已通过 v1 + operator 完成 9 项只读验收并真实返回 2 个 sheet。新旧 Job 均未被改写，当前剩余阻塞只在确认型写入验收。
- AI 表格数据表创建使用新 r29/r44 Job、独立 Action Intent 和原用户卡片回调，仅执行 1 次并返回新 sheet ID `shhqkza`；写入后新旧 Publication 与历史 Job 快照仍未被改写。独立只读回查尚未发送，因此该步骤暂不计为完整事实闭环。
- 契约修正前的全量相关组合回归为 106 passed；针对七 profile 分类、官方语义/治理描述、显式排除、notable v2 与 legacy allowlist 的完成性子集曾得到 14 passed。该历史测试结果不能证明 v2 与官方 MCP 语义等价，现由新增 v1/operator 回归替代。
- 当前源码中的 `oapi.dingtalk.com` 仅作为统一 legacy base 存在，实际 `/topapi/` 调用严格等于 6 个 allowlist operation：部门成员、部门详情、子部门、工作通知发送、进度、结果；未发现额外旧端点。
- 发现 notable v2 契约不兼容后，已完成 notable v1 + `operatorId`、三个静态说明 Tool、数据表/字段非删除 mutation、Action Intent 冻结与 Worker 再授权实现；这些变更不能由旧 Job 替代。修正后的本地相关组合回归为 134 passed，Ruff、Mypy 与 OpenSpec strict validation 均通过。
- 当前纳入 14 个 mutation：已完成事实回查 5 个（待办创建/更新/完成、日程创建/更新）；仍待新 Publication 和新 Job 验收 9 个（AI 表格数据表创建/改名、字段创建/更新、记录新增/更新、群消息、批量个人消息、工作通知）。每次外部写入仍需要原用户当下允许发送验收请求并逐卡确认；群消息还必须从真实群来源发起。未满足前不得标记 5.5、5.6 完成或归档。
