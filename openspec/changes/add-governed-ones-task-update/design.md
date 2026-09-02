## Context

当前 ONES MCP 已具备代码固定 Tool、Job Principal、个人 ONES 外部身份、默认 Team、加密 Credential、Provider 目标约束与查询审计，但 Manifest 装配会把全部 ONES Tool 固定为只读。现有外部操作链已经提供 Action Intent、钉钉确认卡片 Outbox、签名回调、数据库 claim/lease、失败恢复和审计，不过 `external_action_intent` 的必填目标字段、`ExternalActionWorker` 的重新授权、Provider 客户端和卡片文案均绑定钉钉操作。

新的 `ones_update_task` 必须在一次 Tool 调用中只准备一个现有缺陷 Bug 的 Patch，不得立即调用写接口。只有钉钉私聊或群聊来源 Job 可以提出更新，确认卡片通过同一来源 Connector 私发给原始操作人；Web 只用于 ONES 身份绑定，不提供 mutation 确认入口。确认后仍由现有 `enterprise_agent-external-action-worker` 服务取得执行权并调用 ONES。`ones_mock/ones/更新task.md` 与 `查询条件字典.yaml` 是本次 Provider 合同和字段含义的输入证据，不作为运行时任意写入接口。

## Goals / Non-Goals

**Goals:**

- 提供一个仅更新缺陷 Bug、代码固定、受发布授权和逐次卡片确认保护的 `ones_update_task`。
- 让调用方只表达语义化 Patch，由代码将其编译为固定 `update3` 请求。
- 复用同一 Action Intent、Card Outbox、claim/lease、恢复和审计主账，同时明确区分确认渠道与执行 Provider。
- 在确认前展示实际差异，并在执行前重新验证身份、Credential、授权、权限、字段目录及 Task 版本。
- 对 Provider 明确失败、部分失败和结果不确定分别给出可恢复且不重复写入的终态。

**Non-Goals:**

- 不创建、删除或批量更新 Task，不更新工单、需求或其它非缺陷 Task。
- 不修改或流转缺陷状态；状态能力在取得专用流转接口、可达状态和权限合同后独立设计。
- 不开放任意 REST、GraphQL、路径、Header、Team、原始 `field_values`、字段 UUID 或字段 type 参数。
- 不支持卡片内修改参数、复用旧确认、自动确认或非钉钉渠道确认。
- 不把 ONES 密码、Token、认证 Header 或 Credential Secret 保存到 Intent、Outbox、审计或卡片。
- 不新增第二套 mutation 表、第二个 worker 服务或通用工作流编排平台。

## Decisions

### 1. 一个语义化 Patch Tool，而不是 Provider 透传 Tool

`ones_update_task` 使用扁平、`additionalProperties=false` 的代码固定输入 schema。`uuid` 必填，至少再提供一个变更字段；未出现字段表示不修改，所有字段拒绝 `null`。经过真实 Provider 合同测试的文本字段可用空字符串清空，经过验证的数组字段可用空数组清空；负责人、迭代、单选项等单值字段没有明确清空写法时只能替换为另一个有效值，不能清空。

第一版公开字段与 Provider 编译关系如下：

