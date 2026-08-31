# 新版 Publication 与部署证据

取证时间：2026-08-30 至 2026-08-31（Asia/Shanghai）

## 2026-08-31 AI 表格官方契约修正（服务部署后、新 Publication 前）

- Provider 已将 AI 表格资源读写恢复为官方 notable v1 路径，并从已解析的当前钉钉 Principal 注入 `operatorId`；名称搜索继续使用官方 storage v2 搜索契约。
- Tool 目录现为 35 个：21 个只读、14 个 mutation。新增三个本地静态官方说明 Tool，以及数据表创建/改名、字段创建/更新四个确认型 mutation；删除数据表、字段和记录仍显式排除。
- Action Intent 冻结 `operator_id`、`base_id` 及适用的 `sheet_id`/`field_id`，Worker 执行前重新校验当前 Principal 与资源目标；不接受模型自报 `operatorId`。
- 修正后的本地相关组合回归为 134 passed；Ruff、Mypy 与 OpenSpec strict validation 均通过。此节仅证明部署前实现，不代表旧 r28/r43、旧 Job 或线上 Provider 已获得新契约。
- 已重建并重启 `api-server`（`sha256:ceff4ec178afcf774002ecc1dbd2d6d6b74dc68a12c8aed092c554aa5176df2b`）、`agent-worker`（`sha256:d52ef9596baf5977c0a987f39679304d462fd4cda5025e77685104f2dbb5c562`）、`dingtalk-mcp`（`sha256:9b2123fdb336afebd841a03db69af9331220ed34f431173cc324cbf11106df07`）、`external-action-worker`（`sha256:d769a2dde968d2c072c1b2af5132f4f973a9b80c5326576de52897a85becb6c0`）和 `python-agent-runtime`（`sha256:a22a4da388bf67be8e4e9653076001c77ff6aa0fdc8debbd99fdb4d7287d5856`）。除无独立 healthcheck 的 `agent-worker` 为 running 外，其余均为 healthy；API `/api/health` 返回 `status=ok`。
- 容器内现场探针返回 `read=21`、`mutation=14`、`total=35`，并确认三个 delete operation 仍在显式排除集合；Provider 源码探针为 `v1_notable=true`、`operatorId=true`、`v2_notable=false`。`git diff --check`、Compose 配置校验和 Secret 泄漏门禁均通过。
- 原用户登录后已完成新 Agent/Application Publication 与角色授权：Agent r29 为 `agent_publication_15e8a8b678a64830ae5036382fcb576b`，config hash `5c4b66c2ae4889b77ce9f0b9023009f00ec3312e308d2e7058d8955a501abd10`；Application r44 为 `business_app_publication_d7e4034772e141f5be964d6c22891875`，config hash `b64c1066ded72328eeb30b19627ab35b6813b2caeb5c35baca16d672f8733e2c`，已激活到 local deployment r18。两者均冻结 47 个 Tool，其中钉钉 Tool 为 35 个。
- 角色 `role_167e65682b824c2d8a8774a32c986ada` 的业务授权已推进到 r9：应用授权 47 个 Tool、其中钉钉 35 个，新增的三个静态说明 Tool 和四个数据表/字段 mutation 缺失数为 0。该步骤只证明新工具已发布且已授权；尚未创建采用 r29/r44 的新 Job，因此不能声称 AI 表格 Provider 真实验收已经完成。
- 发布后只读复核确认旧 Agent r28 仍为 40 个 Tool、config hash `7f78cc1a830f890a8c315d43a4533535f5104fe19b4eebed68de4dd5accaaed8`；旧 Application r43 仍为 40 个 Tool、config hash `e478f0879b6b622d32adfb2e7599e1efcea0d4c3237b26bd97eb8cd2115288cf`，旧快照未被覆盖。
- 原用户允许发送首条 AI 表格只读验收消息后，入口事件 `channel_event_a8d83e6e4bf5412098477bec83797123` 在创建 Job 前以 `agent_mcp_tool_envelope_mismatch` 被拒绝；`job_id` 为空，因此没有 Tool Call、Action Intent、确认卡或 Provider I/O。原因是 `channel-dispatch-worker` 等共享 Agent Worker 源码、但使用独立 Compose 镜像标签的服务仍运行旧镜像，无法校验 r29 的 47 Tool envelope；不是钉钉权限或 notable Provider 失败。
- 已重建并重启 `channel-dispatch-worker`、`delivery-dispatch-worker`、`file-worker`、`job-dispatch-worker` 和 `webhook-worker`，五者均为 healthy；`channel-dispatch-worker` 容器内探针现识别 35 个钉钉 Tool（21 read + 14 mutation）。失败入口事件保持 REJECTED 且不复用；重发必须取得原用户新的当下发送确认，并创建全新入口事件和 Job。
- 原用户重新允许发送后，新入口事件 `channel_event_81afb33196564634a3acb3f587fe913f` 成功创建全新 Job `job_3c0c9d05ca35433380c236962be1ac91`。Job 冻结 Agent r29/Application r44，状态 `SUCCEEDED`、错误码为空；MCP snapshot hash 为 `ed26185158b21b2c74b43bfc6f3d1c15baceb7307d6c60ef9d6f33f59017cbeb`，authorization hash 为 `5d79ca1600db0f1dba933ac22a1e8d40bef28ed1c16842e7079fe382b8814130`。本 Job 因没有附件上下文冻结 39 个实际可用 Tool，其中钉钉 35 个，七个新增 notable Tool 缺失数为 0。
- 该 Job 真实产生 9 个只读 Tool Call，全部 `SUCCEEDED`：三个静态官方说明、搜索 AI 表格、列出数据表、读取目标数据表、列字段、列记录、读单条记录。安全审计摘要证明搜索返回 1 个 AI 表格、数据表列表返回 2 个 sheet、目标表返回 3 个字段、记录分页返回 5 条；未持久化或回显记录字段值。
- 该 Job 的 Action Intent 数为 0，没有确认卡或 Provider 写入。结果通过 `dingtalk_stream_session_webhook` 一次投递成功，单 chunk、无错误码；因此此前同一 base 的 `list sheets = 0/permission_denied` 已由新 v1 + `operatorId` 真实调用推翻。

