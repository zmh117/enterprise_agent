# Mutation 真实验收计划与不变性基线

取证时间：2026-08-31（Asia/Shanghai）

## 安全与执行边界

- 本计划覆盖新 Publication 纳入的全部 14 个 mutation Tool；每次调用必须先创建独立 Action Intent，并由原钉钉用户在操作发生前通过确认卡同意。
- 未确认、取消、过期或目标发生漂移时不得执行 Provider 写入；不得把“创建确认卡”或异步请求被钉钉受理表述为最终业务成功。
- 每一步只记录 Tool 标识、Action Intent 状态、Provider 安全错误码、稳定目标 ID、计数、摘要 hash 和回查结论；不得记录消息正文、用户目录、凭据或 Provider 原始响应。
- 待办和日程分别创建一个验收对象，后续更新/完成复用同一 ID；AI 表格创建一个验收数据表和一个验收字段，后续改名/更新复用同一稳定 ID；再插入一条验收记录并由更新 Tool 复用同一 record ID。当前目录没有纳入删除 Tool，因此不得虚构清理步骤。
- 群消息必须从用户明确选定的真实钉钉群发起，以受信 route 解析 `openConversationId`；当前机器人私聊不能替代群来源。批量单聊只使用同一 Job 中搜索并核实的稳定 `user_id`，不得按姓名猜测。

## 执行顺序

| 序号 | Tool | 确认卡冻结目标 | Provider 成功边界 | 回查 |
|---|---|---|---|---|
| 1 | `dingtalk_create_todo` | 当前用户；subject、description、due_time | 返回稳定 task ID | `dingtalk_list_todos` 找到同一 subject/task ID |
| 2 | `dingtalk_update_todo` | 步骤 1 task ID；新 subject/due_time | 回显同一 task ID | `dingtalk_list_todos` 显示新 subject/时间 |
| 3 | `dingtalk_complete_todo` | 步骤 1 task ID；当前用户本人执行者 | 同一 task ID 的完成请求成功 | 未完成列表不再返回该 task ID，或详情状态证明完成 |
| 4 | `dingtalk_create_calendar_event` | 当前用户主日历；title、起止时间、时区 | 返回稳定 event ID | `dingtalk_get_calendar_event` 返回同一 event ID/时间 |
| 5 | `dingtalk_update_calendar_event` | 步骤 4 event ID；新 title/location | 回显同一 event ID | `dingtalk_get_calendar_event` 返回更新后的字段 |
| 6 | `dingtalk_create_aitable_sheet` | 明确 base ID、新数据表名称 | 返回稳定 sheet ID 和同一名称 | 独立只读 Job 列表与详情均命中同一 sheet ID/名称 |
| 7 | `dingtalk_update_aitable_sheet` | 步骤 6 base/sheet ID；新名称 | 同 operator 回读同一 sheet ID/名称后才成功 | 独立字段/记录定位继续读取同一 sheet ID |
| 8 | `dingtalk_create_aitable_field` | 步骤 6 base/sheet ID；新字段名称和类型 | 返回稳定 field ID、同一名称和类型 | `dingtalk_list_aitable_fields` 命中同一 field ID/名称/类型 |
| 9 | `dingtalk_update_aitable_field` | 步骤 8 base/sheet/field ID；更新名称 | 回显同一 field ID、更新后名称和类型 | `dingtalk_list_aitable_fields` 命中更新结果 |
| 10 | `dingtalk_insert_aitable_records` | 明确 base ID、sheet ID、单条字段映射 | 返回且仅返回一个新 record ID | `dingtalk_get_aitable_record` 读取同一 record ID |
| 11 | `dingtalk_update_aitable_records` | 步骤 10 base/sheet/record ID；更新字段映射 | 回显 record ID 集合与请求完全一致 | `dingtalk_get_aitable_record` 返回更新后的字段 |
| 12 | `dingtalk_send_message_to_group_by_robot` | 受信当前来源群；固定 title/text | `processQueryKey` 只证明请求已受理 | 记录受理标识摘要；群内事实由原用户核验，不宣称已送达 |
| 13 | `dingtalk_batch_send_message_to_users_by_robot` | 同一 Job 搜索并核实的全部目标 user ID；固定 markdown | `processQueryKey` 与受理/过滤/流控/无效计数 | 计数集合自洽；不回显收件人 ID，不宣称已送达 |
| 14 | `dingtalk_send_work_notification` | 当前用户本人；固定 title/text | task ID 只证明异步任务已提交 | `dingtalk_get_work_notification_progress/result` 查询同一 task ID |

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

## AI 表格数据表创建（已确认并由独立 Job 回查）

