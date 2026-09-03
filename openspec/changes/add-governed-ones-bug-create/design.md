## Context

当前 checkout 已具备代码固定 ONES Tool、业务 Principal、个人 ONES 身份/Team/Credential、Action Intent、Card Outbox、钉钉卡片回调以及 `enterprise_agent-external-action-worker`。活动变更 `add-governed-ones-task-update` 正在把外部操作表和 worker 泛化为可执行 ONES mutation，但其规格明确把创建 Task 列为 Non-Goal；本设计只复用其通用基础，不改写更新 Tool 的语义。

新增接口证据来自 `ones_mock/ones/新增bug-task.md`：创建使用固定 `POST /project/api/project/team/{team_uuid}/tasks/add3`，Task UUID 由客户端预生成，标题与负责人需要同时写入顶层及字段区，多选字段必须使用数组。文档中“409 后更换 UUID 重试”、负责人默认当前用户、任意 HTML 描述等建议均已被本次产品决策覆盖，不作为实现合同。

当前没有可连接的真实 ONES 服务，且现有资料没有证明真实 Provider 的创建权限、创建布局和按 UUID 完整回查合同。因此本次可以完成代码与 Mock 链路，但生产能力必须保持不可启用，真实证据作为明确未完成项。

## Goals / Non-Goals

**Goals:**

- 提供一个只创建单个缺陷、输入与输出有界、默认不授权的 `ones_create_bug`。
- 允许 Agent 基于受限当前上下文提出建议值，同时让用户在同一张中文卡片中看见并逐次确认全部最终字段。
- 复用现有 Action Intent、Card Outbox、钉钉模板、回调、外部操作 worker、claim/lease 和审计主账。
- 用固定 Task UUID、写前二次校验和写后只读核验防止超时、崩溃或重复消息造成重复缺陷。
- 让明确修订产生新 Intent，并以可审计的 `SUPERSEDED` 终态禁用旧待确认卡。

**Non-Goals:**

- 不创建需求、任务或工单，不批量创建，不关联其它 Task，不设置父任务、工时或迭代。
- 不开放任意 REST/GraphQL、任意字段、原始 `field_values`、HTML、Provider URL/Header、Team 或认证参数。
- 不上传图片、截图、文件或附件，不把临时下载地址写入描述。
- 不支持卡片内表单编辑，不自动取消已批准/执行中的创建，不在创建后自动调用更新 Tool。
- 第一版不增加按 ONES 实例或 Team 划分的字段 Profile，也不动态刷新已确认稳定的静态枚举 UUID。
- 不新增第二套 mutation 表、队列、worker 服务或通用工作流引擎。
- 不以 Mock 结果代替真实 ONES 生产验收。

## Decisions

### 1. Tool公开完整业务参数，并以独立元数据标记建议来源

`ones_create_bug` 使用扁平、`additionalProperties=false` 的固定 schema。以下业务字段全部必填：

| Tool 字段 | 类型 | 语义 |
|---|---|---|
| `title` | 非空字符串 | 缺陷标题 |
| `project_uuid` | UUID 字符串 | 所属项目 |
| `description` | 非空纯文本 | 缺陷描述 |
| `environment` | 非空字符串 | 环境 |
| `assignee_uuid` | UUID 字符串 | 负责人 |
| `defect_type_uuid` | UUID 字符串 | 缺陷类型 |
| `urgency_uuid` | UUID 字符串 | 紧急程度 |
| `severity_uuid` | UUID 字符串 | 严重程度 |
| `discovery_difficulty_uuid` | UUID 字符串 | 发现难易程度 |
| `reproduction_probability_uuid` | UUID 字符串 | 重现概率 |
| `product_uuids` | 非空 UUID 数组 | 所属产品，可多选 |
| `product_module_uuids` | 非空 UUID 数组 | 所属功能模块，可多选 |
| `discovery_stage_uuid` | UUID 字符串 | 缺陷发现阶段 |
| `online_defect_uuid` | UUID 字符串 | 是否线上缺陷 |
| `historical_defect_uuid` | UUID 字符串 | 是否历史缺陷 |
| `affected_version_uuids` | 非空 UUID 数组 | 影响版本，可多选 |

