## ADDED Requirements

### Requirement: 钉钉企业 App 连接引用受治理企业
每个 `dingtalk_enterprise_stream` 连接 MUST 引用一个钉钉企业内部 ID，且 MUST NOT 使用管理员自由填写的租户字符串定义身份命名空间；连接名称、内部 Connector ID、Client ID 或机器人名称均不得代替企业 Corp ID。

#### Scenario: 创建首个钉钉应用连接
- **WHEN** 管理员为待验证企业提交应用连接名称、Client ID 和 Client Secret
- **THEN** 系统保存企业引用和受控 Secret reference，不要求或接受自由 `tenant_code`

#### Scenario: 创建后续应用连接
- **WHEN** 管理员为已验证企业创建第二个应用连接
- **THEN** 系统引用同一企业记录并在消息阶段校验真实 Corp ID，不创建新的租户命名空间

#### Scenario: 客户端仍提交旧租户字段
- **WHEN** 新建或编辑钉钉应用连接请求提交 `tenant_code` 试图覆盖企业归属
- **THEN** 系统拒绝该可信字段或明确忽略旧兼容输入，持久化关系只来自所选企业 ID

### Requirement: 连接可用性同时受连接和企业状态约束
钉钉应用连接只有在自身启用、运行凭据有效且所属企业为 `ACTIVE` 时才能用于业务入口；企业待验证时连接 MAY 建立 Stream 以收集验证证据，但 MUST NOT 被业务应用选为可运行入口。

#### Scenario: 待验证企业的连接已建立
- **WHEN** Stream SDK 已连接但所属企业仍为 `PENDING_VERIFICATION`
- **THEN** 管理页面显示“已连接，等待企业验证”，业务应用候选和运行时入口均不把该连接视为可用

#### Scenario: 企业被停用
- **WHEN** 应用连接自身仍启用但所属企业变为 `DISABLED`
- **THEN** 系统停止该连接的业务入口并将其从新业务应用渠道选择中排除

#### Scenario: 企业已启用但连接断线
- **WHEN** 企业为 `ACTIVE` 而某个连接处于 `RECONNECTING`
- **THEN** 系统分别报告企业启用和连接重连状态，不显示为“待注册”或“等待企业验证”

### Requirement: 删除连接不得改写历史发布来源
删除或测试数据重建钉钉连接时，系统 SHALL 使连接不再参与活动路由并撤销其专属 Secret；历史 Application Publication、Agent Job 和投递记录中的连接引用 MUST 保持原值并标记为不可用历史来源。

#### Scenario: 删除已被历史发布引用的连接
- **WHEN** 管理员清理一个已被旧应用发布引用的测试连接
- **THEN** 系统不把历史发布自动切换到其他连接，当前应用必须选择新连接并重新发布

#### Scenario: 查看历史运行记录
- **WHEN** 管理员查看由已清理连接产生的历史 Job 或投递记录
- **THEN** 页面显示历史连接名称或 ID 及“已清理／不可用”状态，记录本身仍可读取