| 语义字段 | Provider 写入 | 值类型 |
|---|---|---|
| `title` | 同时写 `name`、`summary` | 非空字符串 |
| `description` | 同时写安全生成的 `desc_rich`、`descriptionText` | 字符串 |
| `assignee_uuid` | 顶层 `assign` | 用户 UUID |
| `environment` | `5BiPnrfy`, type 15 | 字符串 |
| `labels_text` | `F9eyqM3a`, type 2 | 字符串 |
| `resolver_uuid` | `field040`, type 8 | 用户 UUID |
| `owner_uuids` | `VRS2LsBn`, type 13 | 用户 UUID 数组 |
| `watcher_uuids` | `field008`, type 13 | 用户 UUID 数组 |
| `defect_type_uuid` | `field041`, type 1 | 选项 UUID |
| `urgency_uuid` | `FnkEKd4Y`, type 1 | 选项 UUID |
| `severity_uuid` | `field038`, type 1 | 选项 UUID |
| `discovery_difficulty_uuid` | `4v1yHkX9`, type 1 | 选项 UUID |
| `reproduction_probability_uuid` | `679m6U93`, type 1 | 选项 UUID |
| `sprint_uuid` | `field011`, type 7 | 迭代 UUID |
| `product_uuids` | `field029`, type 44 | 产品 UUID 数组 |
| `product_module_uuids` | `field030`, type 46 | 功能模块 UUID 数组 |
| `discovery_stage_uuid` | `79WCF8hL`, type 1 | 选项 UUID |
| `online_defect_uuid` | `field031`, type 1 | 选项 UUID |
| `historical_defect_uuid` | `6FimuZwX`, type 1 | 选项 UUID |
| `affected_version_mes_uuids` | `4ipdiS95`, type 16 | 选项 UUID 数组 |
| `fixed_version_mes_uuids` | `MysgAE3y`, type 16 | 选项 UUID 数组 |
| `verified_version_mes_uuids` | `LfbLTzsp`, type 16 | 选项 UUID 数组 |
| `solution_text` | `LMb5XC7P`, type 15 | 字符串 |
| `cause_uuid` | `PxHXwe6T`, type 1 | 选项 UUID |
| `svn_version_number` | `DmGDdhkv`, type 4 | 数字 |
| `handling_result_uuid` | `field039`, type 1 | 选项 UUID |
| `impact_analysis` | `41TN9bsG`, type 15 | 字符串 |
| `multi_version_duplicate_bug_uuid` | `2adoeHHw`, type 1 | 选项 UUID |
| `priority_uuid` | `field012`, type 1 | 选项 UUID |

调用方不能选择 `field_uuid`、type、顶层 `assign` 与 `field004` 的两套表达，也不能写状态、项目、工作项类型、创建者、时间、编号等第一版禁写或只读字段。标题和描述的成对字段由编译器生成；描述富文本只由纯文本安全转义生成，不接收任意 HTML。

选项、用户、迭代、产品和功能模块等参数使用解析后的 UUID。Agent 先通过查询字典或代码固定只读 Tool 把用户的中文描述解析成唯一 UUID，再调用 mutation；同名、歧义或无法唯一解析时必须询问用户，不得猜测。确认卡片只展示中文字段名和解析后的显示名称，不向用户展示内部 UUID。

选择该方案而不是开放 `field_values`，是为了让 Tool schema hash、授权、确认文案和回归测试都能约束真实写入面。代价是新增字段必须通过代码和 OpenSpec 变更加入。

### 2. 查询字典只提供含义与选项输入，独立生成写字段目录

新增有界、Team-scoped、版本化的 `task_update_field_catalog` 运行资源。构建/校验脚本从 `查询条件字典.yaml` 读取已列入上述白名单的字段标签与静态选项 UUID，拒绝同名多套字段、未知 type、重复 UUID 和超界内容；运行镜像不直接解析 mock 文档。

写字段目录同时固定语义字段、Provider field UUID、type、值类型、是否允许清空并固定第一版只适用于缺陷。接口文档中全部已验证的缺陷可写字段可以进入目录，但状态字段必须排除。用户、迭代、产品、功能模块等动态实体不从静态字典冻结，准备阶段按当前 Team/缺陷范围查询并验证。Action Intent 保存目录版本与 SHA-256；执行时版本或摘要漂移即停止并要求重新发起。

选择独立写目录而不是扩展查询字典为写授权，是因为“可查询”不等于“可修改”，且查询字典中的动态组织数据不应被复制为长期写权限来源。

### 3. Tool 调用只准备 Intent，并以当前 Task 快照生成精确差异

ONES MCP 在当前短时 Principal 下完成以下准备步骤：

1. 规范化 Patch，并验证至少存在一个变更字段。
2. 以代码固定查询读取 Task、项目、工作项类型、当前可写字段、权限位和 `serverUpdateStamp`，并证明目标工作项为缺陷；其它类型立即拒绝。
3. 验证缺陷属于当前已验证 Team；普通字段要求编辑权限，关注者要求关注者更新权限。
4. 用字段目录验证静态选项，用当前 Provider 数据验证动态实体与字段适用性。
5. 计算规范化后的实际差异；无变化时直接返回“无需更新”，不创建 Intent。
6. 保存请求参数、编译后的 Provider Patch、原值/新值、Task 快照前置条件、身份/Team/目录事实和安全摘要，并投放确认卡片。

