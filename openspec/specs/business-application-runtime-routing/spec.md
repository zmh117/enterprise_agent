# business-application-runtime-routing Specification

## Purpose
TBD - created by archiving change complete-business-application-runtime-routing. Update Purpose after archive.
## Requirements
### Requirement: 应用部署只使用local且与业务数据环境相互独立
系统 MUST 只允许创建、激活、回退、查询或停用 `local` Business Application Deployment，并 MUST NOT 使用 Channel event 的业务数据 `routing.environment` 选择应用版本。

#### Scenario: 本地运行时处理三九数据范围
- **WHEN** 服务运行于 `APP_ENV=local` 且钉钉事件的 `routing.environment` 为 `sanjiu`
- **THEN** 系统只查询该应用的 `local` Deployment
- **AND** `sanjiu` 原样保留在 Agent Job 的业务 routing context 中

#### Scenario: 管理端请求非local部署
- **WHEN** 管理端请求 `test`、`staging`、`production` 或其他非 `local` Deployment
- **THEN** 管理 API 拒绝请求并返回 `environment` 字段错误
- **AND** 系统不创建 Deployment 或 route 投影

### Requirement: 系统返回统一且真实的运行时接线状态
系统 SHALL 由单一运行时就绪评估器计算 `runtime_wired`、整体 `runtime_status` 和逐组件状态，并 MUST 在应用列表、详情、Publication、Deployment、effective 查询、激活响应和审计中使用同一结果。

#### Scenario: 当前环境存在可执行钉钉路由
- **WHEN** 数据面闸门开启，当前部署环境存在完整且受支持的活动钉钉 route
- **THEN** `runtime_wired` 为 `true`
- **AND** Trigger routing、Agent Publication、Session Policy 和 Delivery 分别返回其真实组件状态

#### Scenario: 只有部分配置已接线
- **WHEN** 钉钉路由可以执行但 Workflow 或 Execution Policy 字段仍只被存储
- **THEN** 整体状态为 `partially_wired`
- **AND** 未执行字段返回 `stored_only` 及稳定 reason code

#### Scenario: 活动路由完整性失败
- **WHEN** 当前环境的活动 route 指向 hash 不一致、schema 不支持或依赖缺失的 Publication
- **THEN** 整体状态为 `blocked`
- **AND** 系统不得把该应用显示为已完整接管

#### Scenario: 数据面闸门关闭
- **WHEN** `FEATURE_PUBLISHED_AGENT_RUNTIME` 关闭
- **THEN** `runtime_wired` 为 `false` 且整体状态为 `not_wired`
- **AND** 响应明确指出数据面闸门未开启

### Requirement: 第一阶段运行时只接管受支持的钉钉Trigger
系统 MUST 只将 `dingtalk_private + CURRENT_SENDER` 和 `dingtalk_group + CURRENT_SENDER` 标记为第一阶段可执行 Trigger，并 SHALL 将 Webhook、Workflow 和 API Capability 等未接线路径明确标记为 `stored_only` 或 `unsupported`。

#### Scenario: 评估钉钉私聊应用
- **WHEN** Publication 包含合法 `dingtalk_private` Trigger 和当前发送人 actor policy
- **THEN** 运行时就绪评估器按钉钉私聊支持矩阵校验该 Trigger

#### Scenario: 评估Webhook Trigger
- **WHEN** Publication 包含 Webhook Trigger
- **THEN** 本变更不让 Business Application Resolver 接管该 Webhook
- **AND** 管理端状态明确为 `stored_only` 而不是已生效

#### Scenario: Publication包含非空Capability
- **WHEN** 应用引用尚未接入目录的 API Capability
- **THEN** 现有发布校验继续阻止发布
- **AND** 系统不得将其映射为数据库、Redis、Loki 或其他内部工具

### Requirement: 活动路由解析是确定性的三态结果
系统 SHALL 将运行时路由解析结果建模为 `matched`、`not_matched` 或 `blocked`，并 MUST 使用部署环境、Trigger type、受信 connector ID 和规范化 routing key 唯一解析活动应用。

#### Scenario: 唯一路由命中
- **WHEN** 当前环境存在唯一且完整的活动 route 与事件规范化路由键相同
- **THEN** Resolver 返回 `matched`、应用、Publication、Deployment、route 和逐组件状态

#### Scenario: 没有活动路由
- **WHEN** 当前环境不存在与事件匹配的活动 route
- **THEN** Resolver 返回 `not_matched`
- **AND** 不把“没有匹配”表示为完整性异常