`watcher_uuids` 是唯一额外可选业务字段，用于追加关注者；服务端始终把当前 ONES 用户加入最终集合。工作项类型不进入 schema，由服务端固定为缺陷。标题、环境沿用现有有界文本规则；描述可以按现有更新合同接受较大纯文本，但正式确认摘要总长仍受 4000 字符硬上限约束，因此不能通过更大的输入上限绕过展示完整性。

Tool 另接受有界 `field_provenance` 元数据数组，仅为 Agent 实际推断的字段记录 `{field, source}`；`field` 只能来自上述业务字段，`source` 只能是 `current_message`、`conversation_context`、`field_catalog` 或 `ones_read`，同一字段只能出现一次。没有列入该数组的字段视为用户明确提供；服务端固定的工作项类型和当前用户关注者分别显示为“系统固定”和“系统默认”。该元数据不进入 ONES 请求。服务端按当前 Job 关联允许范围内的消息、目录版本或只读 Tool Call 证据引用，但 Intent 不复制原始会话内容。

采用显式来源元数据，而不是让卡片渲染器猜测，是因为渲染器看不到模型形成候选值的语义过程。代价是 schema 较长，但来源枚举和字段集合均可静态校验，且用户仍通过最终卡片决定是否接受。

若任何必填字段尚未完成、描述含“待补充”、名称解析不唯一或 Agent 只能编造事实，Agent 不调用 `ones_create_bug`，只在普通钉钉会话中输出草稿并继续询问。这样不需要为不完整草稿新增数据库状态。

### 2. 创建字段目录固定Provider映射，动态引用仍实时验证

新增独立 `bug_create_field_catalog`，使用固定 schema version、目录 version 和 SHA-256。目录可由受控脚本从 `查询条件字典.yaml` 与新增接口文档提取白名单内容，运行镜像只包含生成后的有界 JSON，不解析完整 mock 文档。根据用户确认，第一版不增加实例/Team Profile，也不动态刷新静态枚举 UUID；字段目录及静态选项变更必须经过代码审查和新的目录摘要。

Provider 编译关系固定如下：

| 业务值 | Provider 写入 |
|---|---|
| 预生成 Task UUID | 顶层 `uuid` |
| 标题 | 顶层 `summary` 与 `field001`, type 2，同值 |
| 项目 | 顶层 `project_uuid` |
| 固定缺陷类型 | 顶层 `issue_type_uuid=B4TV9bu5`，预检时验证仍解析为“缺陷”且适用于项目 |
| 负责人 | 顶层 `assign` 与 `field004`, type 8，同值 |
| 关注者 | 顶层 `watchers`，当前用户与显式追加值稳定去重 |
| 环境 | `5BiPnrfy`, type 15 |
| 缺陷类型 | `field041`, type 1 |
| 紧急程度 | `FnkEKd4Y`, type 1 |
| 严重程度 | `field038`, type 1 |
| 发现难易程度 | `4v1yHkX9`, type 1 |
| 重现概率 | `679m6U93`, type 1 |
| 所属产品 | `field029`, type 44，数组 |
| 所属功能模块 | `field030`, type 46，数组 |
| 缺陷发现阶段 | `79WCF8hL`, type 1 |
| 是否线上缺陷 | `field031`, type 1 |
| 是否历史缺陷 | `6FimuZwX`, type 1 |
| 影响版本 | `4ipdiS95`, type 16，数组 |
| 描述 | `field016`, type 20，由纯文本安全转义生成富文本 |

顶层 `parent_uuid` 固定为空字符串，`add_manhours` 固定为空数组；它们属于 Provider 固定实现细节，不出现在 Tool、卡片或业务审计快照中。第一版不写 `field011` 迭代，也不接受接口文档列出的其它可选字段。影响版本不得与修复版本或验证版本选项混用。

静态分类 UUID 只需通过目录成员校验。项目、负责人、额外关注者、产品、模块和影响版本的名称到 UUID 解析先查版本化文档目录：规范化名称必须精确且唯一命中；目录不存在唯一值时，才使用当前 ONES 身份可调用的固定只读 Operation 补充解析，接口仍歧义时要求用户确认。无论 UUID 来自目录还是接口，正式确认前都要验证存在性、Team/项目范围及关系，模块必须属于至少一个已选产品。项目布局与创建权限仍须真实 Provider 预检，静态目录不是权限证明。