- 用户明确允许在“新浪热搜”中创建并保留验收数据后，向原钉钉私聊发送仅调用 `dingtalk_create_aitable_sheet` 的单 mutation 请求；目标 base ID 为 `Amq4vjg895Oedmm5Tx5MqX5g83kdP0wQ`，名称为 `Enterprise Agent MCP 验收 20260831`，并明确禁止修改或删除任何已有资源。
- 新入口 `channel_event_e9cad91c260b485c81deb953360c5ad9` 创建 Job `job_4e7fd2944aa8441ea6c0cbe55ee80f88`；Job 为 `SUCCEEDED`，冻结 r29/r44、39 个当前上下文 Tool，snapshot/authorization hash 分别为 `56d5673cbc9b5772b25442e6bae54e2495449744ffc1829943c32d62d83fd100` 与 `5d79ca1600db0f1dba933ac22a1e8d40bef28ed1c16842e7079fe382b8814130`。
- 真实 Tool Call `dingtalk_create_aitable_sheet/SUCCEEDED` 创建 Intent `action_5f4f32e88fd642ee9b6595ed0c167558`。审计先记录 `external_action.prepared/PENDING_CONFIRMATION`；卡片 CREATE Outbox 一次投递成功，确认前没有 Provider 执行。
- 原用户随后通过确认卡回调批准；Intent 于 `2026-08-31T11:54:29.853113+00:00` 获批，仅执行 1 次，并于 `2026-08-31T11:54:31.613094+00:00` 进入 `SUCCEEDED`。Provider 严格响应返回新 sheet ID `shhqkza` 和同一名称；结果卡一次更新成功，无错误码。
- 写入后只读复核确认 r28/r43、r29/r44 的 Publication ID、revision 和 config hash 均保持原值；历史基线 Job `job_df08fb56b75a4f58b203a5363a79787a` 与修正后只读 Job `job_3c0c9d05ca35433380c236962be1ac91` 的状态、Tool 数、snapshot/authorization hash 也均未被改写。
- 用户另行允许发送只读回查消息后，新入口 `channel_event_542f3cce110047a296a9af642249cc6e` 创建 Job `job_3b2b2bf348b148bcac74069b7107c5a6`。该 Job 冻结 r29/r44、39 个 Tool，snapshot/authorization hash 分别为 `50a0c1b01e310f94cdffd3f55d36a20fc48785eaebca4d8de258d607cdc8e19d` 与共同授权 hash。
- 回查 Job 仅调用 `dingtalk_list_aitable_sheets` 和 `dingtalk_get_aitable_sheet`，两次均为 `SUCCEEDED`：列表真实返回 3 个 sheet，其中名称 `Enterprise Agent MCP 验收 20260831` 与 `sheet_id=shhqkza` 唯一匹配；详情再次返回相同 base ID、sheet ID 和名称。Intent 与卡片 Outbox 均为 0，结果一次投递成功；由此完成数据表创建的 Provider 写入与独立只读事实闭环。

## AI 表格数据表改名（首次过期、第二次结果不确定、修复后已确认回查）

- 用户允许发送改名验收消息后，新入口 `channel_event_899eae349e7d451cbc63edbf325dd9e6` 创建 Job `job_b5ea95e8ecbf496986d441ca8a1f9075`，冻结 r29/r44；目标严格固定为 base ID `Amq4vjg895Oedmm5Tx5MqX5g83kdP0wQ`、sheet ID `shhqkza`，新名称为 `Enterprise Agent MCP 验收 20260831 UPDATED`。
- 真实 Tool Call `dingtalk_update_aitable_sheet/SUCCEEDED` 创建 Intent `action_ee366c5789cb45fab8e83df2f8fc53f9`。首次观测为 `PENDING_CONFIRMATION`、`execution_attempts=0`，没有 approved/completed 时间、Provider request ID 或错误码；CREATE 卡片 Outbox `action_card_9f5fe54081da4d9c92f86d6def9195ed` 一次投递成功。
- 该卡片于北京时间 `20:23:51` 到期；原用户随后点击时，Intent 于 `2026-08-31T12:25:03.039512+00:00` 转为 `EXPIRED`。`execution_attempts=0`、无 approved 时间、Provider request ID 或错误码，审计仅新增 `external_action.expired/EXPIRED`，因此数据表没有改名。
- 原用户重新允许发送后，新入口 `channel_event_2171302f509d4072b19e407c2baeb263` 创建全新 Job `job_b776935b60ef4dd8a926c726261b2ba2`。Job 冻结 r29/r44、39 个 Tool，snapshot/authorization hash 为 `39a727200e51893a1cfa7aa7a1837b79c66f428807ab415b5f397457afaa3194` 与 `5d79ca1600db0f1dba933ac22a1e8d40bef28ed1c16842e7079fe382b8814130`；没有复用或改写首个过期 Job/Intent。
- 第二次真实 `dingtalk_update_aitable_sheet/SUCCEEDED` Tool Call 创建 Intent `action_59970b4f4e1d44ad9bb14073a8be242d`，CREATE 卡 `action_card_ba713d003b254e66aaa7bcb238017dad` 一次投递成功。原用户约 8 秒后确认，Intent 仅执行 1 次；结果为 `FAILED_UNCERTAIN/dingtalk_response_invalid`，结果卡一次更新成功。
- 该失败发生在 `PUT` 已返回后对响应强制要求 `id/name` 的旧实现，因此不能断言数据表已改名，也不能断言未改名。实现已改为以同一 operator 对同一数据表执行独立 GET 后置条件，只有稳定 ID 与新名称同时精确匹配才成功；相关 97 项回归、Ruff、mypy、OpenSpec strict validation 与 `git diff --check` 均通过，`dingtalk-mcp` 和 `external-action-worker` 新镜像已重建并健康运行。新的原用户确认闭环完成前不得宣称改名成功。
- 修复部署后，原用户自行发送相同的单 mutation 验收请求；新入口 `channel_event_77512a8f7af347fbb45aae3cba25056a` 创建 Job `job_88c9e3978e1745c9991555fb43f9928e`，冻结 r29/r44、39 个 Tool，snapshot/authorization hash 为 `f5af91006f1fb062b17c64936cba578bc97bd5ec48f8ac1295babb75a2287df8` 与共同授权 hash。该 Job 仅有一次 `dingtalk_update_aitable_sheet/SUCCEEDED` Tool Call。
- 新 Intent `action_5e4511d826634f01bd41c47e6a897b1c` 与 CREATE 卡 `action_card_341f483fbf9d4662a22e8af73fef56eb` 均为全新事实。原用户在卡创建约 11 秒后确认，Intent 仅执行 1 次并进入 `SUCCEEDED`；结果为 `sheet_id=shhqkza`、`name=Enterprise Agent MCP 验收 20260831 UPDATED`、`updated=true`，无错误码，RESULT_UPDATE 卡 `action_card_c03ef27d3f694aceb97d4c8c2514454a` 一次成功。
- 此 `SUCCEEDED` 由修复后的 Provider 在 `PUT` 后以同一 operator 对同一 `base_id/sheet_id` 执行 GET，并精确匹配稳定 ID 与新名称后产生，不是请求参数回填。历史创建 Intent 仍为 `SUCCEEDED/1`，首次改名 Intent 仍为 `EXPIRED/0`，旧解析失败 Intent 仍为 `FAILED_UNCERTAIN/1`；对应历史 Job 的状态、39 个 Tool 及两项 hash 均未改写。数据表改名已形成确认、执行与 Provider 回读闭环。

