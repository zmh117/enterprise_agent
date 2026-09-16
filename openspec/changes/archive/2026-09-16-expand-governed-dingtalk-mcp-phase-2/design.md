## Context

`add-governed-dingtalk-mcp-mvp` 已在当前 checkout 实现固定 `dingtalk-mcp`、Business Principal JWT、`dingtalk_create_todo`、Action Intent、互动卡片回调和独立 external action worker，并完成真实同意/拒绝 E2E；但该 change 尚未进入 canonical baseline。当前实现仍在合同、Principal 和 worker 中写死单一 Tool 与 `dingtalk.todo.create`，只适合作为安全骨架，不能直接承载多领域工具。

官方 `dingtalk-mcp@1.1.21` 的所选七个 Profile 共暴露 52 个工具，并从 YAML 动态读取 Tool、URL、Method 和参数。本项目只把它作为 Provider 合同参考，不在运行时加载官方 YAML 或 `ACTIVE_PROFILES`。Phase 2 选择 18 个只读工具和 8 个新增 mutation，与既有创建待办共同形成 27 个固定 Tool。

所有能力继续使用当前 DingTalk enterprise App Connector。当前 Job 必须来自该 Connector，当前内部用户必须在同一企业具有唯一启用的 DingTalk 身份；本阶段不引入用户 OAuth、第二个 Stream Client 或通用 HTTP 执行器。

## Goals / Non-Goals

**Goals:**

- 交付覆盖 contacts、department、tasks、calendar、notable、robot-send-message 和 notice 的固定 Phase 2 工具集。
- 让只读 Tool 在完整 Principal、Publication、角色、Job 快照、企业和 Provider 范围复核后直接返回有界结果，不创建确认意图。
- 让新增 mutation 复用现有 Action Intent 与确认卡片，并按真实 Tool/operation 重新授权和固定分派。
- 让身份、operator、主日历、当前会话、机器人和工作通知接收人来自服务端事实，不接受模型提供的身份或任意目标。
- 保持 Provider 请求、响应、审计和错误有界，并对各 Profile 建立合同测试与真实验收。

**Non-Goals:**

- 不实现官方 Profile 的全量 52 个工具，也不支持 `ACTIVE_PROFILES=ALL`。
- 不实现删除、撤回、DING、自定义机器人 Webhook、任意个人/群/部门群发、AI 表格结构修改、日程删除或参与人修改。
- 不引入用户 OAuth、动态 Provider URL/Method/Header、Raw API、通用 YAML Tool loader 或新的 MCP Server。
- 不改变现有 `dingtalk_create_todo` 的输入、确认、同意、拒绝和终态语义。

## Decisions

### 1. 使用一个带执行元数据的固定 Tool 合同目录

`DingTalkToolContract` 增加 `effect`、`confirmation_policy`、`operation_code`、`risk_level` 和 `target_policy` 等代码字段。代码 Manifest、MCP list、Principal scope、审计和 worker 分派均从同一合同目录派生；输入 schema hash 继续只基于模型可见 input schema，执行元数据作为 Job Snapshot 独立事实冻结。

Phase 2 固定 Tool 如下：

- contacts/department：`dingtalk_search_users`、`dingtalk_get_user`、`dingtalk_list_department_users`、`dingtalk_search_departments`、`dingtalk_get_department`、`dingtalk_list_sub_departments`；
- tasks：`dingtalk_list_todos`、`dingtalk_create_todo`、`dingtalk_update_todo`、`dingtalk_complete_todo`；
- calendar：`dingtalk_get_calendar_event`、`dingtalk_list_calendar_events`、`dingtalk_list_calendar_attendees`、`dingtalk_create_calendar_event`、`dingtalk_update_calendar_event`；
- notable：`dingtalk_search_aitables`、`dingtalk_list_aitable_sheets`、`dingtalk_get_aitable_sheet`、`dingtalk_list_aitable_fields`、`dingtalk_list_aitable_records`、`dingtalk_get_aitable_record`、`dingtalk_insert_aitable_records`、`dingtalk_update_aitable_records`；
- robot/notice：`dingtalk_send_robot_message`、`dingtalk_send_work_notification`、`dingtalk_get_work_notification_progress`、`dingtalk_get_work_notification_result`。

选择固定合同目录而不是导入官方 YAML，是为了让发布快照、角色授权、effect、确认策略、代码审查和 Provider allowlist 保持一个事实源。官方 Profile 仅用于对照接口与权限，不参与启动或工具发现。

### 2. Principal Resolver 按调用 Tool 参数化

MCP registry 在调用前把精确 `DingTalkToolContract` 交给 Principal Resolver。Resolver 使用该 Tool 的 required scope 验证 JWT，复核 Job Snapshot 中同一 server/tool/schema/effect/policy，执行当前角色和 Application 授权，再解析来源 Connector、企业、当前 staff ID 与 union ID。审计上下文使用调用 Tool 的 operation/risk，不再引用模块级 `TOOL_IDENTIFIER` 常量。