## 已完成

- 参数级复核前的 Agent/Application Publication 分别为 `agent_publication_05c116e511ef477f95f25e5e41b4dc35`（`r22`）与 `business_app_publication_2e71cc5450724e63a3f3fd77bbadd65a`（`r37`）。
- 发现并迁移 `dingtalk_get_user` 后，已创建 Agent Publication `agent_publication_e04b5c90dba14edba2c24d9b15ae9027`（`r23`）和 Application Publication `business_app_publication_9f9987172680405e9ac567dbe1cc67d5`（`r38`）。
- 异步消息成功语义复核后，已继续创建 Agent Publication `agent_publication_49d7ccbd2f7b4ce69144b819aa773652`（`r24`）和 Application Publication `business_app_publication_3c86a8cd75494aaab71e92f5fca63a2b`（`r39`）。
- 全量响应边界复核后，已创建 Agent Publication `agent_publication_8bc7df45e1664e2f85129b4c0be8863d`（`r25`）和 Application Publication `business_app_publication_a820950af4d345a1af23d2f3b4619f2e`（`r40`）。
- AI 表格 v2 目标策略纠正后，已创建 Agent Publication `agent_publication_b6c302bf457e4c0383d68fc32829f349`（`r26`）和 Application Publication `business_app_publication_b15def56fed843c8bf72d30298387a44`（`r41`）。
- 全量模型描述语义复核后，已创建 Agent Publication `agent_publication_f4e9634f4cf34debb09dda0e97798679`（`r27`）和 Application Publication `business_app_publication_6165c86f70d149c48728780e76228211`（`r42`）。
- 治理子集参数说明复核后，已创建 Agent Publication `agent_publication_e90646e86d884c758777ca882d4bb4fb`（`r28`）和 Application Publication `business_app_publication_3c5ee20803cb445db48fe0fe9cfbaeb8`（`r43`）。
- local deployment 已推进到 revision `r17`，当前激活 Application Publication 为上述 `r43`，Runtime 状态为 `wired`。
- 钉钉连接器“测试ai机器人”升级到 revision `r6`；独立 `ROBOT_CODE` 已保存，未把工作通知 Agent ID 当作机器人 Code。
- 新 Agent/Application Publication 均固定 40 个 MCP Tool；其中钉钉集合为 28 个（18 read + 10 mutation），旧 `dingtalk_send_robot_message` 未进入新 Publication。
- `dingtalk_get_user` 的 Schema hash 已从旧 `r22/r37` 的 `12770add02b6928c8032429f57bf5460d5f01a4c33188413cf542ed7812ca7ba` 更新为新 `r23/r38` 的 `e9a809e44ede6d9a356c60722fe28000092ddb251b1b7cc19455223b209bf4f4`；旧 Publication 行未被覆盖。
- 角色 `role_167e65682b824c2d8a8774a32c986ada` 的业务授权已原子替换到 revision `r8`：应用数仍为 1、Tool 数仍为 40、数据范围仍为 1；旧 `dingtalk_send_robot_message` 已移除，以下两个新消息 Tool 均已授权：
  - `dingtalk_batch_send_message_to_users_by_robot`
  - `dingtalk_send_message_to_group_by_robot`
