## ADDED Requirements

### Requirement: ONES缺陷更新必须是代码固定的单资源 mutation Tool
系统 SHALL 只通过代码 Manifest 固定的 `ones_update_task` 提出 ONES 缺陷 Bug 更新。一次调用 MUST 只包含一个现有缺陷的 Task UUID 和该缺陷的一组语义化 Patch，且不得允许调用方控制 Provider URL、HTTP method、Header、Team、GraphQL、REST path、字段 UUID、字段 type 或原始 `field_values`。

#### Scenario: 提出单个Task更新
- **WHEN** 已授权钉钉来源 Job 调用 `ones_update_task` 并提供一个合法缺陷 UUID 与至少一个可写语义字段
- **THEN** ONES MCP 只准备该缺陷的一个待确认 Action Intent
- **AND** 在用户确认前不得调用 ONES 写接口

#### Scenario: 尝试透传Provider参数
- **WHEN** 调用参数包含 URL、Header、Team、原始字段 UUID、type、`field_values` 或其它未声明字段
- **THEN** Tool 在任何 Provider 网络访问前返回字段级合同错误

#### Scenario: 尝试创建批量更新或修改非缺陷Task
- **WHEN** 调用方缺少现有缺陷 UUID、提供多个 Task、请求创建 Task 或目标工作项不是缺陷
- **THEN** Tool 拒绝该请求且不创建 Action Intent

### Requirement: ONES缺陷更新必须执行严格Patch语义
`uuid` MUST 为必填字段，所有业务变更字段 MUST 为可选字段，并且请求 MUST 至少显式提供一个业务变更字段。未出现的字段 SHALL 表示“不修改”；`null` MUST NOT 表示未提供或清空。经过 Provider 合同验证并由版本化写字段目录明确允许的文本字段空字符串和数组字段空数组 SHALL 表示清空；没有明确清空写法的负责人、迭代、单选项等单值字段 MUST NOT 被清空。

#### Scenario: 只更新标题
- **WHEN** 调用只提供 `uuid` 与 `title`
- **THEN** 编译后的 Provider 请求同时写入同值 `name` 与 `summary`
- **AND** 不得发送任何其它未提供业务字段

#### Scenario: 只更新描述
- **WHEN** 调用只提供 `uuid` 与 `description`
- **THEN** 编译器以纯文本生成 `descriptionText` 和安全转义的 `desc_rich`
- **AND** 不接受调用方提供的任意 HTML

#### Scenario: 未提供业务变更
- **WHEN** 调用只提供 `uuid`
- **THEN** Tool 返回稳定合同错误且不读取或写入 Provider

#### Scenario: 使用null清空字段
- **WHEN** 任一业务变更字段显式为 `null`
- **THEN** Tool 返回字段级合同错误且不创建 Action Intent

#### Scenario: 使用允许的空值清空字段
- **WHEN** 调用为目录明确允许清空的字符串或数组字段提供空字符串或空数组
- **THEN** 确认差异明确显示“清空”
- **AND** 编译器只使用目录固定的清空表达

#### Scenario: 尝试清空未验证的单值字段
- **WHEN** 调用请求清空负责人、迭代、单选项或其它没有明确清空合同的单值字段
- **THEN** Tool 返回字段级不支持错误且不创建 Action Intent

### Requirement: ONES缺陷更新必须使用固定写字段目录
系统 MUST 使用代码审查且版本化的 Team-scoped 写字段目录，将公开语义字段映射为固定 Provider field UUID、type、值类型和清空策略。第一版目录 SHALL 包含接口文档中全部已验证的缺陷可写字段但 MUST 排除状态；该目录 MAY 从 `查询条件字典.yaml` 提取白名单字段的中文含义与静态选项 UUID，但查询可见性 MUST NOT 自动产生写权限。任意未列入写目录、第一版禁写、只读或不适用于当前缺陷的字段 MUST 被拒绝。

#### Scenario: 使用静态选项字段
- **WHEN** Patch 为写目录中的单选或多选语义字段提供选项 UUID
- **THEN** 系统验证 UUID 属于当前 Team、目录版本和对应字段
- **AND** 只生成目录固定 field UUID 与 type 的 `field_values` 项

#### Scenario: 使用动态实体字段
- **WHEN** Patch 提供用户、迭代、产品或功能模块 UUID
- **THEN** 系统以当前身份在当前 Team 和缺陷范围内验证该实体及其字段适用性
- **AND** 不以静态查询字典中的历史动态实体作为可写证明

