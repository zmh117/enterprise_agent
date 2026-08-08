## ADDED Requirements

### Requirement: 系统持久化稳定的业务应用聚合
系统 SHALL 为每个 Business Application 持久化唯一编码、名称、描述、项目范围、负责人、生命周期状态和当前修订信息，并 MUST 将业务应用作为 Agent、Workflow、Channel 和未来 API Capability 的装配边界。

#### Scenario: 创建业务应用
- **WHEN** 有创建权限的内部用户提交合法且未被占用的应用编码、名称和项目范围
- **THEN** 系统创建稳定的业务应用定义和初始草稿修订
- **AND** 创建操作不会启动 Agent Job 或修改任何入口路由

#### Scenario: 重复应用编码
- **WHEN** 用户创建的应用编码已经存在
- **THEN** 系统拒绝创建并返回可识别的冲突错误
- **AND** 已存在应用及其草稿保持不变

### Requirement: 业务应用通过草稿修订装配版本化组件
系统 SHALL 使用草稿修订保存一个 Agent Publication、零个或一个 Workflow Publication、Trigger Binding、Delivery Binding、会话策略、执行策略和 API Capability 引用，并 MUST NOT 直接引用可变的 Agent 或 Workflow 草稿。

#### Scenario: 保存完整应用草稿
- **WHEN** 用户为业务应用选择已发布 Agent、已发布 Workflow、合法 Trigger 和 Delivery，并保存策略
- **THEN** 系统创建新的应用草稿 revision 并保存各组件的稳定引用
- **AND** 先前 revision 的内容保持不变

#### Scenario: 尝试引用组件草稿
- **WHEN** 用户提交 Agent Revision 或 Workflow 草稿而不是 Publication
- **THEN** 系统拒绝该引用并返回对应字段错误

#### Scenario: Capability目录尚未接入
- **WHEN** 应用草稿包含非空 API Capability 编码而当前没有可解析的 Capability Catalog
- **THEN** 系统可以保存该草稿引用用于后续补全
- **AND** 系统 MUST 在发布校验中将其标记为未解析并阻止发布

### Requirement: 应用策略采用严格的受控结构
系统 SHALL 对 Trigger、Actor、Session、Execution 和 Delivery 策略执行严格 schema 校验，MUST 拒绝未知字段、未知枚举、越界限制、任意 URL、底层查询语言和敏感凭据。

#### Scenario: 保存钉钉当前发送人策略
- **WHEN** 钉钉 Trigger 使用 `CURRENT_SENDER` actor policy 并引用允许入口的 connector
- **THEN** 系统接受该受控策略并保存非敏感 connector 与路由标识

#### Scenario: 保存Webhook服务身份策略
- **WHEN** Webhook Trigger 使用 `SERVICE_ACCOUNT` actor policy
- **THEN** 系统要求引用一个已启用的内部服务主体
- **AND** 不允许在策略中直接提交外部系统用户名、密码或 Token

#### Scenario: 提交不安全配置
- **WHEN** 草稿包含数据库连接、Redis地址、Loki地址、SQL、LogQL、Shell、任意HTTP URL、Password、Secret或Token字段
- **THEN** 系统拒绝保存并返回安全的字段级校验错误
- **AND** 错误、日志和审计中不回显敏感值

### Requirement: 应用写入使用乐观并发控制
系统 MUST 要求应用元数据和草稿写请求携带预期 revision，并 SHALL 在预期 revision 与当前值不一致时拒绝覆盖。

#### Scenario: 更新最新草稿
- **WHEN** 用户提交的 expected revision 等于当前应用 revision
- **THEN** 系统原子创建下一草稿 revision 并返回新的 revision

#### Scenario: 两个管理员并发编辑
- **WHEN** 第二个管理员基于已经过期的 revision 保存应用
- **THEN** 系统返回冲突错误并包含当前 revision 的非敏感摘要
- **AND** 不覆盖第一个管理员已经保存的修改

### Requirement: 应用生命周期不删除历史事实
系统 SHALL 支持 enabled、disabled 和 archived 生命周期状态，MUST 保留草稿、发布快照、部署和审计历史，并 MUST 阻止 disabled 或 archived 应用的新发布和激活。

#### Scenario: 停用业务应用
- **WHEN** 有管理权限的用户将应用从 enabled 改为 disabled
- **THEN** 系统保留全部历史数据并拒绝后续发布或激活
- **AND** 已有环境 deployment 必须由显式停用操作处理，不进行隐式数据删除

#### Scenario: 归档业务应用
- **WHEN** 用户归档一个不存在活动 deployment 的业务应用
- **THEN** 系统将应用标记为 archived 并从默认可编辑列表中隐藏
- **AND** 历史查询仍可读取其 publication 和 audit

### Requirement: 控制面变更不自动改变现有数据面
系统 MUST 将业务应用草稿、发布和激活作为控制面配置管理，第一版 MUST NOT 自动修改钉钉入口、Webhook入口、Agent Job创建、RabbitMQ消费或Delivery路径。

#### Scenario: 发布并激活应用
- **WHEN** 管理员发布业务应用并在测试环境激活
- **THEN** 系统更新业务应用控制面数据和解析读模型
- **AND** 现有钉钉和Webhook消息仍沿用原默认Agent执行链路

#### Scenario: 查询应用运行时接线状态
- **WHEN** 管理端读取应用详情或激活结果
- **THEN** 响应明确返回当前 `runtime_wired=false` 或等效状态
- **AND** 不暗示该应用已经接管生产入口