## AI 表格字段与记录写入前定位（已通过）

- 原用户自行发送已授权的只读定位请求后，新入口 `channel_event_feaac1a6ccde486db612a49bd50b46c1` 创建 Job `job_92412a3252c74a9689ea35733e94cfcc`。Job 为 `SUCCEEDED`，冻结 Agent r29/Application r44 和 39 个当前上下文 Tool；snapshot/authorization hash 分别为 `ce7f9514d84e042ca31d80c73a273fa838e9ad96db3fe911136afe30c1e8d3a1` 与 `5d79ca1600db0f1dba933ac22a1e8d40bef28ed1c16842e7079fe382b8814130`。
- 本 Job 仅调用 `dingtalk_list_aitable_fields` 与 `dingtalk_list_aitable_records`，两次均为 `SUCCEEDED`。目标固定为 base ID `Amq4vjg895Oedmm5Tx5MqX5g83kdP0wQ`、sheet ID `shhqkza`；字段列表返回 1 项：`field_id=v3IH50w`、名称 `标题`、类型 `text`，`returned=1`、`truncated=false`。
- 记录列表为真实空结果：`returned=0`、`truncated=false`，record ID 列表为空；本次未读取、记录或交付任何记录字段值。Action Intent 与卡片 Outbox 均为 0，没有调用 mutation。
- 历史基线 Job、修正后只读 Job、数据表创建及三次改名 Job 的状态、Tool 数、snapshot/authorization hash 均保持原值；创建、过期、旧解析失败和修复后成功的四个相关 Intent 也分别保持 `SUCCEEDED/1`、`EXPIRED/0`、`FAILED_UNCERTAIN/1`、`SUCCEEDED/1`。
- 该定位允许下一步在同一验收数据表创建一个独立字段，并在确认及只读回查成功后复用其稳定 field ID 做字段更新；记录新增/更新仍必须等待各自独立确认卡，不能因当前空记录结果绕过确认。

## AI 表格字段创建（已确认并由独立 Job 回查）

- 原用户自行发送单 mutation 请求后，新入口 `channel_event_0b3ff7117388497ba608f8b630f3319d` 创建 Job `job_4bc9ad2e9472451f964c9c34d03ff1c6`。Job 为 `SUCCEEDED`，冻结 Agent r29/Application r44 和 39 个当前上下文 Tool；snapshot/authorization hash 分别为 `7e3064a51eaf6f2cb8dc83f20a0e1cdbc05e237479d19fd547a59b7629807875` 与 `5d79ca1600db0f1dba933ac22a1e8d40bef28ed1c16842e7079fe382b8814130`。
- 本 Job 仅调用一次 `dingtalk_create_aitable_field`，Tool Call 为 `SUCCEEDED`，创建全新 Intent `action_235e5cf916dd47549baaf9a9ca334450` 和 CREATE 卡 `action_card_4b00051836264d1b9b71c5c050af831f`。确认目标固定为 base ID `Amq4vjg895Oedmm5Tx5MqX5g83kdP0wQ`、sheet ID `shhqkza`、名称 `Enterprise Agent MCP 验收字段 20260831`、类型 `text`。
- 原用户在卡片有效期内确认；Intent 仅执行 1 次，于 `2026-08-31T13:14:30.727989+00:00` 进入 `SUCCEEDED`，Provider 返回 `created=true`、稳定 field ID `ayCCk1p`、同一名称和 `text` 类型，无错误码；RESULT_UPDATE 卡 `action_card_bdd2ff2040b54a69beb548d80851b7d0` 一次更新成功。
- 历史基线、修正后只读、数据表创建/改名及字段/记录定位 Job 的状态、Tool 数和两项 hash 均保持原值，历史数据表 Intent 状态与执行次数也未变化。
- 原用户另行发送只读回查后，新入口 `channel_event_2c72d1ad8654455aa34b459b6d459fb7` 创建 Job `job_6ae61e0a25954bf186717331e8958814`。Job 为 `SUCCEEDED`，冻结 r29/r44、39 个 Tool；snapshot/authorization hash 分别为 `4290d7e1f4a71d921797455c05a114e097b0791bd63da38a4f1b470fe4a42879` 与共同授权 hash。
- 回查 Job 仅调用一次 `dingtalk_list_aitable_fields/SUCCEEDED`，返回两个字段且 `truncated=false`：新字段 `ayCCk1p/Enterprise Agent MCP 验收字段 20260831/text` 唯一命中，原字段 `v3IH50w/标题/text` 仍存在。该 Job 的 Action Intent 和卡片 Outbox 均为 0，没有 mutation 或其他资源变更；由此完成字段创建的确认、单次 Provider 执行和独立只读事实闭环。

