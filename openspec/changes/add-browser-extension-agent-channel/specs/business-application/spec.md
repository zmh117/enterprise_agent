## MODIFIED Requirements

### Requirement: 运行时接管受支持的钉钉与Webhook入口
应用运行态 SHALL 支持 `dingtalk_private`、`dingtalk_group`、`webhook` 与 `browser_extension` 四种已发布 Trigger。钉钉使用 CURRENT_SENDER 与 `bot:` 或 `conversation:` 路由键；Webhook 使用 BOUND_USER 与 `webhook:` 路由键，执行用户取自 Webhook 发布并与应用入口绑定一致。插件使用 CURRENT_SENDER、受管 Connector 和服务端生成的应用路由键，按已登录内部用户检查活动应用访问。未知类型、错误前缀、主体策略不匹配或无有效来源依赖 MUST 失败关闭。

#### Scenario: 钉钉入口
- **WHEN** 受信消息匹配启用的私聊或群聊 Trigger
- **THEN** 服务按当前发送人解析身份和角色，并固定命中的应用发布版本。

#### Scenario: Webhook入口
- **WHEN** 受治理 Webhook 绑定启用执行用户与已发布应用
- **THEN** 服务通过完整认证授权链创建 Job，不回退默认 Agent 或其他人工主体。

#### Scenario: Webhook重新绑定人员
- **WHEN** 事件执行用户与应用发布固定的入口用户不一致
- **THEN** 系统拒绝创建 Job 并提示重新保存、发布和激活应用，不静默切换执行身份。

#### Scenario: 插件入口按当前用户激活
- **WHEN** 用户选择本人有权访问且配置了插件入口的活动应用
- **THEN** 服务端检查 Agent Publication 的双向连接、应用发布、启用状态及当前访问权，使用唯一活动路由。没有可运行匹配时不展示为可用且不能创建 Job

### Requirement: 每个入口独立配置结果去向
新业务应用草稿和 Publication SHALL 将每条 Delivery 明确关联到一个 Trigger 的类型、连接器和规范化路由键（`delivery_binding_mode=per_trigger`）。每个 Trigger MUST 至多有一个投递方式；未引用、重复或不存在的入口关联 MUST 返回定位到字段的错误。钉钉入口 MUST 使用与入口连接器一致的回复原会话；Webhook SHALL 支持仅保存结果、钉钉私聊（最多 20 名人员）、钉钉群或高级 HTTP 回调。Webhook 无投递绑定或私聊名单为空时使用 none 路由。启用的插件入口 MUST 通过同一 Connector 绑定唯一的 `reply_original`，管理页显示「回复原插件会话」。

#### Scenario: 保存多人员投递
- **WHEN** 用户为 Webhook 选择钉钉私聊并选择最多 20 个不同目标人员
- **THEN** 管理 API 接受 `target_user_ids` 并保存入口关联，发布前复核企业与身份并冻结 `resolved_recipients`；空人员表示不发送

#### Scenario: 修改或删除入口
- **WHEN** 用户修改入口身份或删除触发器
- **THEN** 编辑器同步更新对应投递引用或删除该投递，不改变其他入口的投递

#### Scenario: 消息流向可见
- **WHEN** 用户查看组成配置
- **THEN** 每个触发器卡片展示入口、Agent 和自己的结果去向；保存错误展示在固定保存区

#### Scenario: 旧草稿存在未使用投递
- **WHEN** 原独立投递不能唯一归属于入口
- **THEN** 编辑器明确展示待处理配置并要求用户移除后保存，不静默丢弃或分配到其他入口

#### Scenario: 配置同一应用的多个渠道
- **WHEN** 管理员同时启用插件和钉钉入口
- **THEN** 插件结果绑定原插件会话，钉钉仍按其入口投递；插件缺回复、连接不匹配或绑定外部目标时拒绝发布/激活并定位到对应入口