所有 DingTalk Tool 都要求来源 Job 具有有效 DingTalk enterprise App Connector；调试 Job、其它 Channel Job、身份缺失或多身份命中均失败关闭。企业通讯录类 Tool 只需要当前身份的 staff ID；待办、日历和 AI 表格 Provider 调用还需要 union ID。钉钉 Stream 常见消息只携带 staff ID，因此平台先接受并持久化受信消息中直接提供的 union ID；当需要 union ID 的 Tool 发现当前身份尚未补全时，再使用同一 Connector 的应用凭据和该身份的 staff ID 调用固定联系人详情接口，校验返回 user ID 后原子补全 union ID，并继续本次 Tool 调用。补全失败仍返回稳定的身份或 Provider 权限错误，不把联系人读取失败解释为角色未授权。

备选方案是允许模型、JWT 或 Tool 参数传 `unionId`，但这会把身份选择退回 Prompt，因此不采用。空值不得覆盖既有 union ID；受信消息或联系人详情返回的非空 union ID 与既有非空值冲突时必须失败关闭并保留原值。

### 3. 只读 Tool 使用共享受治理执行壳和领域 Provider Client

只读执行壳负责参数规范化、Principal/授权、MCP 审计、超时、响应大小和安全错误分类；联系人、部门、待办、日历、AI 表格和通知状态各自使用固定领域 Client 与固定 endpoint。代码按领域组织，不为每个 Tool 复制一套认证和审计类，也不建立通用 URL 执行器。

统一上限为：MCP 请求/响应各不超过 256 KiB；列表单页不超过 50 项，AI 表格记录读单页不超过 100 行；日历查询时间窗不超过 31 天；游标和稳定 ID 各不超过 512 字符。Provider 更低上限优先。通讯录响应只保留工作所需字段，不返回手机号、邮箱、家庭地址或原始完整用户对象；审计只保存字段名、数量、目标摘要和哈希，不保存联系人、日程、表格或消息正文。

### 4. 当前主体和当前来源决定资源目标

- 待办 path 中的 union ID、日历 path 中的 union ID 与 `calendarId=primary` 均由当前 Principal 注入；模型只提供 task/event ID 和业务字段。
- AI 表格 `operatorId` 固定使用当前 Principal 的 union ID。base/sheet/record ID 可由模型从本次受权只读结果中提供；Provider 必须以当前 operator 验证目标可访问。记录 mutation 在准备确认前执行只读目标预检，并在确认后写入前再次预检。
- `dingtalk_send_robot_message` 的 conversation type、open conversation ID、staff ID 与 robot code 从 Job 冻结的来源/回复路由和 Connector 元数据解析。群聊使用当前群，私聊只发送给当前发起人；输入只包含有界 title/text。
- `dingtalk_send_work_notification` 的接收人固定为当前发起人的 staff ID，Agent ID 从 Connector 非敏感元数据 `work_notification_agent_id` 读取；不得接受 `userid_list`、`dept_id_list` 或 `to_all_user`。
- 通知进度/结果查询只允许查询同一 actor、企业和 Connector 通过该 Tool 成功产生并持久化的 task ID，不能探测任意通知任务。

该方案依赖 Provider 的当前 operator 权限作为 AI 表格资源边界，避免新增一套平行资源授权 UI；平台仍通过 Tool grant、当前身份、固定 operator、目标预检、确认和执行前复核形成完整交集。

### 5. mutation 使用通用准备器和固定 operation dispatcher

新增 mutation handler 共享参数规范化、Principal、审计、Action Intent 准备和确认响应，只由每个合同提供规范化器与安全摘要构造器。Action Intent 的 `arguments_json` 同时冻结模型参数和服务端解析的目标事实；模型不可覆盖服务端字段。

worker 先按 intent 的 `tool_identifier` 读取当前 Manifest，复核 schema/effect/policy、角色、Application、Connector、身份和目标，再从代码固定 `operation_code -> handler` 注册表分派。未知 operation、Tool/operation 不匹配或 Manifest 漂移均在 Provider I/O 前失败。每个 handler 固定 host/path/method/body 投影，禁止字符串拼接出注册表外 endpoint。

当前数据库 Action Intent 与 Card Outbox 已能保存通用 operation 和规范化 JSON，本阶段不新增平行状态机或新 mutation 表。消息/通知/表格写入在 Provider 超时后继续进入 `FAILED_UNCERTAIN`，不得自动重发；有明确 Provider 幂等键时才可由后续 change 单独放宽。

### 6. 确认卡模板按 Connector 和代码定义用途配置

确认卡模板不再由服务全局常量选择。每个 `dingtalk_enterprise_stream` Connector 在非敏感元数据中维护代码定义用途 `external_action_confirmation`，其中包含管理员填写的 `template_id` 和平台固定的 `external-action-confirmation-v1` 合同版本。管理端当前只开放“外部操作确认卡片模板 ID”这一字段；Agent、模型和 Tool 参数均不能选择模板或增加任意用途。