- 本次角色授权产生 `authorization.role.business.updated` 审计事件 `audit_b31f018677c443c29fd7eccd4219e012`，状态为 `SUCCEEDED`；替换未修改历史 Publication 或历史 Job 快照。
- 用户再次授权替换旧权限后，现场复核 r8 已包含全部 28 个当前钉钉 Tool，且退役钉钉授权为 0；因此未创建内容完全相同的 r9，也未产生无意义的重复授权审计。
- `api-server`、`admin-web`、`dingtalk-mcp`、`external-action-worker`、`agent-worker` 和 `python-agent-runtime` 均在本次重建后运行；API health 返回 `status=ok`。
- r24 与 r25 的 Agent Publication 均保留 40 个 Tool，r39 与 r40 的 Application Publication 也均保留 40 个 Tool；历史行仍存在且其 config hash 未被改写。r25 的 Agent 配置 hash 与 r24 相同，是因为此次继续收紧 Provider 输出验证而未改变 Agent 草稿配置；Application r40 因固定新的 Agent Publication ID 形成新 hash。
- r26/r41 均保留 40 个 Tool，其中钉钉 Tool 为 28 个；r26 冻结的 AI 表格目标策略已区分名称搜索的 `current_user_aitable_operator`、只读资源的 `enterprise_application_aitable_visible_scope` 和写入资源的 `explicit_aitable_resource_in_application_scope`。历史 r25/r40 仍存在，原 config hash 分别保持 `99e00a22cbd8f3358968999295400f3d6cb8a005b6a78d5cbc7b19612109f69a` 与 `ba16c73795d876616e73c510e1693b49c88a8168647954ae591e4f1e6920084d`。
- r27/r42 也均保留 40 个 Tool，其中钉钉 Tool 为 28 个；现场读取新 Agent snapshot 已确认用户拼音搜索、部门白名单边界、日程能力子集和工作通知 markdown 四项描述均已冻结。角色业务授权仍为 r8，当前钉钉 Tool 无缺失且退役授权为 0。历史 r25/r26 与 r40/r41 的行和 config hash 均保持原值。
- r28/r43 均保留 40 个 Tool，其中钉钉 Tool 为 28 个；现场读取冻结 Agent snapshot 已确认待办更新字段子集、日程更新字段子集、notable v2 记录分页无 filter 和“全部已核实用户进入同一批”四项描述。角色授权仍为 r8（40 个 Tool、28 个钉钉 Tool、缺失 0、退役 0），没有创建无意义的重复授权 revision。历史 r27/r42 仍保留且 config hash 未被改写。
- 初次使用 r28/r43 发起只读验收时，`channel-dispatch-worker` 仍运行旧的独立 Compose 镜像，入口事件 `channel_event_a920c06fac5e43c29e24c060cbca9843` 以 `agent_mcp_tool_envelope_mismatch` 拒绝。容器内对 r28 envelope 与当前 Manifest 复核无差异后，已重建并重启所有共用 `agent-worker` Dockerfile target、但具有独立 Compose 镜像标签的 `channel-dispatch-worker`、`delivery-dispatch-worker`、`file-worker`、`job-dispatch-worker` 和 `webhook-worker`；五个服务随后均为 healthy。
- 1023 字与 626 字验收消息均被钉钉客户端转成“长文本附件”，入口事件分别进入 `ATTACHMENTS_STAGED`，没有创建 Job。为保持真实钉钉入口且不绕过渠道，验收按普通文本阈值拆成 A、B1、B2、C 四条只读消息。
- 四条短消息分别创建 `job_2eb01ce50fb147369117dca351a71361`、`job_6cab4a69d9d641098025334d21db577c`、`job_2647dc88276540d2805945ab4577ec32`、`job_47156cc9d23d45cbba91a70147050142`；四个 Job 均为 `SUCCEEDED`，且均冻结 Agent Publication `agent_publication_e90646e86d884c758777ca882d4bb4fb`（r28）与 Application Publication `business_app_publication_3c5ee20803cb445db48fe0fe9cfbaeb8`（r43）。
- 真实只读调用的有界结果：
  - contacts：`dingtalk_search_users` 成功返回 2 个候选，随后两次 `dingtalk_get_user` 均成功；
  - department：`dingtalk_search_departments` 成功返回 0 个部门，因此详情、子部门和成员列表按条件安全跳过；
  - tasks：`dingtalk_list_todos` 成功返回 0 个未完成待办；
  - calendar：`dingtalk_list_calendar_events` 成功返回 1 条，随后详情与参与者列表均成功，参与者计数为 1；
  - notable：`dingtalk_search_aitables` 成功精确命中 1 个 AI 表格；`dingtalk_list_aitable_sheets` 在平台授权判定 `ALLOW` 后被钉钉 Provider 以 `dingtalk_permission_denied` 拒绝，后续 sheet/field/record 条件调用安全跳过；这证明不是 Job/角色 Tool 授权拒绝。当时归因为 notable v2 应用权限或资源可见范围，后续官方 MCP v1 + operator 成功对照已把根因进一步收敛为接口契约不兼容；
  - notice：`dingtalk_get_work_notification_progress` 与 `dingtalk_get_work_notification_result` 均成功；
  - robot-send-message：该 profile 没有只读 Tool，其真实 mutation/确认卡验收归入 5.5。