选择独立创建目录而不是复用 `task_update_field_catalog`，是因为创建必填性、顶层字段、固定缺陷类型和字段适用性与 Patch 更新不同。两者可以复用生成器和标签规范化代码，但不能共用授权语义。

### 3. 准备流程只在完整预检后生成Task UUID和正式Intent

只有来源为可验证钉钉私聊或群聊的 RUNNING Job 可以准备创建，确认卡一律通过同一来源 Connector 私发原始发起人。Web、后台、无 Connector、无唯一钉钉主体或无兼容卡片模板的 Job 在 Intent 前拒绝。

ONES MCP 的准备顺序固定为：

1. 校验 Tool schema、完整业务参数、`field_provenance` 和 4000 字符可展示预算。
2. 从 Job Principal 解析当前内部用户、唯一启用的 ONES 身份、默认 Team 和当前 Credential；身份与 Team 不接受 Tool 覆盖。
3. 按“版本化文档目录优先、目录无唯一值时才查只读接口”解析名称到 UUID，再验证项目、固定缺陷工作项类型、创建权限、项目创建布局、负责人/关注者、产品/模块/版本及字段目录。
4. 解析全部中文显示值，形成与 Provider 写入值一一对应的完整确认摘要；任何歧义、缺失或超限均停止。
5. 生成一次符合 Provider 合同的随机 Task UUID，并把它作为待创建资源 ID 冻结；UUID 不显示给用户。
6. 在一个数据库事务中保存 Intent 与 CREATE Card Outbox，Tool 返回“等待确认”，不执行写接口。

真实 Provider 的创建权限、布局及按 UUID 回查接口尚无可靠证据，因此实现以显式 adapter capability 失败关闭；受控 Mock 可实现同一接口用于合同与链路测试。生产配置不能仅因项目可见或用户属于项目而把 capability 标为 ready。

### 4. 以提案链和SUPERSEDED扩展现有Action Intent

继续使用 `external_action_intent` 已有的确认渠道、执行 Provider、外部身份、Team scope、目标资源、precondition、目录摘要、确认摘要和指纹字段。ONES 创建 Intent 固定：

- `confirmation_channel_code=dingtalk`
- `execution_provider_code=ones`
- `operation_code=ones.task.create`
- `target_resource_type=task`
- `target_resource_id=<预生成 Task UUID>`
- `precondition_json` 保存无 Secret 的权限/布局/动态引用验证摘要及绑定 revision
- `arguments_json` 保存规范化业务字段、最终关注者和来源元数据，不保存认证材料或原始 HTTP payload
- `confirmation_summary_json` 保存已通过 4000 字符校验的完整中文展示模型

为创建提案修订增加 `proposal_chain_id`、可空 `supersedes_intent_id`、可空 `superseded_by_intent_id` 和 `superseded_at`，并在 domain 状态中增加终态 `SUPERSEDED`。普通新建调用使用新 chain；只有 Tool 显式提交 `supersedes_intent_id`，且服务端证明旧 Intent 属于同一 actor、Session、Application、Tool、ONES 身份和 Team 并仍为 `PENDING_CONFIRMATION` 时才允许修订。

创建新 Intent、把旧 Intent CAS 更新为 `SUPERSEDED`、写入互相引用及创建新卡/更新旧卡 Outbox 必须在同一事务完成。若旧卡已 `APPROVED`、`EXECUTING` 或进入其它终态，整个替代事务失败，不创建新卡，并提示等待结果后使用 `ones_update_task`。相同会话或相似标题不产生替代关系。

每个 MCP Tool Call 以稳定 `mcp_call_id` 作为准备幂等边界：同一 Tool Call 的 transport/worker 重入复用原 Intent 与 Task UUID；新的 Tool Call 即使参数相同也视为新的缺陷提案，除非显式修订。这避免按相同标题或参数错误合并用户确实要创建的两条缺陷。

### 5. 卡片保持现有模板合同，但为创建提供完整中文渲染