创建新 Action Intent 时，平台从来源 Connector 解析模板绑定，并把用途、模板 ID、合同版本和 Connector revision 冻结到 `external_action_card_outbox.payload_json`。card worker 只使用该冻结绑定创建卡片，不再读取当前 Connector 模板配置；因此修改模板只影响修改后新建的 Intent，已存在或已排队的 Intent 保持原模板。现有 Connector 和 CREATE Outbox 在迁移时补入升级前实际使用的模板 `0ad7c643-7e30-4797-8284-da5ef89d3841.schema`，运行时不得以代码 fallback 掩盖缺失绑定。

`external-action-confirmation-v1` 固定要求公开字段 `providerName`、`operationName`、`targetName`、`detailText`、`status`、`statusText`，以及私有字段 `revisionNo`、`intentToken`、`supplement`、`inputStatus`、`errorText`。worker 根据 operation 注册表生成差异化摘要和终态文案；opaque intent token 与 revision 仍只进入私有数据，卡片不可转发。模板 ID 必须是有界、无空白且以 `.schema` 结尾的钉钉模板标识。

Card Outbox 以不可变载荷记录用途、合同版本、Connector revision 和模板 ID；普通日志和审计如需引用该绑定，只能记录这些安全配置事实。消息正文、日程正文和 AI 表格值不得复制到审计。未来新增其它卡片时，必须先在代码中声明新用途和合同，再扩展管理端，不提供让模型任意选模板的通用映射编辑器。

### 7. 发布与可用性按精确 Tool 处理

部署新代码不会自动改变任何已发布 Agent/Application 或角色。管理员仍需创建新 Agent Publication、Application Publication 和角色 Tool grant；新 Job 才能冻结新 Tool。MCP `tools/list` 只返回 Principal 当前被授权的精确子集，不因为 Connector 具备某项钉钉权限而扩大工具集合。

Connector readiness 校验 App Secret 可解析、企业 ACTIVE、机器人 code 可用，并在选择工作通知 Tool 时要求合法 `work_notification_agent_id`。业务应用选择任何 `confirmation_policy=external_action_card_v1` 的 mutation 时，所有已启用钉钉来源 Connector 必须配置兼容的 `external_action_confirmation` 模板；缺失或不兼容只阻止这类 mutation 发布，不影响纯只读应用。Provider 权限不足返回稳定缺失权限错误，不把整台 MCP 服务误标为可用；上线验收必须用新的真实 Job，而不是复用旧 Job 快照。

## Risks / Trade-offs

- [官方 API schema 或权限点变化] → apply 前锁定并记录官方包/文档版本，Provider 合同测试固定 method/path/body，升级必须显式改合同和 schema hash。
- [联系人或 AI 表格响应包含敏感内容] → 字段 allowlist、分页/响应上限、审计摘要化，Tool 结果只在当前 Job 内使用。
- [AI 表格 target 在确认后失权] → 准备前和执行前都以当前 operator 读取目标，任一次失败均不写入。
- [消息或通知被重复发送] → 同一 Job/tool/normalized hash 复用 Intent，重复点击不重复 claim；Provider 不确定失败不自动重试。
- [工作通知 Agent ID 配置错误] → 发布/就绪预检要求正整数并进行授权只读探针，错误时只禁用相关 Tool，不回退任意 Agent ID。
- [一次增加 26 个新 Tool 扩大测试矩阵] → 复用共享执行壳，但按领域保留独立 Provider 合同测试；每个 Profile 至少一个真实读验收，每类 mutation 至少一条同意和拒绝链。
- [前置 MVP 尚未归档导致 delta 基线错误] → apply 前先同步并归档 predecessor，再重读 canonical、重新对账所有 ADDED/MODIFIED requirement 并执行严格校验。

## Migration Plan

1. 同步并归档 `add-governed-dingtalk-mcp-mvp`，确认 canonical 出现其新 capability 和通用确认要求；若语义不一致则停止并修订本 change。
2. 先扩展合同/Manifest/Principal/只读执行壳和 Provider clients，在未选择新 Tool 的 Publication 下部署并通过合同测试。
3. 泛化 worker operation dispatcher 和卡片摘要，保持现有创建待办回归与旧 Intent 可执行。
4. 增加 Connector 模板用途配置和数据迁移，先回填既有 Connector/Outbox，再启用运行时冻结绑定的强校验；切换组织时新建并验证新的企业与 Connector，不修改已验证企业的 Corp ID。
4. 配置钉钉应用权限和 Connector `work_notification_agent_id`，验证 readiness；不得把 Secret 或 Access Token写入元数据。
5. 创建新的 Agent/Application Publication 与角色 grant，小范围启用只读 Tool，再逐类启用 mutation。
6. 使用全新真实 DingTalk Job 验证各 Profile 读取以及 mutation 同意、拒绝和卡片终态，保存有界证据后再扩大授权。

回滚时先撤销新 Tool 的 Application/角色授权并停止产生新 Job；代码保留旧 Tool/Intent 的兼容执行。尚未确认的新 Intent 过期，已批准或执行中的 Intent按现有状态机完成或进入人工对账，不删除历史。

## Open Questions

- 无阻塞设计问题。apply 前仍需现场核对当前钉钉应用已开通的精确权限点及 `work_notification_agent_id`，该核对属于部署前置事实，不改变本 change 的工具和目标边界。
