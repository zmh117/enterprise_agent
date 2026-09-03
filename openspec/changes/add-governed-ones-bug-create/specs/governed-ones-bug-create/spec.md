## ADDED Requirements

### Requirement: ONES缺陷创建必须是代码固定的单资源mutation Tool
系统 SHALL 只通过代码 Manifest 固定的 `ones_create_bug` 提出 ONES 缺陷创建。一次调用 MUST 只创建一个缺陷，工作项类型 MUST 由服务端固定为“缺陷”；调用方不得控制 Provider URL、HTTP method、REST path、Header、Team、用户身份、认证材料、工作项类型 UUID、字段 UUID、字段 type、原始 `field_values`、父任务或工时。

#### Scenario: 提出单个缺陷创建
- **WHEN** 已授权钉钉来源 Job 使用完整合法参数调用 `ones_create_bug`
- **THEN** ONES MCP 只准备一个待确认 Action Intent
- **AND** 在原用户确认前不得调用 ONES 创建接口

#### Scenario: 尝试透传Provider参数
- **WHEN** Tool 输入包含 URL、Header、Team、认证字段、工作项类型、原始字段 UUID/type、`field_values`、父任务、工时或其它未声明字段
- **THEN** Tool 在任何 Provider 网络访问前返回字段级合同错误

#### Scenario: 尝试创建其它工作项
- **WHEN** 调用方请求创建需求、任务、工单、多个工作项或非缺陷工作项
- **THEN** Tool 拒绝且不创建 Action Intent

### Requirement: ONES缺陷创建必须具有完整且有界的业务字段
正式创建提案 MUST 同时包含非空标题、项目 UUID、纯文本描述、环境、负责人 UUID、缺陷类型 UUID、紧急程度 UUID、严重程度 UUID、发现难易程度 UUID、重现概率 UUID、非空产品 UUID 数组、非空功能模块 UUID 数组、缺陷发现阶段 UUID、是否线上缺陷 UUID、是否历史缺陷 UUID及非空影响版本 UUID 数组。产品、功能模块和影响版本数组 SHALL 按首次出现顺序去重；任一必填字段缺失、空白、`null`、类型错误或超出代码固定大小边界时 MUST 在创建 Intent 前拒绝。

#### Scenario: 提交完整业务字段
- **WHEN** 调用提供全部必填字段且通过类型、长度、数量和引用校验
- **THEN** Tool 接受该完整提案进入预检

#### Scenario: 缺少任一必填字段
- **WHEN** 标题、项目、描述、环境、负责人或任一必填分类与多选字段缺失、为空或为 `null`
- **THEN** Tool 返回可定位字段的中文错误
- **AND** 不创建 Intent、卡片 Outbox 或 Provider 写请求

#### Scenario: 多选值包含重复UUID
- **WHEN** 产品、功能模块、影响版本或额外关注者数组包含重复 UUID
- **THEN** 系统按首次出现顺序去重后继续校验

### Requirement: Agent建议值必须可区分且不得补造事实
Agent MAY 从当前用户消息、当前钉钉会话中与本次缺陷直接相关的上下文或引用消息、版本化文档目录，以及本次请求执行的 ONES 只读查询结果生成候选值。每个候选值 MUST 标记为建议值并保存安全来源类别；系统 MUST NOT 使用其它会话、其它用户数据、长期记忆或过期缓存补全提案。Agent MUST NOT 编造缺陷事实；描述仍含“待补充”或任一引用无法唯一解析时，不得调用正式创建 Tool。

#### Scenario: Agent根据当前上下文生成完整建议
- **WHEN** 当前允许的上下文足以形成所有必填字段的唯一候选值
- **THEN** Agent MAY 调用 Tool，并明确提交哪些字段属于建议值
- **AND** 确认卡片逐项显示对应“建议值”标记

#### Scenario: 描述事实不完整
- **WHEN** 重现步骤、预期结果、实际结果或其它必要事实只能写成“待补充”
- **THEN** Agent 只在普通钉钉会话中展示草稿并要求用户补充
- **AND** 不创建 Intent 或确认卡片

#### Scenario: 名称无法唯一解析
- **WHEN** 项目、人员、产品、模块、版本或其它引用名称不存在、同名或无法唯一映射 UUID
- **THEN** Agent 必须询问用户且不得任选一个值