- 上述 12 次真实 Tool 调用均来自新 Job；成功响应审计只记录字段名、列表计数、字节数和摘要哈希，未在本证据中读取或记录业务正文、用户目录、凭据或 Provider 原始响应。所有 Tool 的平台授权记录均为 `ALLOW/principal_identity_snapshot_and_tool_grant_allowed`，仅 AI 表格数据表读取在 Provider 边界返回权限拒绝。
- 现场权限拒绝还暴露出诊断压缩缺口：HTTP 401/403 的官方 JSON 错误码此前被全部压缩为 `dingtalk_permission_denied`，无法区分具体钉钉权限点。Transport 现只从最大 64 KiB 的错误 JSON 中提取符合 `^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$` 的 `code/errcode/errorCode`，把该值追加到安全中文摘要和内部 diagnostics；Provider message、嵌套详情、非法/超长 code 和原始响应均被丢弃，稳定平台错误码保持不变。
- 该诊断收紧新增 6 个失败优先用例后，最新钉钉契约/Runtime/多连接器组合回归为 106 passed；Ruff、Provider mypy、OpenSpec strict validation 与 `git diff --check` 均通过。`dingtalk-mcp` 已以镜像 `sha256:b5298f068b2761444eec7e9047d53fcc118129f01251322df3e14e691b4388ae` 重建并健康运行。由于重试仍需代表用户发送钉钉消息，尚未在未获当下确认时自动发起新的 notable v2 真实调用。
- 用户当下确认发送后，短消息只读复验创建 `job_0b5c106f32564195b01a79b69b6b35de`；该 Job 为 `SUCCEEDED`，冻结 r28/r43。`dingtalk_search_aitables` 成功，`dingtalk_list_aitable_sheets` 的平台授权仍为 `ALLOW/principal_identity_snapshot_and_tool_grant_allowed`，随后由钉钉 Provider 拒绝为 `dingtalk_permission_denied`，安全摘要中的官方错误码为 `AccessTokenPermissionDenied`。该证据排除本系统 Job、角色 Tool 授权拒绝；原先进一步归因为应用权限的判断已由后续官方 MCP v1 + operator 成功对照修正，且全程未读取或记录 Provider 原始响应。
- 同一次授权下的待办验收消息创建 `job_d5164cef989e46c2ba6daaae6cbe0d01` 和 Action Intent `action_966259dff07b4a2d8e66f30c68331a89`。两者均冻结 r28/r43；Intent 当前为 `PENDING_CONFIRMATION`、`execution_attempts=0`、无错误码，钉钉确认卡已可见。该证据只证明确认门已建立，不证明待办已创建。
- 原用户随后在钉钉确认卡点击“确认执行”；Intent 于 `2026-08-31T06:35:46.722759+00:00` 获批，并在一次执行后于 `2026-08-31T06:35:47.404675+00:00` 进入 `SUCCEEDED`，无错误码，稳定 task ID 为 `task63397341727470c18ddabb100e89f979`。独立审计同时存在 `external_action.approved/APPROVED` 与 `external_action.executed/SUCCEEDED`，没有重复执行。
- 只读打开钉钉“待办”页面完成事实回查：页面真实显示标题 `Enterprise Agent 钉钉官方契约 E2E 20260831`、执行人为当前用户、截止时间为星期三 18:00、创建时间为今天 14:35。该 UI 回查未勾选完成、未修改待办，也未发送第三条消息。
- 写入后再次核对历史快照：历史 `job_df08fb56b75a4f58b203a5363a79787a` 仍为 `SUCCEEDED`、31 个 Tool，snapshot/authorization hash 仍分别为 `e577169ea6dffbb56d29473b2a83d5fa09f0fb61ec7679a413448839372db0d6` 与 `44b0aa7729bcd556fa71867df8470b73520915d615256133f7b061a36571b7cd`；四个 5.4 只读 Job 仍为 `SUCCEEDED`、32 个 Tool，四个 snapshot hash 与共同 authorization hash 均保持写入前基线值。
- 用户另行确认发送更新验收消息后，入口创建 `job_fc181bdc54914b828a863dff5a6c3257`，冻结 r28/r43；`dingtalk_update_todo` 为同一 task ID 创建 Action Intent `action_b254a7419f8d4b12b5a0ab27fdd0ae65`。首次观测为 `PENDING_CONFIRMATION`、`execution_attempts=0`、无 Provider request ID 或错误码；确认卡 CREATE Outbox 为 `SUCCEEDED`、`attempt_count=1`。该证据只证明更新确认门已建立，尚不证明待办已更新。
- 原用户确认更新卡后，Intent 于 `2026-08-31T06:53:16.444305+00:00` 获批，并在一次执行后于 `2026-08-31T06:53:17.219719+00:00` 进入 `SUCCEEDED`；Provider 返回与创建步骤相同的 task ID `task63397341727470c18ddabb100e89f979`，无错误码。独立审计存在且仅需一组 `external_action.approved/APPROVED` 与 `external_action.executed/SUCCEEDED`。
- 只读钉钉“待办”页面回查到同一对象的新标题 `Enterprise Agent 钉钉官方契约 E2E 20260831 UPDATED`，截止时间已变为星期四 18:00；执行人仍为当前用户，创建时间仍为今天 14:35。历史基线 Job 仍为 `SUCCEEDED`、31 个 Tool且两项 hash 不变；创建与更新 Job 均冻结 r28/r43、32 个 Tool和相同 authorization hash。
- 用户另行确认发送完成验收消息后，入口创建 `job_a25f5115635643c9abc0b9fe74503525`，冻结 r28/r43；`dingtalk_complete_todo` 为同一 task ID 和当前 `UPDATED` 标题创建 Action Intent `action_b9975649365e4860aef67396c3f6d463`。首次观测为 `PENDING_CONFIRMATION`、`execution_attempts=0`、无 Provider request ID 或错误码；确认卡 CREATE Outbox 为 `SUCCEEDED`、`attempt_count=1`。该证据只证明完成确认门已建立，尚不证明待办已完成。
- 原用户在证据记录期间确认完成卡；Intent 于 `2026-08-31T07:02:19.481117+00:00` 获批，并在一次执行后于 `2026-08-31T07:02:20.470197+00:00` 进入 `SUCCEEDED`。Provider 返回同一 task ID `task63397341727470c18ddabb100e89f979`，无错误码；独立审计记录 `external_action.approved/APPROVED` 与 `external_action.executed/SUCCEEDED`。
- 初次打开的待办详情仍显示“完成待办”按钮；退出并重新进入待办页面排除客户端缓存后，目标已从“待我处理”列表消失，并出现在“我已处理”列表，标题、星期四 18:00 截止时间和当前用户执行人均对应同一对象。完成 Job 也冻结 r28/r43、32 个 Tool和共同 authorization hash；历史基线 Job 的状态、Tool 数和两项 hash 再次保持不变。
- 用户确认发送创建日程验收消息后，入口创建 `job_d7a18854183a44b08bbf1dc69f282fc6`，状态 `SUCCEEDED` 且冻结 r28/r43；但该 Job 的 `agent_tool_call`、`mcp_operation_audit`、`external_action_intent` 和确认卡 Outbox 均为 0。模型仍在白色最终回复中声称“确认卡片已创建（status=confirmation_required）”，因此本次不是卡片延迟或日程 Provider 失败，而是零 Tool Call 的未验证确认声明；不得让用户确认，也不得计入 mutation 验收。
- 针对该缺口，确认型 mutation 的模型约束现要求参数齐备时实际调用已分配 Tool，且仅能依据本 Job 的成功 Tool 结果声明 `confirmation_required`；Worker 在持久化最终回复前还会把“确认卡已创建”但没有成功确认型 Tool Event 的声明替换为明确未创建说明，并记录 `agent.external_action_confirmation_claim.rejected` 有界审计。Prompt 模板推进到 `agent-system-prompt-v4`；Agent 上下文、Worker、Python Runtime 与 Runtime HTTP 相关回归为 112 passed，Ruff 与目标 mypy 均通过。
- 已重建并重启 `agent-worker`（镜像 `sha256:d861801927ac21392703792f97ab7018f9c9ddaecce076365a528a8220efb38a`）和 `python-agent-runtime`（镜像 `sha256:3dbf9db89447229aa691ec084b1951160cd8ddf907c6f5c79cc7e80bf479d599`）；前者为 `running`，后者为 `healthy`。容器内现场探针确认 Prompt 版本为 `agent-system-prompt-v4`，且无 Tool Event 的确认卡声明会被替换。r28/r43 与失败 Job 均未被改写，重试必须创建新 Job。
- 用户重新给予代表发送的当下确认后，新入口 Job `job_98c51c7cccf447fabc833e5a147ac745` 使用 `agent-system-prompt-v4` 并冻结 r28/r43。该 Job 真实产生 `dingtalk_create_calendar_event/SUCCEEDED` Tool Call，MCP 授权为 `ALLOW/principal_identity_snapshot_and_confirmation_policy_allowed`，创建 Action Intent `action_9939fcd1ce9649e2a2f7f0bb5107fd37`；首次观测为 `PENDING_CONFIRMATION`、`execution_attempts=0`、无 Provider request ID 或错误码，卡片 CREATE Outbox 为 `SUCCEEDED`、`attempt_count=1`。因此 Prompt v4 重试已证明卡片声明与 Tool/Intent/Outbox 事实一致，但用户确认前仍不证明日程已创建。
- 该日程 Intent 的确认窗口为 15 分钟：北京时间 15:42:45 创建、15:57:45 到期。用户约 16:22 操作时，服务将其转为 `EXPIRED` 并记录 `external_action.expired/EXPIRED`；`execution_attempts=0`、无 `approved_at`、无 Provider request ID 或错误码，也没有 `external_action.executed`。因此过期卡没有创建日程，下一次只能新建 Job/Intent，禁止复用或延长旧 Intent。
- 用户再次授权发送后，全新 Job `job_8ef3bd7e0ecb4980b4b58da3e8e19deb` 使用 Prompt v4 并冻结 r28/r43、32 个 Tool；真实 Tool Call `dingtalk_create_calendar_event/SUCCEEDED` 创建 Intent `action_0a89a1dffa614eca807d4e609e625e0f`。卡片 CREATE Outbox 成功，确认前 `execution_attempts=0`；没有复用前述零 Tool Call Job 或已过期 Intent。
- 原用户在有效期内确认后，Intent 于北京时间 16:44:30 获批，并在一次 Provider 执行后于 16:44:31 进入 `SUCCEEDED`，返回 event ID `aTJER3BDY3pLUEVlRHlqZ2ZFb28wQT09`，无错误码；审计按序记录 prepared、approved、executed，结果卡 Outbox 也一次更新成功。只读钉钉日历页面在 2026-09-04 显示 `10:00 Enterprise Agent Calendar E2E 20260831 RETRY`，完成 Provider 事实回查。
- 该 Job 的 snapshot/authorization hash 为 `ff0f45af77c6d03a011ce5c266aec12fd62ecff1a700148e05a6b5ab2d2aeab4` 与 `3cb762c58e58887f5dabb74f4505d7468397c6a8adfde6ed5000a863aed8e795`。历史 `job_df08fb56b75a4f58b203a5363a79787a` 仍为 `SUCCEEDED`、31 个 Tool，snapshot/authorization hash 仍为 `e577169ea6dffbb56d29473b2a83d5fa09f0fb61ec7679a413448839372db0d6` 与 `44b0aa7729bcd556fa71867df8470b73520915d615256133f7b061a36571b7cd`，未被改写。
- 用户授权发送更新日程验收消息后，入口创建 `job_a327f8fab9ab46a1b51944f7c55c5a26`；真实 `dingtalk_update_calendar_event/SUCCEEDED` Tool Call 为同一 event ID 创建 Intent `action_a47aebf7890a4f77a85ae629c19266c8`。确认前为 `PENDING_CONFIRMATION`、`execution_attempts=0`，卡片 CREATE Outbox 一次成功；没有绕过确认或复用创建 Intent。
- 原用户于北京时间 17:28:30 确认，Intent 一次 Provider 执行后于 17:28:31 进入 `SUCCEEDED`，回显同一 event ID且无错误码；prepared、approved、executed 审计与 RESULT_UPDATE Outbox 完整。钉钉日历页面显示更新后的 `11:00 Enterprise Agent Calendar E2E 20260831 RETRY UPDATED`，完成事实回查。
- 更新 Job 冻结 r28/r43、32 个 Tool，snapshot/authorization hash 为 `47f41d68c8f5aae7f188211ecf33f7fc449c458f4322981168ac340576195e64` 与 `3cb762c58e58887f5dabb74f4505d7468397c6a8adfde6ed5000a863aed8e795`；历史基线 Job 的状态、31 个 Tool及两项 hash 再次保持不变。
- 用户授权发送 AI 表格只读定位消息后，新 Job `job_ff534a9d526143a7b35d4da47ca21963` 的 `dingtalk_search_aitables` 成功精确命中“新浪热搜”并返回既有 base ID；`dingtalk_list_aitable_sheets` 的平台授权为 `ALLOW/principal_identity_snapshot_and_tool_grant_allowed`，随后由 Provider 拒绝为 `DENIED/dingtalk_permission_denied`。后续 sheet/field/record 分支安全跳过，Action Intent 和卡片 Outbox 均为 0。
- 用户随后提供官方 MCP `1.1.21` 的真实对照：同一 base 可通过 notable v1 + 当前 operator 列出 `sheetId=hERWDMS`、读取字段、插入记录并回读。结合本 Job 的平台授权 `ALLOW`，这次复验应归类为本系统 notable v2 无 operator 契约的兼容性失败，不再要求管理员重复补不明权限。修正后的新 Publication/Job 完成前，AI 表格能力不得宣称可运行。
- 新 r29/r44 只读验收通过后，用户明确允许创建并保留 AI 表格验收数据。新入口 `channel_event_e9cad91c260b485c81deb953360c5ad9` 创建 Job `job_4e7fd2944aa8441ea6c0cbe55ee80f88`，冻结 r29/r44、39 个 Tool；`dingtalk_create_aitable_sheet/SUCCEEDED` 创建 Intent `action_5f4f32e88fd642ee9b6595ed0c167558`。Intent 先为 `PENDING_CONFIRMATION`，CREATE 卡片一次投递成功；原用户约两分钟后通过卡片回调批准，随后仅执行 1 次并进入 `SUCCEEDED`，返回新数据表 `Enterprise Agent MCP 验收 20260831` 的稳定 sheet ID `shhqkza`，结果卡一次更新成功且无错误码。
- 该创建步骤的 snapshot/authorization hash 为 `56d5673cbc9b5772b25442e6bae54e2495449744ffc1829943c32d62d83fd100` 与 `5d79ca1600db0f1dba933ac22a1e8d40bef28ed1c16842e7079fe382b8814130`。写入后 r28/r43、r29/r44 的 Publication config hash，以及历史基线 Job 与修正后只读 Job 的状态、Tool 数和两项 hash 均保持不变。尚需创建独立只读 Job 回查该 sheet 后，才能把数据表创建记为完整事实闭环。