#### Scenario: 解析中文选项或动态实体名称
- **WHEN** 用户以中文名称表达选项、用户、迭代、产品或功能模块
- **THEN** Agent 必须先通过查询字典或代码固定只读 Tool 解析唯一 UUID，再调用 mutation
- **AND** 同名、歧义或无法唯一解析时必须询问用户且不得猜测

#### Scenario: 同名字段存在多套UUID
- **WHEN** 查询字典存在同名多套字段或选项集合
- **THEN** 写目录只接受代码明确选定的一套映射
- **AND** 不按显示名称猜测或回退到其它 UUID

#### Scenario: 请求只读字段
- **WHEN** Patch 请求修改状态、项目、工作项类型、创建者、创建/更新时间、编号或其它目录标记为第一版禁写/只读的字段
- **THEN** 系统在 Provider 写调用前拒绝

#### Scenario: 执行时目录发生漂移
- **WHEN** Action Intent 保存的字段目录版本或摘要与 worker 当前加载的目录不一致
- **THEN** worker 不调用 ONES 写接口
- **AND** 卡片提示用户按新目录重新发起并确认

### Requirement: ONES缺陷更新必须在确认前生成当前差异
ONES MCP MUST 在创建 Action Intent 前读取当前 Task、项目、工作项类型、可写字段、权限位与 `serverUpdateStamp`，证明目标为缺陷，并将规范化 Patch 与当前值比较。确认卡片 MUST 复用现有钉钉 mutation 卡片模板、确认/取消按钮和状态交互，向原用户完整展示缺陷标识以及每个实际变化字段的中文名称、原值和新值；卡片不得展示内部 UUID，未变化字段不得进入 Intent 或卡片。

#### Scenario: Patch包含实际变化
- **WHEN** 规范化后的一个或多个字段与当前 Task 不同且用户具有对应权限
- **THEN** 系统保存差异、Task 更新戳、字段目录摘要与参数摘要
- **AND** 通过来源钉钉 Connector 向原用户私聊投放逐次确认卡片

#### Scenario: 钉钉私聊或群聊来源发起更新
- **WHEN** 当前 Job 来自可验证的钉钉私聊或群聊 Connector
- **THEN** 系统始终把独立确认卡片私发给该 Job 的原始操作人
- **AND** 每个 Intent 使用独立 `outTrackId`，不得复用其它操作的卡片实例

#### Scenario: Web或后台Job发起更新
- **WHEN** 当前 Job 来自 Web、后台任务、无来源 Connector 或无法唯一解析原始钉钉操作人
- **THEN** Tool 在创建 Intent 和 Provider 写调用前拒绝
- **AND** Web 只保留 ONES 身份绑定能力

#### Scenario: 渲染ONES确认卡片
- **WHEN** 缺陷差异符合现有模板的有界字段合同
- **THEN** 卡片使用 `providerName=ONES`、`operationName=更新缺陷`、缺陷编号/标题以及中文差异内容
- **AND** 继续使用现有等待确认、执行中、成功、失败和过期状态

#### Scenario: Patch没有实际变化
- **WHEN** 所有规范化目标值都等于当前 Task 值
- **THEN** Tool 返回“无需更新”且不创建 Action Intent 或卡片 Outbox

#### Scenario: 差异超过卡片预算
- **WHEN** 完整的原值、新值和必要目标信息超过 `detailText` 4000 字符预算
- **THEN** Tool 拒绝准备并要求拆分更新
- **AND** 不创建 Intent，不得以未披露的截断值取得确认

#### Scenario: 字段需要额外权限
- **WHEN** Patch 包含关注者等需要专用权限的字段
- **THEN** 系统在准备阶段验证相应关注者更新权限
- **AND** 普通编辑权限不得替代缺失的专用权限

### Requirement: 每个Task快照上的参数集必须获得独立确认
系统 MUST 以 Job、Tool、规范化参数、原始 ONES 外部身份、Team、Task UUID、`serverUpdateStamp` 和写字段目录摘要生成 Intent 幂等指纹。同一快照上的完全相同请求 MAY 复用同一 Intent；Task 快照、身份、Team、目录或参数任一变化 MUST 产生新的 Action Intent 和确认。

#### Scenario: 重复提交同一快照和Patch
- **WHEN** 同一 Job 在同一 Task 更新戳上重复提出完全相同的规范化 Patch
- **THEN** 系统返回同一个 Action Intent 且不重复投放创建卡片

#### Scenario: Task变化后重新提交相同Patch
- **WHEN** Task 更新戳已经变化后再次提出文本相同的 Patch
- **THEN** 系统重新计算当前差异并创建新的 Action Intent
- **AND** 不复用旧卡片确认

