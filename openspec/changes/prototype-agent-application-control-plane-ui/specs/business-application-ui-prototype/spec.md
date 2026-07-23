## ADDED Requirements

### Requirement: 原型展示一个Runtime多个业务应用的产品模型
系统 SHALL 展示一个共享Agent Runtime、多个Agent Profile和多个Business Application之间的关系，业务应用 MUST 作为前端主要管理对象，而不是把Channel、Workflow、Profile和Capability展示为缺少装配关系的平行资源。

#### Scenario: 查看业务应用组成
- **WHEN** 用户查看任一业务应用卡片或关系摘要
- **THEN** 页面展示该应用引用的Agent Profile、Workflow、触发方式、API Capability数量、输出渠道和发布状态
- **AND** 不暗示每个应用需要部署独立Agent Runtime

### Requirement: 原型展示三个代表性业务应用
系统 SHALL 展示钉钉私聊诊断助手、钉钉群聊诊断助手和Webhook告警分析助手，三个示例 MUST 体现不同的会话主体、触发身份和流程形态。

#### Scenario: 查看钉钉私聊应用
- **WHEN** 用户查看钉钉私聊诊断助手
- **THEN** 页面展示按应用、租户和钉钉用户构成的人员会话语义
- **AND** API调用主体来自当前消息发送人的内部身份

#### Scenario: 查看钉钉群聊应用
- **WHEN** 用户查看钉钉群聊诊断助手
- **THEN** 页面展示群会话上下文和必须@机器人等触发条件
- **AND** 明确API权限仍按当前消息发送人判断而不是按群共享

#### Scenario: 查看Webhook告警应用
- **WHEN** 用户查看Webhook告警分析助手
- **THEN** 页面展示签名与幂等、服务账号、固定API节点、Agent分析和钉钉投递的静态流程
- **AND** 不把Webhook请求伪装成真实人员身份

### Requirement: 原型展示应用工作区目标页签
系统 SHALL 以静态页签或关系卡形式展示应用概览、流程设计、渠道与触发器、能力授权和发布管理的目标结构，但 MUST NOT 实现真实路由和编辑行为。

#### Scenario: 评审应用工作区
- **WHEN** 用户查看业务应用区域
- **THEN** 页面能够识别五个目标工作区及各自职责
- **AND** 编辑、测试、保存、发布和回滚入口处于不可操作状态

### Requirement: 原型区分确定性API节点与Agent自主能力
系统 SHALL 在Workflow预览中区分显式API Capability节点和Agent自主决策节点，并展示两种模式可以在同一流程内组合。

#### Scenario: 查看Webhook混合流程
- **WHEN** 用户查看Webhook告警分析流程
- **THEN** 固定告警查询和日志查询以显式API节点展示
- **AND** Agent节点展示其可继续自主选择的只读Capability集合

### Requirement: 原型展示API Capability而非底层数据源工具
系统 SHALL 使用业务能力编码、名称、描述、风险、环境和可用状态展示Capability，并 MUST NOT 提供数据库、Redis、Loki连接或任意查询语言的配置入口。

#### Scenario: 查看能力目录预览
- **WHEN** 用户查看API能力区域
- **THEN** 页面展示类似`log.query.application`、`order.query.detail`和`cache.query.status`的业务能力
- **AND** 不展示DSN、数据库方言、Redis地址、Loki地址、SQL、Redis命令、LogQL、Shell或任意HTTP URL

### Requirement: 原型展示能力授权交集和版本冻结
系统 SHALL 展示有效能力由平台发布、应用授权、Workflow节点授权、Agent Profile授权和当前主体数据权限取交集，并展示应用发布冻结所引用的Profile、Workflow、Capability、Channel和策略版本。

#### Scenario: 评审应用有效能力
- **WHEN** 用户查看应用的能力授权摘要
- **THEN** 页面展示权限交集而不是“允许全部API”的单一开关
- **AND** 高风险写能力显示为未授权或MVP不可用

#### Scenario: 评审发布快照
- **WHEN** 用户查看发布管理摘要
- **THEN** 页面展示发布版本引用的Profile Revision、Workflow Revision、Capability Version和Channel Binding
- **AND** 不提供真实发布或回滚操作