不增加新的卡片模板 ID 或必填变量。渲染器继续输出：

- `providerName=ONES`
- `operationName=创建缺陷`
- `targetName=<标题>`
- `detailText=<固定顺序的全部中文字段>`

字段顺序按项目、工作项类型、标题、描述、环境、负责人、关注者、缺陷类型、紧急程度、严重程度、发现难易程度、重现概率、产品、功能模块、发现阶段、线上缺陷、历史缺陷、影响版本排列。Agent 推断项在中文标签后显示“（建议值）”；系统固定缺陷类型和系统默认关注者使用对应标记。所有外部字符串先做长度、控制字符和卡片文本转义；内部 UUID、field/type、HTML、认证事实不进入 `detailText`。

4000 字符按最终提交给模板的 `detailText` 计算，禁止截断。卡片沿用确认、拒绝和现有状态更新；若模板包含“补充/重新生成”动作，回调只返回“请在当前会话回复要修改的字段”，原 Intent 继续待确认，直到新完整版本原子替代或原卡过期。

`SUPERSEDED` 卡片显示“已被新版本替代，请使用最新确认卡”。确认有效期固定 900 秒，过期转为 `EXPIRED`，对应 Task UUID 永久废弃。确认回调继续验证签名 token、Intent revision、Connector、企业、钉钉主体和内部 actor；群内其它成员不能批准。

### 6. Worker执行前重验，并以Provider attempt阻止任何未知重放

保留 `enterprise_agent-external-action-worker` 服务名、队列和全局 claim/lease。Provider 中立编排按 `execution_provider_code + operation_code` 分发到新 ONES create adapter。适配器先重新验证内部用户、原钉钉主体、Job Tool Snapshot、Application/角色授权、原 ONES 身份、原 Team、当前 Credential、目录摘要、创建权限、项目布局和所有动态引用；任何变化都在写调用前把 Intent 安全终结并更新原卡。

调用 Provider 前先持久化唯一 Provider attempt 的 `STARTED` 事实、Task UUID、请求摘要和目录摘要，再发送固定 `add3` 请求。正常成功响应仅表示 Provider 声称接受，仍需用同一 UUID 回查并按语义字段核验全部确认值。明确 4xx/权限/合同错误且 Provider 能证明未创建时进入 `FAILED`；409、超时、连接中断、无合法响应或 attempt 开始后的 worker 中断一律先回查。

恢复器发现 attempt 已开始时不得再次发送 `add3`。回查任务存在且项目、缺陷类型、标题、描述、负责人、关注者及全部字段都与确认快照一致时进入 `SUCCEEDED` 并标记“核验后成功”；任务不存在、字段不一致或查询失败时进入 `FAILED_UNCERTAIN`。任何情形都不自动更换 Task UUID，也不自动重放创建。若用户仍要创建，必须主动发起新的独立 Intent 和 UUID。

这比接口文档建议的“409 后换 UUID 重试”更保守，因为 409 或传输中断可能意味着原请求已经创建成功；自动换 UUID 会把不确定结果扩大成确定的重复缺陷。

### 7. 成功输出与审计采用白名单，不持久化Provider原文

成功后原确认卡更新为“创建成功”，显示缺陷编号、标题、项目和负责人。查看链接只能由受信 ONES 基础地址和已验证编号/路由规则生成；不直接采用 Provider 返回 URL，也不显示内部 Task UUID。失败卡只显示稳定中文原因、是否需要重新提案及安全关联号，不显示 Provider 原始正文。

Action Intent 保存用户实际确认的完整业务快照，包括完整描述、中文显示值、建议字段及安全来源类别；审计链关联 Intent、MCP Call、Agent Tool Call、Job、Session、actor、Connector、Tool/schema、绑定 revision、权限预检、卡片点击、Provider attempt 和结果。原始钉钉上下文、模型私有推理、密码、Token、JWT、Cookie、认证 Header、Credential 密文及无界 ONES 请求/响应不得进入 Intent、Outbox、日志或通用审计。

Provider 结果白名单只允许 Task UUID、缺陷编号、规范化状态和安全错误码；业务字段证据来自冻结确认快照与有界回查归一化结果，而不是保存原始 HTTP body。