#### Scenario: 用户修改确认内容
- **WHEN** 用户希望改变待更新字段或目标值
- **THEN** 原 Intent 不得被就地改写
- **AND** 修改后的参数必须创建新的 Intent 并逐次确认

### Requirement: ONES缺陷更新必须在执行前阻断陈旧确认
worker MUST 在取得已批准 Intent 的执行 claim 后、调用 Provider 写接口前重新读取当前缺陷并复核 Task UUID、工作项类型、Team、可见性、字段适用性、字段级权限与 `serverUpdateStamp`。任一事实缺失、歧义、撤销或漂移 MUST fail closed；任何更新戳变化均 MUST 使整张确认失效，即使变化发生在本次 Patch 未涉及的字段。

#### Scenario: 确认后Task未变化
- **WHEN** 原始身份、授权、权限、字段目录和 Task 更新戳均保持有效
- **THEN** worker 仅发送用户已确认的编译后 Patch

#### Scenario: 确认后Task被他人修改
- **WHEN** 执行前读取的 `serverUpdateStamp` 与确认快照不一致
- **THEN** worker 不调用 ONES 写接口并以冲突终结当前 Intent
- **AND** 结果卡片要求用户基于最新值重新发起确认

#### Scenario: 确认后只有无关字段变化
- **WHEN** `serverUpdateStamp` 已变化但本次 Patch 的目标字段表面上仍与确认时相同
- **THEN** worker 仍使当前确认失效且不自动合并或继续执行

#### Scenario: 确认后字段不再适用或权限被撤销
- **WHEN** 当前布局不再包含目标字段或当前身份失去所需权限
- **THEN** worker 在写调用前终结 Intent
- **AND** 不删除字段、不降级权限检查也不尝试其它写法

### Requirement: ONES update3结果必须归一化并防止未知结果重放
worker SHALL 仅在 Provider HTTP 调用成功、响应结构合法且 `bad_tasks` 为空时把提交视为已接受，并 MUST 通过只读回查验证确认字段达到目标值。明确部分失败 SHALL 终结为失败；超时、连接中断或 worker 中断 SHALL 先回查，无法证明结果时进入 `FAILED_UNCERTAIN` 且不得自动重放写请求。

#### Scenario: Provider明确更新成功
- **WHEN** `update3` 返回合法响应且 `bad_tasks` 为空，回查字段也等于确认值
- **THEN** Intent 进入 `SUCCEEDED`
- **AND** 结果卡片显示更新成功

#### Scenario: Provider返回失败Task
- **WHEN** 合法响应中的 `bad_tasks` 非空
- **THEN** Intent 进入明确失败终态并保存有界安全错误摘要
- **AND** 不把 HTTP 成功误报为 Task 更新成功

#### Scenario: 超时后回查已达到目标值
- **WHEN** 写请求结果不确定但只读回查证明全部确认字段等于目标值
- **THEN** 系统记录“核对后成功”并进入 `SUCCEEDED`
- **AND** 不再次发送写请求

#### Scenario: 超时后无法证明结果
- **WHEN** 写请求结果不确定且回查不存在、失败或目标字段不完全匹配
- **THEN** Intent 进入 `FAILED_UNCERTAIN`
- **AND** 禁止自动重放并在卡片中要求人工核对

### Requirement: ONES缺陷Action Intent必须复用单一受治理外部操作链
系统 SHALL 复用现有 `external_action_intent`、Card Outbox、签名确认回调、数据库 claim/lease、恢复和审计主账，并 MUST 分离钉钉确认渠道事实与 ONES 执行 Provider 事实。ONES 身份、Team、目标 Task、前置条件和目录摘要 MUST 以无 Secret 的显式受约束字段保存；钉钉 Union ID 不得冒充 ONES 身份。

#### Scenario: 投放ONES更新确认卡片
- **WHEN** `ones_update_task` 成功准备 Intent
- **THEN** Card Outbox 继续使用同一 Intent ID、revision 与来源钉钉路由投放卡片
- **AND** execution provider 被明确记录为 `ones`

#### Scenario: 两个worker竞争同一ONES Intent
- **WHEN** 多个 `enterprise_agent-external-action-worker` 实例扫描同一已批准 Intent
- **THEN** 只有一个实例获得数据库执行 claim 并进入 ONES 适配器

#### Scenario: Intent或审计包含认证材料
- **WHEN** 系统准备、投放、执行或记录 ONES 缺陷更新
- **THEN** Intent、Outbox、卡片和安全审计均不得包含密码、Token、认证 Header、Cookie 或 Credential Secret