#### Scenario: 命中路由但Publication损坏
- **WHEN** route 投影存在但关联 Publication 无法通过 schema、hash 或引用完整性校验
- **THEN** Resolver 返回 `blocked` 和安全 reason code
- **AND** 不返回其他业务应用或默认 Agent 作为匹配结果

### Requirement: 未命中和命中后异常均失败关闭
系统 MUST 对 `not_matched` 和 `blocked` 的钉钉事件停止 Job 创建与 MQ 发布、记录审计并触发安全失败通知，MUST NOT 使用默认 Agent 兼容路径。

#### Scenario: 未配置业务应用路由
- **WHEN** 合法钉钉消息的路由结果为 `not_matched`
- **THEN** 系统不创建 Agent Job 或发布 RabbitMQ 消息
- **AND** 记录 `business_application.route.not_matched`
- **AND** 钉钉用户收到“当前机器人未配置可用的业务应用，请联系管理员”

#### Scenario: 已匹配应用配置无效
- **WHEN** 合法钉钉消息命中 route 但运行时结果为 `blocked`
- **THEN** 系统不创建 Agent Job
- **AND** 不静默回退到默认 Agent 或其他应用
- **AND** 钉钉用户收到不含敏感细节的错误通知

### Requirement: 命中应用后固定不可变运行版本
系统 MUST 以命中的 Business Application Publication 固定 Agent Publication 和所有已支持策略，MUST NOT 允许 Channel event、后续激活或 Worker 重新解析覆盖已经固定的版本。

#### Scenario: 入口携带相同Agent Publication
- **WHEN** 命中应用且事件携带的 Agent Publication 与应用快照完全一致
- **THEN** 系统使用应用快照版本创建 Job并记录一致性来源

#### Scenario: 入口尝试覆盖Agent Publication
- **WHEN** 命中应用但事件携带不同 Agent Publication、revision 或 hash
- **THEN** 系统将路由标记为 `blocked/agent_override_conflict`
- **AND** 不创建使用任一冲突版本的 Job

#### Scenario: Job入队后激活新版本
- **WHEN** Job 已固定 Publication 并入队，管理员随后激活新应用 Publication
- **THEN** 已入队 Job 继续使用原固定版本
- **AND** 后续新事件才解析到新版本

### Requirement: 激活回退和停用具有明确运行影响
系统 SHALL 在激活历史或最新 Publication 前执行运行时预检，并 MUST 在激活、回退和停用响应中返回受影响 route、固定的 `local` 部署、接线状态与未命中失败说明。

#### Scenario: 激活到当前运行环境
- **WHEN** 管理员把通过预检的 Publication 激活到当前 `APP_ENV`
- **THEN** 系统原子更新 Deployment 与 route 投影
- **AND** 下一条匹配的新事件使用该 Publication

#### Scenario: 激活已知不可执行的路由
- **WHEN** 当前环境 Publication 的受支持钉钉 Trigger 缺少 bot/conversation identity、有效 Agent 或 reply-original Delivery
- **THEN** 系统拒绝激活并返回字段级或组件级错误
- **AND** 现有 Deployment 保持不变

#### Scenario: 回退到历史Publication
- **WHEN** 管理员重新激活一个仍通过当前运行时预检的历史 Publication
- **THEN** 后续新事件使用历史 Publication
- **AND** 审计记录旧、新 Publication ID 和操作主体

#### Scenario: 停用当前Deployment
- **WHEN** 管理员显式停用当前环境 Deployment
- **THEN** 系统移除对应活动 route 投影
- **AND** 后续无匹配事件失败关闭且不创建 Job
- **AND** 已入队 Job 不受影响

### Requirement: 路由决策可审计且不泄露敏感信息
系统 MUST 以 correlation ID 串联路由、Job、Agent 和 Delivery 阶段，并 SHALL 记录应用、Publication、Deployment、route、结果和安全 reason code，MUST NOT 在运行状态或审计中记录 Secret、Token、完整 session webhook 或敏感原始 payload。

#### Scenario: 应用路由成功创建Job
- **WHEN** 匹配事件成功创建 Agent Job
- **THEN** 审计包含 `matched`、application code、Publication ID、Deployment ID、route ID、job ID 和 correlation ID
- **AND** 不包含可直接调用钉钉的临时凭据

#### Scenario: 路由被阻止
- **WHEN** route 因完整性或策略错误被阻止
- **THEN** 审计记录稳定 reason code 和安全摘要
- **AND** 管理员可以从运行记录定位到对应应用版本

