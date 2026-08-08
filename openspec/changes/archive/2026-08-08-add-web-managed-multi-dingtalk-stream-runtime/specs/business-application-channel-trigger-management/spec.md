## ADDED Requirements

### Requirement: 业务应用导航提供独立渠道与触发器页面
系统 SHALL 在后端阶段验收完成后，在左侧导航“业务应用”分组中把“渠道与触发器”放在“应用列表”下方，并通过独立页面管理平台级 Channel。

#### Scenario: 打开渠道与触发器
- **WHEN** 有 Channel 读取权限的管理员通过侧边栏打开“渠道与触发器”
- **THEN** 系统进入独立路由 `/applications/channels`，加载统一 Channel 目录和每项服务端资格状态，不要求先打开或选择某个业务应用

#### Scenario: 查看业务应用导航层级
- **WHEN** 管理员查看左侧“业务应用”分组
- **THEN** “应用列表”和“渠道与触发器”显示为两个同级菜单项，且“渠道与触发器”排列在“应用列表”之后

#### Scenario: 打开应用详情
- **WHEN** 管理员打开某个业务应用详情
- **THEN** 应用详情不显示 Channel 创建、编辑、启停或重连页面，只在应用设置的 Trigger Binding 中选择合格 Channel

#### Scenario: 导航高亮
- **WHEN** 管理员在应用列表、渠道与触发器或具体应用详情之间导航
- **THEN** 侧边栏只高亮当前对应入口，不因路径前缀相同而同时高亮

#### Scenario: 后端接口失败
- **WHEN** 独立页面的 Channel 目录接口失败
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
系统 SHALL 在应用设置中通过服务端 eligible catalog 填充 Trigger Channel 选择器，并在保存和发布时再次校验兼容性；独立“渠道与触发器”页面 MUST NOT 直接修改应用 Trigger Binding。

#### Scenario: Channel 启用后进入应用选择器
- **WHEN** 管理员在独立“渠道与触发器”页面启用一个符合入口资格的 Channel
- **THEN** 该 Channel 出现在兼容 Trigger 类型的应用设置选择器中

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

#### Scenario: 编辑 Channel
- **WHEN** 管理员在独立“渠道与触发器”页面执行操作
- **THEN** 页面和请求只改变 Channel 配置，不改变 Business Application Revision 或 Agent Publication

#### Scenario: 编辑应用 Trigger
- **WHEN** 管理员在应用设置中选择 Channel
- **THEN** 请求只改变新的 Business Application 草稿修订，不改变 Channel 配置或 Agent Publication