### Requirement: ONES缺陷创建必须使用独立固定字段目录和安全编译器
系统 MUST 使用独立、版本化的 `bug_create_field_catalog` 固定第一版字段 UUID、Provider type、中文标签、值类型和接口文档中确认稳定的静态选项 UUID，并提供文档中已知项目、人员、产品、功能模块和版本的名称到 UUID 索引。第一版 SHALL 使用单一代码审查目录，不增加按 ONES 实例或 Team 划分的 Profile，也不要求运行时动态刷新静态枚举；运行时 MUST NOT 直接解析完整 `查询条件字典.yaml`。名称解析 MUST 先使用版本化文档目录，只有文档目录找不到唯一 UUID 时才调用当前身份的代码固定 ONES 只读接口；确认前仍 MUST 验证引用有效性，且功能模块 MUST 属于所选产品。

#### Scenario: 使用静态枚举值
- **WHEN** Tool 为缺陷类型、紧急程度、严重程度、发现难易程度、重现概率、发现阶段、线上缺陷或历史缺陷提供 UUID
- **THEN** 编译器只接受字段目录中对应字段的稳定选项 UUID
- **AND** 只生成目录固定的 field UUID 与 type

#### Scenario: 验证动态引用关系
- **WHEN** Tool 提供项目、负责人、额外关注者、产品、功能模块或影响版本 UUID
- **THEN** 系统先使用版本化文档目录解析名称，目录找不到唯一 UUID 时才调用当前身份的只读接口补充解析
- **AND** 在正式确认前验证最终引用存在、可用且属于当前 Team/项目范围
- **AND** 任一功能模块不属于所选产品时完整拒绝

#### Scenario: 文档中存在唯一UUID
- **WHEN** 名称在版本化文档目录中精确命中一个合法 UUID
- **THEN** 系统使用该 UUID 作为候选值且不为名称解析额外调用 ONES 接口
- **AND** 后续权限、布局和引用有效性预检仍按正式确认规则执行

#### Scenario: 文档中找不到UUID
- **WHEN** 名称在版本化文档目录中不存在唯一合法 UUID
- **THEN** 系统调用代码固定的 ONES 只读接口解析
- **AND** 接口结果仍不存在、同名或歧义时要求用户确认且不得猜测

#### Scenario: 编译描述
- **WHEN** 完整提案包含纯文本描述
- **THEN** 编译器生成 ONES 要求的纯文本与安全转义富文本字段
- **AND** 不接受调用方提供任意 HTML

#### Scenario: 生成关注者
- **WHEN** 当前 ONES 用户已解析且调用方未提供或提供了额外关注者
- **THEN** 最终关注者集合始终包含当前 ONES 用户，并与额外关注者按稳定顺序去重
- **AND** 调用方不得移除当前用户

### Requirement: 正式确认前必须完成身份权限和字段预检
ONES MCP MUST 在创建 Intent 前，以当前 RUNNING Job 的内部用户解析唯一启用的 ONES 身份、原始 Team 与当前 Credential，并验证目标项目允许创建“缺陷”、当前身份具有创建权限、固定工作项类型唯一适用、字段布局接受全部必填字段及所有引用 UUID 有效。项目可见、项目成员身份或普通编辑权限 MUST NOT 替代明确创建权限。若 Provider 没有可靠只读权限或布局接口，真实创建 Tool MUST 保持不可用。

#### Scenario: 创建预检通过
- **WHEN** 当前身份、Team、Credential、创建权限、缺陷类型、字段布局和引用值均可可靠验证
- **THEN** Tool MAY 保存无 Secret 的预检事实并创建待确认 Intent

#### Scenario: 仅能证明项目可见
- **WHEN** 当前只读接口只能证明用户可查看项目但不能证明创建权限或字段布局
- **THEN** Tool 返回稳定中文不可用错误且不创建正式确认卡片

#### Scenario: 尝试切换身份或Team
- **WHEN** 当前绑定、默认 Team 或目标权限不满足创建要求
- **THEN** 系统不得回退管理员、服务账号、其它用户、其它绑定或其它 Team
- **AND** 用户必须显式重新验证或切换后重新生成提案

### Requirement: 缺陷创建确认卡必须完整且复用现有模板
正式提案 MUST 通过来源钉钉 Connector 向原提案用户私发独立确认卡片，并复用 Web 后台配置的 `external_action_confirmation` 模板及既有 `providerName`、`operationName`、`targetName`、`detailText` 合同。卡片 MUST 以中文完整展示项目、固定工作项类型“缺陷”、标题、完整描述、环境、负责人、全部分类、多选字段、当前用户及额外关注者，并区分建议值；不得展示 Task UUID、字段 UUID/type、生成 HTML、认证材料或其它内部参数。

#### Scenario: 渲染完整创建卡片
- **WHEN** 提案通过预检且完整中文摘要不超过 `detailText` 4000 字符
- **THEN** 卡片使用 `providerName=ONES`、`operationName=创建缺陷`、标题目标和全部中文业务字段
- **AND** 使用现有确认、拒绝与状态更新交互