## AI 表格字段更新（已确认并由独立 Job 回查）

- 原用户自行发送单 mutation 更新请求后，新入口 `channel_event_24cdeaec5d7741f78a4d573b1c222341` 创建 Job `job_bc06fc4bc626410ba1293b633c04da7e`。Job 为 `SUCCEEDED`，冻结 Agent r29/Application r44 和 39 个当前上下文 Tool；snapshot/authorization hash 分别为 `991c2142ec5940bde45119c84703bc10cda0391d3506a48e55213973b53ef1a6` 与共同授权 hash。
- 本 Job 仅调用一次 `dingtalk_update_aitable_field`，Tool Call 为 `SUCCEEDED`，创建全新 Intent `action_a288162b6d924cb986c84fd7add37653` 和 CREATE 卡 `action_card_6bdcd8db351c4c1f980b3c8a65a933fb`。目标固定为同一 base ID、sheet ID、`field_id=ayCCk1p`，新名称为 `Enterprise Agent MCP 验收字段 20260831 UPDATED`。
- 原用户在有效期内确认；Intent 仅执行 1 次，于 `2026-08-31T13:31:00.551615+00:00` 进入 `SUCCEEDED`，Provider 返回同一 `field_id=ayCCk1p` 和 `updated=true`，无错误码；RESULT_UPDATE 卡 `action_card_4e4aa4e9d2f845a8973138b283b962f0` 一次更新成功。
- Provider 写入响应不含新名称，因此未仅凭 `updated=true` 证明字段已经呈现确认后的名称。历史基线、数据表及字段创建/回查 Job 的状态、Tool 数和两项 hash 均保持原值。
- 原用户另行发送只读回查后，新入口 `channel_event_ff3c71bf74324c949c93541da384d0b7` 创建 Job `job_435a3db6790b4295801764bfd7f6f403`。Job 为 `SUCCEEDED`，冻结 r29/r44、39 个 Tool；snapshot/authorization hash 分别为 `07da0758f5631a441800d3e9c5b6492738d49a10dcecbb25e0acb345538db6e8` 与共同授权 hash。
- 回查 Job 仅调用一次 `dingtalk_list_aitable_fields/SUCCEEDED`，返回两个字段且 `truncated=false`：`field_id=ayCCk1p` 唯一命中新名称 `Enterprise Agent MCP 验收字段 20260831 UPDATED` 和 `text` 类型，旧名称已不存在，原 `v3IH50w/标题/text` 仍存在。该 Job 的 Action Intent 与卡片 Outbox 均为 0；由此完成字段更新的确认、单次 Provider 执行和独立只读事实闭环。

## AI 表格记录新增（已确认并由独立 Job 回查）

- 原用户自行发送单 mutation 请求后，新入口 `channel_event_077e69c737cc46c1b7e9ecf55bb66f11` 创建 Job `job_575218116e68495aaa7c078e2855d024`。Job 为 `SUCCEEDED`，冻结 Agent r29/Application r44 和 39 个当前上下文 Tool；snapshot/authorization hash 分别为 `b3b102c2532b0da582a58ec97cca28bd39393a8c4acdabfb9a94df85f5f43028` 与共同授权 hash。
- 本 Job 仅调用一次 `dingtalk_insert_aitable_records`，Tool Call 为 `SUCCEEDED`，创建全新 Intent `action_158d68fa387247bf988309959253bc48` 和 CREATE 卡 `action_card_374a62ddeb764ecbbd6bc5e175c503ef`。确认内容固定为同一 base/sheet、仅 1 条记录和字段 `Enterprise Agent MCP 验收字段 20260831 UPDATED`。
- 原用户在有效期内确认；Intent 仅执行 1 次，于 `2026-08-31T13:41:44.591036+00:00` 进入 `SUCCEEDED`。Provider 严格返回 `inserted_count=1` 且仅有新 `record_id=kdmhXcUThP`，无错误码；RESULT_UPDATE 卡 `action_card_c639f0b494914b04b28dea0127433c3a` 一次更新成功。
- 原用户另行发送单记录只读回查后，新入口 `channel_event_1e01b819eeb44989a4ce04c6b5ae1799` 创建 Job `job_edd511f57d264285aaa6231af9e24537`。Job 为 `SUCCEEDED`，冻结 Agent r29/Application r44 和 39 个当前上下文 Tool；snapshot/authorization hash 分别为 `9ca7d5724f7d90165b8f852a6a583d727925f22bbf11b61063ea062171dda2dd` 与共同授权 hash。
- 回查 Job 仅调用一次 `dingtalk_get_aitable_record/SUCCEEDED`，精确读取 `record_id=kdmhXcUThP`；字段 `Enterprise Agent MCP 验收字段 20260831 UPDATED` 的值严格等于 `记录验收 20260831`。Job 的 Action Intent 与卡片 Outbox 均为 0，没有调用 mutation，也未返回其他记录字段值。
- 历史基线、修正后只读、字段创建/更新/回查及记录新增 Job 的状态、Tool 数和两项 hash 均保持原值；字段创建、字段更新和记录新增 Intent 仍分别为 `SUCCEEDED/1`。由此完成记录新增的确认、单次 Provider 执行、稳定 record ID 与独立只读事实闭环。