确认卡片复用现有钉钉 mutation 的同一模板、确认/取消按钮、等待确认/执行中/成功/失败/过期状态和结果原卡更新机制。ONES 渲染器固定输出 `providerName=ONES`、`operationName=更新缺陷`、缺陷编号/标题目标以及每个变化字段的中文标签和“原值 → 新值”。每个 Intent 必须创建独立 `outTrackId` 和卡片实例，不能复用其它操作的卡片。

现有模板的 `detailText` 上限为 4000 字符。卡片必须完整承载全部待写值；超过预算时准备失败并要求拆分更新，不能沿用现有渲染器的截断方式，也不能以未披露内容取得确认。卡片只允许确认或取消，不在卡片内编辑参数；用户改变内容时必须取消并重新向 Agent 发起。签名 token 继续绑定 Intent ID 与 revision。

只有当前 Job 能服务端解析到来源钉钉 Connector、企业和原始操作人的钉钉主体时才可准备 Intent。群聊和私聊来源均可，但卡片一律私发原始操作人；Web、无 Connector 或后台 Job 在准备阶段拒绝。

Intent 幂等指纹由 Job、Tool、规范化参数摘要、ONES 外部身份、Team、Task UUID、`serverUpdateStamp` 和字段目录摘要共同计算。同一快照上的完全相同请求复用同一 Intent；Task 或目录变化后相同业务 Patch 必须生成新 Intent 和新确认。

### 4. 同一张表区分确认渠道与执行 Provider

保留 `external_action_intent`、`external_action_card_outbox` 及现有状态机。以向后兼容 migration 增加：

- `confirmation_channel_code`，现阶段固定为 `dingtalk`；
- `execution_provider_code`，ONES Intent 固定为 `ones`；
- `execution_external_identity_id`，引用准备时解析的 ONES 外部身份；
- `execution_scope_id`，保存无 Secret 的 Team UUID；
- `target_resource_type` 与 `target_resource_id`，本变更固定为 `task` 与 Task UUID；
- `precondition_json`/摘要，保存 Task 更新戳及必要当前值；
- `field_catalog_version`/摘要；
- `intent_fingerprint`，用于资源快照感知的唯一幂等键。
- `confirmation_summary_json`，保存通过 4000 字符卡片预算校验后的完整中文差异；旧 `safe_summary_json` 保持兼容上限，避免多字段 JSON 元数据挤占实际 `detailText` 预算。

现有 `source_connector_id`、`dingtalk_enterprise_id`、`target_external_subject_id` 与 `target_union_id` 在本变更中继续表示确认卡片路由和确认人事实，绝不承载 ONES 身份。既有钉钉 Intent 保持原执行路径；新增列允许为空或以兼容默认值回填，不改写既有终态记录。

选择扩展现有表而不是新建 ONES Intent 表，是为了保持单一确认状态机、claim 上限和审计链；选择显式列而不是把全部事实塞入 `arguments_json`，是为了可约束查询、重新授权和迁移验证。

### 5. 保留服务名，抽出 Provider 中立 worker 与两个执行适配器

Compose 服务名继续使用 `enterprise_agent-external-action-worker`。通用轮询、Card Outbox、claim/lease、终态提交和审计移到 Provider 中立 worker 模块；钉钉和 ONES 各自实现合同解析、重新授权、Provider 调用、结果归一化与卡片结果文案。操作分发键为代码 Manifest 冻结的 `execution_provider_code + operation_code`，未知组合在网络访问前拒绝。

ONES 执行适配器不复用准备阶段的短时 Principal，也不从 Intent 读取 Secret。它以 `actor_user_id` 和 `execution_external_identity_id` 重新解析当前启用身份及当前加密 Credential，复核 Team、Job Tool Snapshot、Application/角色授权、字段目录、Task 可见性和字段级权限，再构造固定路径的 `update3` 请求。Credential 刷新沿用现有受控刷新服务，刷新后的 Secret 只存在于调用内存。

选择单 worker 加 Provider 适配器而不是新增队列和服务，是因为现有全局并发、恢复和卡片结果链已经满足需求；把 ONES 调用直接写进钉钉 worker 文件则会继续混淆确认渠道与执行 Provider。

### 6. 执行前以更新戳阻断陈旧确认，结果不确定时禁止盲重放