#### Scenario: 完整内容超过卡片预算
- **WHEN** 标题、完整描述和其它字段合计超过 4000 字符展示预算
- **THEN** Tool 拒绝准备并要求用户缩短或完善内容
- **AND** 不创建 Intent，不得截断或隐藏待写内容后取得确认

#### Scenario: 输入包含附件或图片
- **WHEN** 用户要求把图片、文件、截图或附件随第一版缺陷上传
- **THEN** 系统不上传、不写入临时下载地址，并提示先补充可确认的纯文字描述

#### Scenario: 用户要求在卡片内编辑
- **WHEN** 用户点击模板中的补充动作或要求直接修改卡片字段
- **THEN** 系统只引导用户回到当前钉钉会话说明修改内容
- **AND** 不在卡片中编辑原 Intent 参数

### Requirement: 创建提案修订必须产生新Intent并使旧待确认版本失效
每个完整提案版本 MUST 使用独立 Intent、卡片实例与 `outTrackId`。只有用户明确表示修改上一版，或当前消息可靠引用上一张确认卡时，系统才可建立同一提案链；新版本创建与旧 `PENDING_CONFIRMATION` Intent 转为 `SUPERSEDED` MUST 原子提交。仅会话相同、标题相似或字段相同不得自动建立替代关系。

#### Scenario: 明确修改待确认版本
- **WHEN** 原用户明确修订同一提案且旧 Intent 仍为 `PENDING_CONFIRMATION`
- **THEN** 系统创建新 Intent，并原子把旧 Intent 转为 `SUPERSEDED`
- **AND** 旧卡后续点击显示“已被新版本替代，请使用最新确认卡”

#### Scenario: 同一会话创建另一个缺陷
- **WHEN** 新请求没有明确修订证据，即使标题或字段与旧提案相似
- **THEN** 系统创建独立提案链且不废弃旧卡

#### Scenario: 旧版本已经批准或执行
- **WHEN** 用户提出修改时旧 Intent 已为 `APPROVED`、`EXECUTING` 或其它非待确认状态
- **THEN** 系统不得替代、取消或再生成同链创建卡
- **AND** 提示等待创建结果后通过 `ones_update_task` 发起独立更新

### Requirement: 确认必须绑定原发起人并具有固定有效期
确认卡有效期 MUST 为生成后 15 分钟，只有原提案内部用户对应的原钉钉主体可以批准或拒绝。到期后 Intent MUST 转为 `EXPIRED`；原 ONES 身份解绑、换绑、停用或原 Team 变化时，原卡 MUST 失效且不得按新身份继续执行。

#### Scenario: 原发起人在有效期内确认
- **WHEN** 回调签名、Intent revision、来源 Connector、企业、钉钉主体和内部用户均与提案事实匹配
- **THEN** 系统原子把仍待确认的 Intent 转为 `APPROVED`

#### Scenario: 群内其他成员点击卡片
- **WHEN** 点击者不是原提案发起人
- **THEN** 系统拒绝且不改变 Intent 状态

#### Scenario: 卡片已经过期
- **WHEN** 用户在生成 15 分钟后点击旧卡
- **THEN** 系统将其视为 `EXPIRED` 且不得批准
- **AND** 该版本预生成的 Task UUID 永久废弃且不得复用

### Requirement: 确认后执行必须再次校验并只使用冻结请求
`enterprise_agent-external-action-worker` MUST 在取得已批准 Intent 的唯一执行 claim 后、调用 ONES 前，再次复核原内部用户、Job Tool Snapshot、Application/角色授权、原 ONES 身份、原 Team、当前 Credential、创建权限、缺陷类型、字段布局、目录摘要和全部引用 UUID。任一事实撤销、歧义、失效或漂移 MUST 在写入前失败关闭；worker 只能发送用户确认的冻结业务值和服务端生成字段。

#### Scenario: 二次校验通过
- **WHEN** 确认事实、授权、身份、权限、布局、字段目录和引用值均保持有效
- **THEN** worker 只构造并发送该 Intent 冻结的 `add3` 请求

#### Scenario: 确认后权限或布局变化
- **WHEN** 用户确认后创建权限被撤销、必填字段不再适用或引用 UUID 失效
- **THEN** worker 不调用创建接口，并以中文结果要求重新生成提案

#### Scenario: 确认后身份换绑
- **WHEN** 原 ONES 身份已解绑、换绑或 Team 已变化
- **THEN** worker 拒绝执行且不得使用新的身份、Team 或 Credential