## AI 表格记录更新（已确认并由独立 Job 回查）

- 原用户自行发送单 mutation 更新请求后，新入口 `channel_event_2a1afd831ea24123aaf30b3c15e7b8b7` 创建 Job `job_094fb12090454032a064abd1c9187da5`。Job 为 `SUCCEEDED`，冻结 Agent r29/Application r44 和 39 个当前上下文 Tool；snapshot/authorization hash 分别为 `e185ebd2503181f1a4663761e40ebc73bc897df7c4469bba40d21906cf3d4cff` 与共同授权 hash。
- 本 Job 仅调用一次 `dingtalk_update_aitable_records/SUCCEEDED`，创建全新 Intent `action_bae948cafdeb46af90fd84b5ab3e8783` 和 CREATE 卡 `action_card_0d9ccb2ae581413982f5f7e290955eed`。冻结参数严格为同一 base/sheet、仅 1 条 `record_id=kdmhXcUThP`，字段 `Enterprise Agent MCP 验收字段 20260831 UPDATED` 的目标值为 `记录验收 20260831 UPDATED`。
- 原用户在有效期内确认；Intent 仅执行 1 次，于 `2026-08-31T14:51:54.804774+00:00` 进入 `SUCCEEDED`。Provider 严格返回 `updated_count=1` 且仅有同一 `record_id=kdmhXcUThP`，无错误码；RESULT_UPDATE 卡 `action_card_0f5a326cb85a48009a631475e5aebdb2` 一次更新成功。
- 原用户另行发送单记录只读回查后，新入口 `channel_event_063dbf97e82343269e877cf061a7a799` 创建 Job `job_f74dd768cdf340a9a6a8b61d139cb950`。Job 为 `SUCCEEDED`，冻结 Agent r29/Application r44 和 39 个当前上下文 Tool；snapshot/authorization hash 分别为 `038810f7b7bd0ae1823456aa9c585560f1ee0aee89aa7ec1f012bd8f31bac496` 与共同授权 hash。
- 回查 Job 仅调用一次 `dingtalk_get_aitable_record/SUCCEEDED`，精确读取 `record_id=kdmhXcUThP`；字段 `Enterprise Agent MCP 验收字段 20260831 UPDATED` 的值严格等于 `记录验收 20260831 UPDATED`。Job 的 Action Intent 与卡片 Outbox 均为 0，没有调用 mutation，也未返回其他记录字段值。
- 历史基线、修正后只读、字段创建/更新/回查、记录新增/回查及记录更新 Job 的状态、Tool 数和两项 hash 均保持原值，四个相关 Intent 仍各为 `SUCCEEDED/1`。由此完成记录更新的确认、单次 Provider 执行、稳定 record ID 与独立只读事实闭环。

## 群消息首次尝试（应用路由未配置，入口安全拒绝）

- 原用户在真实钉钉群发送验收请求后，入口事件 `channel_event_939296503ca14591872ed48801660eb8` 被标记为 `REJECTED/route_not_matched`，有界错误为“当前机器人未配置可用的业务应用，请联系管理员”；安全摘要确认来源 `conversationType=2`，但事件没有 `job_id`。
- 应用 `assist03` 当前激活的 Application r44/local deployment r18 只有 1 条 `dingtalk_private` 路由，连接器为 `connector_b2013081874a4a7dadec3e3a86f10c14`；`dingtalk_group` 活动路由为 0。该群因此尚未绑定到业务应用，路由解析在 Agent/Tool 之前失败。
- 本次没有 Job、Tool Call、Action Intent、确认卡或 Provider 请求，不能计作群消息 mutation，也不存在本次可确认的外部操作。管理员必须为该真实群创建 `dingtalk_group` 触发器，形成新 Application Revision/Publication 并重新激活 local deployment；之后由原用户在群内发送全新请求，不得复用本次拒绝事件。

## 群消息（路由补齐后已确认并由原用户回查）