### 8. 发布默认关闭，Mock验收与真实验收分层

Manifest 注册 `ones_create_bug` 只让控制面识别 Tool，不自动创建角色 grant、修改 Agent/Application Publication 或扩大既有 Job Snapshot。管理界面显示“创建 ONES 缺陷 `ones_create_bug` / 完整说明 / 写入”，并注明“仅钉钉来源、每次卡片确认”。管理员必须显式创建新角色授权和新 Agent/Application Publication；仅之后创建的 Job 能冻结该 Tool。

本地测试使用独立 ONES Mock 覆盖权限/布局预检、创建、按 UUID 回查、409、超时、连接中断和不一致结果。生产 readiness 必须在取得真实只读预检和回查合同、真实钉钉卡片点击及完整无 Secret 审计证据后才能打开。没有这些证据时，即可交付代码，但验收报告必须明确为“Mock/合同通过，真实 Provider 未验收”。

## Risks / Trade-offs

- [静态字段或选项 UUID 与未来真实配置不一致] → 通过代码审查目录、目录摘要、创建权限/布局预检和默认关闭降低风险；第一版按用户决策不增加 Profile 或动态枚举刷新。
- [真实 Provider 缺少可靠创建权限或布局查询] → adapter capability 失败关闭，允许 Mock 验证但禁止生产启用，不以项目可见或成员身份推断权限。
- [确认内容超过钉钉模板容量] → 在 Intent 前按最终 `detailText` 严格计算，超限要求缩短描述，不截断确认。
- [相同内容可能代表修订，也可能代表第二条缺陷] → 只接受显式 `supersedes_intent_id` 和同 actor/session 强校验；缺少明确修订证据时创建新提案链。
- [创建请求超时后无法证明结果] → 固定 Task UUID、attempt-before-call、只读回查和 `FAILED_UNCERTAIN`；绝不自动更换 UUID 或重放。
- [新增 `SUPERSEDED` 影响现有状态机] → 仅允许 `PENDING_CONFIRMATION -> SUPERSEDED`，现有钉钉/ONES 更新状态迁移不变，并增加 repository、callback、card 与 worker 回归。
- [完整描述进入受控 Intent 增加业务数据暴露面] → 沿用现有授权读取和保留边界，只保存用户实际确认的业务快照，不复制原始会话或 Provider 原文。

## Migration Plan

1. 增加兼容 migration、`SUPERSEDED` 状态和提案链字段；先验证既有钉钉与 ONES 更新 Intent、索引、Card Outbox 和 worker 状态迁移不变。
2. 增加 create Tool schema、字段目录/生成校验器、参数规范化和 Provider 编译器；此阶段不发布 Tool。
3. 增加 Mock 的权限/布局、`add3` 和按 UUID 回查合同，完成准备、卡片、替代、回调、执行、恢复和审计测试。
4. 注册 ONES create adapter 和管理端 Tool 展示，构建 ONES MCP、backend、dingtalk-runtime 与 external-action-worker 镜像，执行容器 import smoke 和 Compose 校验。
5. 只在测试环境创建新的角色 grant、Agent/Application Publication 和新 Job，完成 Mock 全链；生产保持未发布/未授权。
6. 未来取得真实 ONES 环境后，先验证权限/布局与回查合同，再完成钉钉私聊/群聊真实卡片、成功、拒绝、过期、修订、409/超时和审计证据；通过前不得标记生产 ready。
7. 回滚时停止新建创建 Intent，等待或人工终结 `PENDING_CONFIRMATION`、`APPROVED`、`EXECUTING` Intent；回滚应用与 worker 版本但保留 additive 列、终态和审计记录，不执行破坏性降级。

## Open Questions

- 真实 ONES 的创建权限、项目创建布局以及按 Task UUID 完整回查的精确接口合同仍待取得；这是生产启用与真实端到端验收的外部阻塞，不阻塞本地 Mock 实现。
- 当前没有未决产品问题。实例/Team Profile、静态枚举动态刷新、附件、Task 关联、父任务、迭代、工时、其它可选字段和非钉钉确认渠道均留给后续独立变更。
