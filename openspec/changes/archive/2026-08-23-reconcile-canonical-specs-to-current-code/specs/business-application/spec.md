## MODIFIED Requirements

### Requirement: Web支持受控的应用编辑、校验和发布
系统 SHALL 为有权限用户提供严格表单来创建应用、编辑草稿、请求校验、发布和管理环境激活，并 MUST 根据权限、revision和校验结果控制动作可用性。页面 MUST 使用服务端统一评估器返回的 `runtime_wired`、`runtime_status` 和逐组件状态展示真实接线情况，不得把已接管或仅存储的组件统一描述为“尚未接线”。

#### Scenario: 保存应用草稿
- **WHEN** 用户选择合法 Agent Publication、Workflow Publication、Trigger、Delivery、MCP Tool 子集和策略并提交
- **THEN** 页面发送当前 expected revision 并展示服务器返回的新 revision
- **AND** 页面不会将 Secret、底层 URL 或任意工具配置提交给 API

#### Scenario: 校验失败后修正
- **WHEN** API 返回字段和组件校验错误
- **THEN** 页面在对应配置区域展示错误并保留用户可安全重试的输入
- **AND** 发布和激活动作保持禁用

#### Scenario: 发布或激活应用
- **WHEN** 用户成功发布或激活应用
- **THEN** 页面更新 Publication、Deployment 与服务端返回的真实运行时接线状态
- **AND** 页面分别展示已接线、部分接线、仅存储或阻塞的组件及稳定原因

### Requirement: Capability和数据源安全边界在真实页面中保持有效
系统 MUST 只展示 Agent Publication Envelope 中代码 Manifest 注册的 MCP Tool，并只允许 Business Application 选择该集合的精确子集。页面 MUST NOT 提供任意 Capability、Handler、MCP Server、HTTP、SQL、Redis、LogQL、Shell、底层连接或可执行模板录入入口。

#### Scenario: 查看MCP Tool组成区域
- **WHEN** 用户查看或编辑应用组成
- **THEN** 页面显示所选 Agent Publication 允许的代码注册 MCP Tool
- **AND** 不提供自由文本 URL、SQL、Redis、Loki、Server 或工具名输入框

#### Scenario: 查看Channel和Delivery引用
- **WHEN** 页面展示需要凭据的 connector
- **THEN** 只显示 connector 名称、ID、方向和配置状态
- **AND** 不显示 Secret URI 解析结果、Token、密码或完整 Webhook URL

### Requirement: 系统持久化稳定的业务应用聚合
系统 SHALL 为每个 Business Application 持久化唯一编码、名称、描述、项目范围、负责人、生命周期状态和当前修订信息，并 MUST 将业务应用作为 Agent Publication、Workflow Publication、Trigger、Delivery、会话与执行策略、文档处理配置以及 MCP Tool 子集的装配边界。

#### Scenario: 创建业务应用
- **WHEN** 有创建权限的内部用户提交合法且未被占用的应用编码、名称和项目范围
- **THEN** 系统创建稳定的业务应用定义和初始草稿修订
- **AND** 创建操作不会启动 Agent Job 或修改任何入口路由

#### Scenario: 重复应用编码
- **WHEN** 用户创建的应用编码已经存在
- **THEN** 系统拒绝创建并返回可识别的冲突错误
- **AND** 已存在应用及其草稿保持不变

### Requirement: 业务应用通过草稿修订装配版本化组件
系统 SHALL 使用草稿修订保存一个 Agent Publication、零个或一个 Workflow Publication、任务工作区与文档处理配置、Trigger Binding、Delivery Binding、会话策略、执行策略和 Agent Publication Envelope 内的 MCP Tool 子集，并 MUST NOT 直接引用可变的 Agent 或 Workflow 草稿。草稿请求 MUST 拒绝未知字段以及旧 API Capability、Handler、Connection 或 Resource Mapping 引用。

#### Scenario: 保存完整应用草稿
- **WHEN** 用户为业务应用选择已发布 Agent、已发布 Workflow、合法 Trigger、Delivery、MCP Tool 子集并保存策略
- **THEN** 系统创建新的应用草稿 revision 并保存各组件的稳定引用
- **AND** 先前 revision 的内容保持不变

#### Scenario: 尝试引用组件草稿
- **WHEN** 用户提交 Agent Revision 或 Workflow 草稿而不是 Publication
- **THEN** 系统拒绝该引用并返回对应字段错误

#### Scenario: 提交旧平台对象字段
- **WHEN** 旧客户端提交 API Capability、Handler、Connection、Resource Mapping 或任意实现字段
- **THEN** 严格请求 schema 拒绝该字段且不保存草稿

### Requirement: 第一阶段运行时只接管受支持的钉钉Trigger
系统 MUST 只将 `dingtalk_private + CURRENT_SENDER` 和 `dingtalk_group + CURRENT_SENDER` 标记为当前可执行 Trigger，并 SHALL 将 Webhook 和未执行的 Workflow 路径明确标记为 `stored_only` 或 `unsupported`。MCP Tool 可用性 MUST 由已发布 Agent/Application 交集和当前授权独立判断，不得沿用旧 API Capability 目录状态。

#### Scenario: 评估钉钉私聊应用
- **WHEN** Publication 包含合法 `dingtalk_private` Trigger 和当前发送人 actor policy
- **THEN** 运行时就绪评估器按钉钉私聊支持矩阵校验该 Trigger

#### Scenario: 评估Webhook Trigger
- **WHEN** Publication 包含 Webhook Trigger
- **THEN** Business Application Resolver 不接管该 Webhook
- **AND** 管理端状态明确为 `stored_only` 而不是已生效

#### Scenario: Publication包含未授权MCP Tool
- **WHEN** 应用选择的 MCP Tool 不在 Agent Publication Envelope 或当前业务授权内
- **THEN** 发布或执行校验失败关闭
- **AND** 系统不得将其映射为任意数据库、Redis、Loki 或动态内部工具

## REMOVED Requirements

### Requirement: 迁移必须删除不兼容旧Job及关联运行数据
**Reason**: 当前 migration、运维命令和运行服务没有该破坏性删除流程；继续作为 canonical 正向合同会误报现有能力并鼓励无依据删除历史事实。

**Migration**: 不执行数据迁移。历史提案保留在 archive；当前 Job、Session、消息、工具调用、Delivery 和审计事实继续按各自生命周期保存。

## RENAMED Requirements

- FROM: `Capability和数据源安全边界在真实页面中保持有效`
- TO: `MCP Tool和数据源安全边界在真实页面中保持有效`
- FROM: `本变更不得实现retention清理`
- TO: `retention_days当前仅保存且不执行自动清理`