- 管理员补齐真实来源群路由后，应用 `assist03` 形成 Application r45、Publication `business_app_publication_66467713f8114abfb96e6a20e9dac65f` 和 local deployment r19；活动路由同时包含 1 条 `dingtalk_group` 与 1 条 `dingtalk_private`，连接器均为 `connector_b2013081874a4a7dadec3e3a86f10c14`。配置 hash 为 `3ce384bbb1ed487ab59189cf7bf050e1703f64fda20bda7be7920545ebc8c817`，群路由键仅记录不可逆摘要 `0055c0877dea`。
- 原用户从已绑定的真实钉钉群发送全新请求后，入口 `channel_event_b946866ae7d54b31bafd4920d295ea62` 进入 `JOB_CREATED` 并创建 Job `job_ea209c09644f49ce88ea9db7f0ac7af0`。Job 为 `SUCCEEDED`，冻结 Agent r29/Application r45 和 39 个当前上下文 Tool；snapshot/authorization hash 分别为 `189016590caaef8b53a7cf97fcb2100c2fb27e834a08fa40f09b37cb530b38b6` 与 `2f048dd3d999927a1a68d0307684aed728a85934414107a329fbf4be826ba6a0`，Tool 契约判定为 `MATCH`。
- 本 Job 仅调用一次 `dingtalk_send_message_to_group_by_robot/SUCCEEDED`，创建全新 Intent `action_ade67c78965d4c5d8ccfe079df50ffc3` 和 CREATE 卡 `action_card_1e154e00253142af924b55a4e2c5d8ce`。冻结目标中的 `open_conversation_id` 与该入口事件的受信 `conversationId` 完全一致，机器人 Code 非空；目标会话仅记录不可逆摘要 `7ae5cf334507`，未接受模型传入的任意群目标。
- 原用户在有效期内确认；Intent 仅执行 1 次并进入 `SUCCEEDED`，Provider 返回 `accepted=true` 与非空 `message_request_id`，其不可逆摘要为 `f77b30857ae0`，无错误码。RESULT_UPDATE 卡 `action_card_4facd4ceceb0480b8f7b425f807921ba` 一次更新成功。该响应只证明请求受理，平台没有将其描述为最终送达。
- 原用户随后在目标群内回查到该消息，补足 Provider 之外的送达事实。首次 `REJECTED/route_not_matched` 事件仍保持无 Job，所选历史 Job 的状态、Tool 数及两项 hash 均未改变；由此完成群消息的可信路由、确认、单次 Provider 执行和外部事实回查闭环。

## 批量个人机器人消息（首次过期，重发后已确认并由原用户回查）

- 首次私聊入口 `channel_event_671de0ff5db34c1db72973360b7f42eb` 创建 Job `job_440e54920bbb4780b0e5fe44341ca2e5`。该 Job 冻结 Agent r29/Application r45 和 39 个 Tool；snapshot/authorization hash 分别为 `29dcee481a2f408eed70b92241fd0cddbdad3321e5421d3c8d45cf78ca151331` 与 `2f048dd3d999927a1a68d0307684aed728a85934414107a329fbf4be826ba6a0`。它完成用户搜索和两个候选详情查询，并创建 Intent `action_35c50e4f2c48437ea22cc77d0ffad20a`；CREATE 卡 `action_card_561fbb9c46a741b1b29c88daff967ab9` 一次投递成功，但原用户未在有效期内确认，Intent 最终保持 `EXPIRED/0`，没有 Provider 执行或结果卡。
- 原用户重新发送全新请求后，入口 `channel_event_0eddf785bd5249d2999b8977e2751f21` 创建 Job `job_8b0dd6ad5e1045dcb3d9036f9d0fbcc2`。Job 为 `SUCCEEDED`，冻结同一 r29/r45 和 39 个 Tool；snapshot/authorization hash 分别为 `b77fd5a56e2ce8deb552b13ee6ee7772ec6f760c7f3dcafa9a046eafd792f60e` 与共同授权 hash，Tool 契约判定为 `MATCH`。
- 新 Job 严格按序执行 `dingtalk_search_users/SUCCEEDED`、两次 `dingtalk_get_user/SUCCEEDED` 和一次 `dingtalk_batch_send_message_to_users_by_robot/SUCCEEDED`。搜索安全摘要为 `users=2`；两个详情请求的 payload hash 集合与最终 Intent 中两个不同收件人 ID 逐项匹配，证明批量目标确实来自本 Job 的候选核实，不是历史候选或按姓名猜测。收件人集合仅记录不可逆摘要 `4bbe5657c291`，不回显用户 ID。
- 批量 Tool 创建全新 Intent `action_900bf27d49e44ef9a14cca60d7827cab` 和 CREATE 卡 `action_card_39cd4faa751e420eb5b06c8b62423dbf`。Intent 冻结 2 个不同 `user_id`，`_target.recipient_count=2`、机器人 Code 非空，且标题与正文摘要均匹配本次固定验收参数；未分拆成两个写入，也未改用工作通知或群消息。
- 原用户在有效期内确认；Intent 仅执行 1 次，于 `2026-09-01T01:47:57.327543+00:00` 进入 `SUCCEEDED`。Provider 返回非空消息请求标识和 `accepted=true`、`fully_accepted=true`、`recipient_count=2`、`accepted_count=2`、`not_accepted_count=0`、`filtered_count=0`、`flow_controlled_count=0`、`invalid_count=0`；请求标识仅记录不可逆摘要 `eaa31b8b9afc`。RESULT_UPDATE 卡 `action_card_b8afe85939484eec89cf56587bbdc0d2` 一次更新成功；平台只声明两名目标均被 Provider 受理。
- 原用户随后在两个收件端完成消息回查，补足 Provider 之外的送达事实。首次过期 Intent 仍为 `EXPIRED/0`，群消息及所选 AI 表格历史 Job 的状态、Tool 数和两项 hash 均保持原值；由此完成“同一 Job 搜索并核实两个用户、单批确认、单次 Provider 执行和外部事实回查”的闭环。

## 工作通知（已确认并由独立只读 Job 回查）