worker 在写请求前重新读取缺陷。外部身份解绑/换绑、Team 移除、Credential 失效、授权撤销、权限不足、字段目录漂移、缺陷不存在或 `serverUpdateStamp` 与确认快照不一致，均在 Provider 写调用前终止，并把卡片更新为可理解的失败/冲突状态。任何更新戳变化都使整张确认失效，即使外部修改发生在本次 Patch 未涉及的字段；第一版不自动合并或继续执行。

Provider 返回 HTTP 成功且 `bad_tasks` 为空才是已接受成功；`bad_tasks` 非空是明确失败。成功后再读取 Task 验证所有目标字段已经达到确认值。超时、连接中断或 worker 中断属于结果不确定：先只读核对目标字段，全部匹配时记录为“核对后成功”，否则进入 `FAILED_UNCERTAIN`，禁止自动重放并提示人工核对。

`update3` 文档没有给出原子条件更新参数，因此执行前读取与更新之间仍存在极小竞态。全局更新戳采用偏保守冲突策略以避免覆盖；最终只读核对和不确定态阻止系统把未知结果当作失败重试，但不能替代 Provider 原生 CAS。

### 7. 发布与可见性沿用 mutation 治理

ONES Tool 合同扩展 effect、确认策略、operation code、风险与目标策略元数据；Manifest 不再把所有 ONES Tool 强制标记为只读。`ones_update_task` 只有在角色授权、Agent/Application Publication 选择并冻结到新 Job 后才可见。增加 Manifest 不自动修改现有角色、应用 Publication 或运行中 Job。

管理界面以“更新 ONES 缺陷 `ones_update_task` / 完整说明 / 写入”展示，并明确“仅钉钉来源可用且每次调用均需卡片确认”。只读 ONES Tool 的行为不变。

## Risks / Trade-offs

- [Provider 没有原子版本条件，预读后仍可能发生竞态] → 使用 `serverUpdateStamp` 预检、保守冲突、写后核对和禁止未知结果自动重放；后续若 Provider 提供 CAS，再单独提案。
- [静态选项 UUID 可能随 Team 配置变化] → 目录带 Team、版本和摘要，准备及执行均校验；目录漂移要求新 Intent，不静默映射同名选项。
- [确认卡片可能容纳不下长描述或多字段差异] → 对 Tool 和卡片设统一可验证预算，超限要求拆分，不使用未披露截断内容取得确认。
- [抽取 worker 可能影响现有钉钉 mutation] → 保留 Compose 服务名和数据库状态机，先迁移现有钉钉执行器并跑全量合同/恢复回归，再注册 ONES 分发。
- [新增列与既有唯一键可能造成幂等语义冲突] → 使用 additive migration 和新 `intent_fingerprint` 唯一索引；既有钉钉 Intent 继续走旧键，新的 ONES Intent 强制使用快照感知指纹。
- [字段在不同缺陷布局中不存在] → 准备阶段读取当前布局/权限并拒绝不适用字段，不把字典存在视为当前缺陷可写证明。

## Migration Plan

1. 先部署 additive migration 与兼容旧钉钉 Intent 的 Repository 读写逻辑；验证现有记录、索引和 Card Outbox 无变化。
2. 将 worker 编排抽到 Provider 中立模块，注册原钉钉适配器并运行现有钉钉 mutation、租约恢复和卡片回归；此时不发布 ONES mutation。
3. 加入 ONES Tool 合同、写字段目录、准备服务和 ONES 执行适配器，完成单元、集成、migration、容器 import smoke 与 Compose 校验。
4. 通过新的 Agent/Application Publication 显式选择 `ones_update_task`，仅向授权角色启用；分别使用新的钉钉私聊和群聊来源 Job 完成真实“准备 → 私聊卡片 → 确认 → 更新 → 回读”验收，并验证 Web Job 被拒绝。
5. 回滚时先停止创建新的 ONES Intent，等待或人工终结 `PENDING_CONFIRMATION`、`APPROVED`、`EXECUTING` ONES Intent，再回滚应用/worker 镜像；保留 additive 列和审计记录，不执行破坏性降级 migration。

## Open Questions

- 当前没有阻塞本提案的产品问题。创建 Task、非缺陷 Task、状态流转、Provider 原生 CAS、非钉钉确认渠道及字段白名单扩展均留给后续独立变更。