### Requirement: 创建UUID和不确定结果必须阻止重复缺陷
系统 MUST 在生成正式确认卡前创建并冻结一个新的 Task UUID，并在该 Intent 的所有执行、恢复与核验中只使用该 UUID。Provider 明确成功后 MUST 按同一 UUID 回查并验证全部确认字段；UUID 冲突、超时、连接中断或 worker 中断时也只能按同一 UUID 查询。仅当回查任务存在且全部业务字段与确认快照一致时才可记为 `SUCCEEDED`；不存在、字段不一致或无法可靠核验时 MUST 进入 `FAILED_UNCERTAIN`，不得自动更换 UUID、自动重放创建或把未知结果报告为失败后重建。

#### Scenario: Provider明确创建并回查一致
- **WHEN** `add3` 返回合法成功且按冻结 UUID 回查的全部字段与确认快照一致
- **THEN** Intent 进入 `SUCCEEDED` 且不再发送创建请求

#### Scenario: 超时后回查一致
- **WHEN** 创建请求结果不确定但按冻结 UUID 回查到完整一致的缺陷
- **THEN** 系统记录“核验后成功”并进入 `SUCCEEDED`
- **AND** 不重放创建请求

#### Scenario: UUID冲突或结果无法证明
- **WHEN** Provider 返回 UUID 冲突，或超时/连接中断后的回查不存在、不一致或不可用
- **THEN** Intent 进入 `FAILED_UNCERTAIN`
- **AND** 系统不得生成新 UUID 或自动再次创建

#### Scenario: 重复消息或多worker竞争
- **WHEN** 同一已批准 Intent 被重复投递或多个 worker 同时扫描
- **THEN** 只有一个 worker 获得数据库执行 claim
- **AND** 其它消费者不得调用 Provider

### Requirement: ONES缺陷创建必须复用单一外部操作链并保留安全审计
系统 SHALL 复用 `external_action_intent`、Card Outbox、签名回调、数据库 claim/lease、恢复、审计主账和 `enterprise_agent-external-action-worker`，不得新增第二套 mutation 表、队列或 Worker 服务。审计 MUST 保存用户确认的完整业务字段快照、建议值与安全来源类别、发起人、绑定 revision、预检结果、卡片动作、请求摘要哈希和最终结果；不得保存原始钉钉上下文、Agent 私有推理、Token、密码、认证 Header、Cookie 或未经白名单过滤的 ONES 原始响应。

#### Scenario: 创建缺陷成功
- **WHEN** 用户确认且 Provider 创建与回查成功
- **THEN** 审计可由 Intent 关联 MCP Call、Agent Tool Call、Job、Session、actor、Connector、Tool/schema、Provider attempt 和结果卡片
- **AND** 结果卡片显示创建成功、缺陷编号、标题、项目和负责人

#### Scenario: 生成查看链接
- **WHEN** 服务端能够从受信任 ONES 基础地址和规范化结果生成任务链接
- **THEN** 结果卡片 MAY 显示“查看缺陷”链接
- **AND** 不直接采用 Provider 返回的任意 URL，也不展示内部 Task UUID

#### Scenario: 审计输入包含敏感或无界内容
- **WHEN** Provider 请求、响应或错误包含认证材料、原始响应正文或无界字段
- **THEN** 审计只保存缺陷编号、Task UUID、状态、安全错误码及规定的确认业务快照

### Requirement: ONES缺陷创建必须显式发布且区分Mock与真实验收
注册 `ones_create_bug` MUST NOT 自动修改任何现有角色、Agent Publication、Application Publication 或 Job Tool Snapshot。管理员显式授权并发布后，只有随后创建且冻结该 Tool 的新 Job 才可见。当前无真实 ONES 服务时，本地完成证据 SHALL 限定为 Mock、合同、migration、卡片回调、worker、容器和 OpenSpec 校验；真实权限预检、创建、异常回查及完整审计链 MUST 保持未验收，且在可靠权限/布局接口和真实证据具备前不得宣称生产可用。

#### Scenario: 仅注册新Tool
- **WHEN** 新代码和 Manifest 部署但管理员没有创建新的角色授权与 Agent/Application Publication
- **THEN** 现有应用、角色、运行中 Job 和历史 Job 均不得获得 `ones_create_bug`

#### Scenario: Mock链路通过
- **WHEN** 受控 ONES Mock 完成预检、确认、创建、回查和异常用例
- **THEN** 验收只报告本地合同与 Mock 链路通过
- **AND** 不将其描述为真实 ONES 生产可用证据

#### Scenario: 缺少真实权限预检接口
- **WHEN** 真实 Provider 仍不能可靠验证创建权限或字段布局
- **THEN** 真实创建能力保持不可启用