- 原用户自行发送单 mutation 请求后，新入口 `channel_event_2feac97b62d24f72a2a611e3bcaa5291` 创建 Job `job_5b69a2c68bf64307a50e296279315e69`。Job 为 `SUCCEEDED`，冻结 Agent r29/Application r45 和 39 个当前上下文 Tool；snapshot/authorization hash 分别为 `8b4f743aca07a80733bee7edfc01ae37e9be47e39eeb54d9f87ed368062dde4a` 与 `2f048dd3d999927a1a68d0307684aed728a85934414107a329fbf4be826ba6a0`，Tool 契约判定为 `MATCH`。
- 本 Job 仅调用一次 `dingtalk_send_work_notification/SUCCEEDED`，创建全新 Intent `action_ba887b3b9e494ffda2ca1102301976d3` 和 CREATE 卡 `action_card_88802986ce40493a8b5a56e58892aace`。Intent 的 actor 与 Job 当前用户一致，冻结外部主体和 union 身份均与 Job 绑定的钉钉身份一致，Provider `staff_id` 与同一外部主体一致，来源连接器也未漂移；工作通知 Agent ID 非空，目标安全摘要严格为“当前用户本人”。
- 原用户在有效期内确认；Intent 仅执行 1 次，于 `2026-09-01T02:01:43.549999+00:00` 进入 `SUCCEEDED`。Provider 返回 `accepted=true` 和稳定 `task_id=3431404785476`，无错误码；RESULT_UPDATE 卡 `action_card_501f01598f994c5799976ffd70fe5267` 一次更新成功。该结果只证明异步发送任务已提交，不证明最终发送状态或已读状态。
- 原用户另行发送只读回查后，新入口 `channel_event_116cd1ca821e4cd58bfacba700bce507` 创建 Job `job_5f8bb61929ba428a9f649e366b690fa6`。Job 为 `SUCCEEDED`，冻结 r29/r45、39 个 Tool；snapshot/authorization hash 分别为 `594e07237fccb2ba5d26ff3297e1d9a7ac853c03c07c645825fed247bc7d5425` 与共同授权 hash，Tool 契约判定为 `MATCH`。
- 回查 Job 严格按序且仅调用 `dingtalk_get_work_notification_progress/SUCCEEDED` 和 `dingtalk_get_work_notification_result/SUCCEEDED`；两个请求的 payload hash 都精确匹配同一 `task_id=3431404785476`。Provider 返回 `status=2`、`progress_percent=100`、`invalid_user_count=0`、`forbidden_user_count=0`、`failed_user_count=0`、`read_user_count=1`、`unread_user_count=0`、`invalid_department_count=0`、`truncated=false`，未在证据中回显任何用户或部门 ID。
- 只读回查 Job 的 Action Intent 与卡片 Outbox 均为 0；工作通知 Intent 仍为 `SUCCEEDED/1`。所选发送前基线、AI 表格、群消息、批量个人消息、工作通知写入及回查 Job 的状态、Tool 数和两项 hash 均保持原值，首次群路由拒绝事件仍为 `REJECTED/route_not_matched` 且无 Job。由此完成工作通知的当前用户目标、确认、单次 Provider 提交、独立进度/结果回查和历史事实不变性闭环。

## 2026-08-31 完成性审计

