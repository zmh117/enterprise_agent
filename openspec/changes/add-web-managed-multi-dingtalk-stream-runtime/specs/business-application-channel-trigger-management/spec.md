## ADDED Requirements

### Requirement: 业务应用提供渠道与触发器页面
系统 SHALL 在后端阶段验收完成后，为业务应用提供“渠道与触发器”页面，集中展示可管理 Channel 和当前应用的 Trigger Bindings。

#### Scenario: 打开渠道与触发器
- **WHEN** 有业务应用读取权限的管理员打开该页面
- **THEN** 页面加载统一 Channel 目录、当前应用草稿 Trigger Bindings 和每项服务端资格状态

#### Scenario: 后端接口失败
- **WHEN** Channel 目录或应用草稿接口失败
- **THEN** 页面显示明确错误和重试操作，不使用硬编码假数据或把空列表显示为成功

### Requirement: 页面只开放 Webhook 和钉钉应用机器人
系统 SHALL 在本阶段只展示 `WEBHOOK`、`DINGTALK_APP_ROBOT` 的创建和编辑入口。

#### Scenario: 新建钉钉应用机器人
- **WHEN** 管理员在页面选择钉钉应用机器人
- **THEN** 表单只显示名称、Client ID、Client Secret、私聊/群聊/必须 @ 和启用状态等声明字段

#### Scenario: 新建 Webhook
- **WHEN** 管理员在页面选择 Webhook
- **THEN** 页面使用现有受管 Webhook 配置能力，不提供任意出站 HTTP、SQL、Redis、Loki 或脚本配置

#### Scenario: 查看其他提供者
- **WHEN** 后端目录含有未来或仅投递类型 Connector
- **THEN** 页面不提供其创建入口，也不把它作为本阶段 Trigger 可选项

### Requirement: Trigger Binding 只能从合格 Channel 中选择
系统 SHALL 通过服务端 eligible catalog 填充 Trigger Channel 选择器，并在保存和发布时再次校验兼容性。

#### Scenario: 配置钉钉群聊 Trigger
- **WHEN** 管理员新增 `dingtalk_group` Trigger
- **THEN** 选择器只列出已启用且允许 ingress 的钉钉应用机器人

#### Scenario: 配置 Webhook Trigger
- **WHEN** 管理员新增 `webhook` Trigger
- **THEN** 选择器只列出已启用且入口配置完整的受管 Webhook

#### Scenario: Channel 在编辑后被停用
- **WHEN** 草稿引用的 Channel 在应用保存或发布前被停用
- **THEN** 服务端拒绝校验或发布，页面标记失效绑定并要求重新选择

### Requirement: Channel 配置与应用 Trigger Binding 保持不同生命周期
系统 SHALL 区分平台级 Channel 配置和应用修订中的 Trigger Binding；修改 Channel 不得静默改写已发布 Business Application Publication。

#### Scenario: 轮换钉钉 Secret
- **WHEN** 管理员轮换已绑定 Channel 的 Secret
- **THEN** Runtime 重建该连接，但 Business Application Publication 的 Trigger 标识保持不变

#### Scenario: 修改应用 Trigger
- **WHEN** 管理员为应用选择另一个 Channel
- **THEN** 变更只进入新的应用草稿，必须按现有校验、发布和激活流程生效

### Requirement: 页面不增加 Agent 功能
“渠道与触发器”页面 MUST NOT 增加 Agent Profile、模型连接、工具、执行并行或 Agent 运行参数配置。

#### Scenario: 编辑 Channel 或 Trigger
- **WHEN** 管理员在本页面执行任何操作
- **THEN** 页面和请求只改变 Channel 配置或 Business Application Trigger Binding，不改变 Agent Publication