## 已验证的静态闭合

- 七个启用 profile 共 52 个官方条目：28 registered、18 excluded、6 resource，不存在未分类或重复条目。
- Provider 中仅保留 6 个显式 allowlist 的 legacy `topapi` operation：部门成员、部门详情、子部门，以及工作通知发送/进度/结果。2026-08-31 参数级复核发现最新 SDK 的 `BatchGetUser` 可按企业 userId 查询，用户详情已迁移到 `GET /v1.0/contact/users/batch/get`；其余 legacy operation 尚无被最新官方资料证实的等价新接口。
- AI 表格、日程、待办、机器人消息和搜索类已按最新官方 SDK 的新式接口及严格响应容器执行；未知 2xx 结构不得降级为空结果。
- 机器人群消息和个人批量消息的 `processQueryKey` 只记录“请求已受理”，工作通知 `task_id` 只记录“异步任务已提交”；卡片不再显示笼统“操作成功”。个人批量发送对三类拒收名单做严格类型/目标校验，按并集计算未受理人数且不回显收件人 ID。
- `dingtalk_get_user` 新接口覆盖了 `userList`、`unauthorizedUserIdList`、空结果、旧响应容器和目标 userId 漂移；本轮相关后端组合回归为 125 passed，Ruff 与 Provider/worker 目标 mypy 均通过。
- 后续全量响应复核又修复了裁剪前丢失 `truncated`、工作通知结果列表无总数、核心业务字段为空仍被接纳，以及日程/AI 表格写入回显目标漂移仍被判成功的问题；新增失败优先用例后，最新钉钉契约/Runtime/多连接器组合回归为 95 passed，Ruff 与 Provider/worker/共享契约目标 mypy 均通过。
- 进一步核对官方 notable v2 SDK 后，曾移除非搜索 Provider 的 `operator_id`，并用企业应用可见范围解释资源访问；相关三组后端组合回归当时为 98 passed。该中间设计只证明代码内部自洽，未证明与官方 MCP 的真实权限语义等价；2026-08-31 的官方 MCP v1 + operator 成功对照已将其否定，当前 change 恢复官方 v1/operator 契约。
- 全量模型描述复核继续纠正了不会直接触发 HTTP 错误、但会影响模型选参的语义缺口：用户搜索明确支持姓名/姓名拼音/英文名称；部门详情把官方完整能力与平台字段白名单分开；创建日程明确官方参与者/提醒/重复规则能力尚未进入当前治理子集；工作通知描述补齐官方 markdown、实时进度和状态统计语义。新增覆盖全部 28 个已注册 Tool 的官方语义锚点测试后，三组后端组合回归为 99 passed，Ruff 与目标 mypy 均通过。
- 2026-08-31 再次逐 Tool 比对输入 Schema 与官方参数后，补齐治理子集说明：待办创建/更新/完成、日程详情/列表/更新、AI 表格名称搜索/记录分页、群与个人机器人消息均明确当前支持和不支持的参数；“全部匹配者”进入同一批、单数歧义才等待选择。新增治理子集描述回归后，三组后端组合回归为 100 passed，Ruff 与目标 mypy 均通过。

## 尚未完成

- 待办创建/更新/完成及日程创建/更新共 5 个 mutation 已完成确认、单次 Provider 执行、钉钉事实回查与历史 Job 不变性核对；其余 5 个纳入的 mutation 仍须逐项完成相同闭环。

因此，本证据不宣称 change 已完成；OpenSpec task `5.4` 已完成，`5.5` 继续保持未完成。
