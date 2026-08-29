## ADDED Requirements

### Requirement: 外部 mutation 必须先创建不可变操作意图
任何代码注册为 `mutation` 的业务 MCP Tool SHALL 在有效 Job 内只创建持久 `Action Intent` 和确认卡投放 Outbox，不得在首次 Tool Call 中访问写入型 Provider endpoint。意图 MUST 冻结 Job、Session、actor、Application/Agent Publication、Server、Tool/schema、确认策略、来源 Connector、规范化参数及其 hash。

#### Scenario: Agent 提议创建待办
- **WHEN** RUNNING Job 调用已授权的 `dingtalk_create_todo`
- **THEN** 系统原子创建 `PENDING_CONFIRMATION` 意图与卡片 Outbox，返回 `confirmation_required`
- **AND** 不调用钉钉待办创建接口

#### Scenario: 同一 Tool Call 重试
- **WHEN** 同一 Job、Tool 和规范化参数 hash 再次进入准备阶段
- **THEN** 系统返回原意图且不创建第二张卡或第二个执行记录

### Requirement: 确认回调必须绑定原始 actor 和当前 revision
系统 MUST 仅接受来源 Connector、企业、`outTrackId`、点击用户、opaque intent token、action 和 revision 与当前意图全部一致的卡片回调。卡片禁止转发 MUST NOT 替代服务端 actor 校验。

#### Scenario: 原始用户同意当前版本
- **WHEN** 原始 actor 在原 Connector 的卡片上提交 `agree` 且 revision 匹配
- **THEN** 系统只把意图从 `PENDING_CONFIRMATION` 转为 `APPROVED` 并返回快速 ACK

#### Scenario: 其他用户点击转发卡
- **WHEN** 回调 `userId` 不等于意图目标外部用户
- **THEN** 系统拒绝且不改变意图、不创建执行、不泄露参数

#### Scenario: 重复或过期点击
- **WHEN** 回调针对终态、过期或 revision 不匹配的意图
- **THEN** 系统返回幂等或安全拒绝结果且不重复执行

### Requirement: 拒绝不得产生 Provider 副作用
合法 `reject` SHALL 把当前待确认意图转为 `REJECTED`，并 MUST NOT 创建、claim 或执行任何 Provider mutation。

#### Scenario: 用户拒绝创建待办
- **WHEN** 原始 actor 对当前意图提交合法 `reject`
- **THEN** 卡片更新为已拒绝且 Provider 调用次数为零

### Requirement: 已批准意图必须异步、可恢复且执行前重新授权
外部操作 worker SHALL 以数据库 claim/lease 获取 `APPROVED` 意图，在 Provider I/O 前重新复核当前用户、身份、Connector、企业、Application、Tool/schema 和角色授权。worker MUST 在事务外执行外部 I/O，并把结果写为 `SUCCEEDED`、`FAILED` 或不确定失败终态。

#### Scenario: 批准后权限仍有效
- **WHEN** worker claim 已批准意图且所有当前事实仍有效
- **THEN** worker 只执行一次固定 Provider operation 并持久化有界结果

#### Scenario: 批准后 Tool 被撤权
- **WHEN** 用户点击同意后角色或 Application 已撤销该 Tool
- **THEN** worker 在 Provider I/O 前失败关闭并记录授权拒绝

#### Scenario: worker 在 claim 后重启
- **WHEN** 执行租约超时且没有已确认 Provider 成功事实
- **THEN** 恢复器按意图的幂等策略重新 claim 或转为不确定失败，不得无条件重复创建

### Requirement: 卡片投放和结果更新必须使用有界 Outbox
确认卡创建、投放和结果更新 SHALL 由持久 Outbox 驱动，`outTrackId` MUST 等于 Action Intent ID，`callbackType` MUST 为 `STREAM`，`supportForward` MUST 为 false。卡片参数 MUST 只包含安全业务摘要、revision 和 opaque token。

#### Scenario: 投放本人确认卡
- **WHEN** 卡片 worker 处理新意图 Outbox
- **THEN** 系统使用原 Connector 应用和指定模板向原始钉钉用户投放一张不可转发卡

#### Scenario: Secret 出现在卡片参数
- **WHEN** 待投放字段包含 Token、密码、Principal JWT、Cookie 或平台 Secret
- **THEN** 系统拒绝整个投放且不持久化或发送该值

### Requirement: 未实现的修订动作必须失败关闭
MVP 对 `revise` 或补充并重新生成动作 MUST 返回稳定的暂不支持结果，不得修改冻结参数、不得执行旧意图，也不得把补充文本拼接为未治理 Prompt。

#### Scenario: 用户点击补充并重新生成
- **WHEN** 指定模板在 MVP 阶段回传 `revise`
- **THEN** 系统保持原意图待确认或安全取消，并返回 `external_action_revision_not_supported`
- **AND** 不创建 Agent Job 或 Provider 调用