- 发送前基线中，r28 外部操作意图数为 0；`PENDING_CONFIRMATION`、`APPROVED`、`EXECUTING` 状态的 r28 意图均为 0，证明验收消息发送前未偷偷准备或执行任何写入。
- 用户明确允许发送两条验收消息后，r28 新增且仅新增上述 1 个待办 Intent；首次观测为 `PENDING_CONFIRMATION`，当时 `APPROVED`/`EXECUTING` 均为 0、执行次数为 0。只读复验 Job 没有创建确认卡或写入 Intent。
- 原用户确认后，该 Intent 仅执行 1 次并成功；写入后复核历史 `job_df08fb56b75a4f58b203a5363a79787a` 和四个 5.4 只读 Job 的状态、Publication ID、Tool 数、snapshot hash 与 authorization hash，均与写入前基线逐项相等。
- 待办创建和更新两个 Intent 现均各执行 1 次并成功，均返回同一稳定 task ID；第二次写入后再次复核历史基线 Job，未发现快照或授权 hash 改写。
- 待办创建、更新、完成三个 Intent 现均各执行 1 次并成功，均返回同一稳定 task ID；第三次写入后再次复核历史基线 Job，仍未发现状态、Tool 数、snapshot hash 或 authorization hash 改写。
- 日程创建的第三次入口使用全新 Job/Intent，在有效期内确认后仅执行 1 次并成功；钉钉日历页面显示同一标题、日期和 10:00 开始时间。此前零 Tool Call Job 和已过期 Intent 均保持原状态，历史基线 Job 的状态、Tool 数及两项 hash 仍不变。
- 日程更新使用同一稳定 event ID 创建独立 Job/Intent，在有效期内确认后仅执行 1 次并成功；钉钉日历页面显示更新后的标题和 11:00 开始时间，历史基线 Job 的状态、Tool 数及两项 hash 再次保持不变。
- AI 表格旧 Job 的 search 成功、list sheets Provider 权限拒绝保持为历史失败证据；新 r29/r44 Job 已通过 v1 + operator 完成 9 项只读验收并真实返回 2 个 sheet。新旧 Job 均未被改写，当前剩余阻塞只在确认型写入验收。
- AI 表格数据表创建使用新 r29/r44 Job、独立 Action Intent 和原用户卡片回调，仅执行 1 次并返回新 sheet ID `shhqkza`；独立只读 Job 随后从 3 个 sheet 中唯一匹配该名称和 ID并成功读取详情。写入后新旧 Publication 与历史 Job 快照仍未被改写，该 mutation 已形成完整事实闭环。
- AI 表格数据表改名在修复后的第三个独立 Job 中完成确认、单次 Provider 执行和同 operator GET 后置条件回读；此前过期和结果不确定的 Intent 保持原状态。随后字段/记录只读定位仅执行两次 read Tool，确认 `shhqkza` 当前有 1 个 `text` 字段且 0 条记录，Intent 与卡片均为 0。
- AI 表格字段创建使用全新 Job/Intent，仅执行 1 次并返回稳定 field ID `ayCCk1p`；独立只读 Job 随后从两个字段中唯一命中该 ID、名称和 `text` 类型，同时确认原“标题”字段未被覆盖。创建与回查后历史 Job、Intent 和 hash 均未改变。
- AI 表格字段更新复用稳定 `field_id=ayCCk1p` 创建独立 Job/Intent，仅执行 1 次；独立只读 Job 唯一命中 `UPDATED` 新名称并确认旧名称已消失、原“标题”字段仍存在。更新与回查后历史 Job、Intent 和 hash 均未改变。
- AI 表格记录新增在独立 Job/Intent 中仅执行 1 次，返回唯一 `record_id=kdmhXcUThP`；独立只读 Job 随后只调用 `dingtalk_get_aitable_record`，确认同一记录的验收字段值严格等于 `记录验收 20260831`，且未创建 Intent 或卡片。新增与回查后所选历史 Job、Intent 和 hash 均未改变。
- AI 表格记录更新复用同一稳定 record ID 创建独立 Job/Intent，仅执行 1 次并返回 `updated_count=1` 与完全一致的 record ID；CREATE/RESULT_UPDATE 卡均一次成功。独立只读 Job 随后仅调用一次单记录读取，确认目标字段值严格等于 `记录验收 20260831 UPDATED`，且未创建 Intent 或卡片。更新与回查后所选历史 Job、Intent 和 hash 均未改变。
- 群消息首次真实来源尝试在入口阶段因应用缺少该群的 `dingtalk_group` 活动路由而 `REJECTED/route_not_matched`；事件未创建 Job，因此没有 Tool、Intent、卡片或 Provider 执行。该失败保持为前置配置证据，不能计入已完成 mutation。
- 补齐群路由并发布 Application r45/local deployment r19 后，新群入口创建独立 Job；它只执行一次群机器人消息 Tool，受信入口群与冻结 Provider 目标完全一致。原用户确认后 Intent 单次执行并由 Provider 受理，随后在目标群内完成事实回查；历史拒绝事件及所选旧 Job 快照保持不变，群消息 mutation 已形成完整闭环。
- 批量个人消息首次 Intent 因未及时确认而保持 `EXPIRED/0`；重发后的全新 r29/r45 Job 先搜索 2 个候选，再用两个详情请求逐一覆盖最终两个不同收件人，只创建一个批量 Intent。原用户确认后 Provider 单次执行并返回 2/2 受理、三类未受理计数均为 0，随后完成两个收件端回查；历史过期 Intent 和所选旧 Job 均未被改写。
- 工作通知使用全新 r29/r45 Job 和当前用户本人目标，只执行一次 mutation Tool；原用户确认后 Provider 单次执行并返回稳定 task ID，结果卡一次更新成功。独立只读 Job 随后仅调用进度和结果 Tool，两个请求均命中同一 task ID，返回 100% 进度、0 个无效/禁发/失败目标、1 个已读目标和未截断结果；只读 Job 未创建 Intent 或卡片，历史 Job/Intent 均未改写。
- 契约修正前的全量相关组合回归为 106 passed；针对七 profile 分类、官方语义/治理描述、显式排除、notable v2 与 legacy allowlist 的完成性子集曾得到 14 passed。该历史测试结果不能证明 v2 与官方 MCP 语义等价，现由新增 v1/operator 回归替代。
- 当前源码中的 `oapi.dingtalk.com` 仅作为统一 legacy base 存在，实际 `/topapi/` 调用严格等于 6 个 allowlist operation：部门成员、部门详情、子部门、工作通知发送、进度、结果；未发现额外旧端点。
- 发现 notable v2 契约不兼容后，已完成 notable v1 + `operatorId`、三个静态说明 Tool、数据表/字段非删除 mutation、Action Intent 冻结与 Worker 再授权实现；这些变更不能由旧 Job 替代。修正后的本地相关组合回归为 134 passed，Ruff、Mypy 与 OpenSpec strict validation 均通过。
- 当前纳入的 14 个 mutation 已全部完成事实回查：待办创建/更新/完成、日程创建/更新、AI 表格数据表创建/改名、字段创建/更新、记录新增/更新、群消息、批量个人消息和工作通知。每个 mutation 均使用新 Publication、新 Job 和独立确认，Provider 至多执行 1 次；异步消息与工作通知均补充了相应外部事实或官方进度/结果回查，所选历史 Job 和失败/过期 Intent 保持不可变。任务 5.5、5.6 均可标记完成，本 change 的 28 个任务已满足完成条件。
