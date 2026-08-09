## MODIFIED Requirements

### Requirement: 系统持久化稳定的业务应用聚合
系统 SHALL 持久化多个 Business Application，每个应用具有唯一 code、名称、说明、项目范围、负责人、生命周期状态、revision 和当前环境 Deployment，并 MUST 将应用作为 Agent Publication、MCP Tool Publication、Resource Deployment、Channel、Trigger、Session、Execution 与 Delivery 的装配边界。

#### Scenario: 创建业务应用
- **WHEN** 有权限用户提交唯一 code、合法名称和项目范围
- **THEN** 系统创建稳定 Application 与初始 Draft，不启动 Job、不发布 Tool且不改变入口路由

#### Scenario: 创建多个应用
- **WHEN** 同一项目创建两个使用不同 Agent 或 MCP Tool 子集的应用
- **THEN** 两个聚合具有独立 Draft、Publication 和环境 Deployment，互不覆盖

#### Scenario: 重复应用编码
- **WHEN** 用户提交已占用 code
- **THEN** 系统拒绝冲突且不修改已有应用

### Requirement: 业务应用通过草稿修订装配版本化组件
系统 SHALL 使用 Draft revision 保存一个 Agent Publication、零个或多个该 Agent 允许的 MCP Tool Publication、对应精确 Resource Deployment、Trigger、Channel、Delivery、Session 和 Execution Policy；系统 MUST NOT 引用 Agent Draft、自由 Tool、Capability、Handler、Connection 或 `latest` Resource。

#### Scenario: 保存完整应用草稿
- **WHEN** 用户选择已发布 Agent、其 Tool 最大集合的合法子集、精确 Resource Deployment 和合法入口/投递策略
- **THEN** 系统创建下一 Draft revision并保存各组件稳定版本引用，旧 revision 保持不变

#### Scenario: 尝试引用组件草稿
- **WHEN** 请求引用 Agent/Tool/Resource Draft 而非 Publication/Deployment
- **THEN** 系统拒绝并返回对应字段错误

#### Scenario: 提交旧 Capability 引用
- **WHEN** 请求包含 Capability、Handler、Connection 或旧 Resource Composition 字段
- **THEN** 系统以已退役契约错误拒绝，不能映射成 MCP Tool

### Requirement: 应用策略采用严格的受控结构
系统 SHALL 对 Agent、MCP Tool、Resource、Trigger、Actor、Session、Execution 和 Delivery 执行严格 schema 与交叉范围校验，并 MUST 拒绝未知字段、越界限制、任意 URL、底层查询语言、自由 Tool 名和敏感凭据。

#### Scenario: 保存钉钉当前发送人策略
- **WHEN** 钉钉 Trigger 使用 `CURRENT_SENDER` 并引用允许入口的 connector
- **THEN** 系统接受非敏感 connector/routing 标识且运行时继续解析统一 `app_user`

#### Scenario: 保存不同 Tool 子集
- **WHEN** 应用选择 Agent Publication 最大集合中的一部分 MCP Tool
- **THEN** Draft 接受精确 Publication 引用且不能扩大 scope 或替换 Schema hash

#### Scenario: 提交不安全配置
- **WHEN** Draft 包含连接地址、SQL、LogQL、Redis 命令、Shell、自由 HTTP、Password、Token、Secret 或认证 Header
- **THEN** 系统拒绝并确保错误、日志和审计不回显敏感值

### Requirement: 应用生命周期不删除历史事实
系统 SHALL 支持 enabled、disabled、archived，MUST 保留 Draft、Publication、Deployment 和审计历史，并 MUST 阻止 disabled/archived 应用的新发布和激活。归档前 MUST 不存在活动 Deployment、未完成 Draft 或受保护运行引用。

#### Scenario: 停用业务应用
- **WHEN** 管理员将 enabled 应用停用
- **THEN** 历史保持不变且后续发布/激活被拒绝，活动 Deployment 必须显式停用

#### Scenario: 归档业务应用
- **WHEN** disabled 应用没有活动 Deployment 和阻塞依赖
- **THEN** 系统归档并从默认列表隐藏，历史仍可查询

### Requirement: 控制面变更不自动改变现有数据面
系统 MUST 将 Draft、校验和 Publication 与环境激活分离；仅创建/发布 MUST NOT 改变入口或新 Job。显式激活合法 Application Publication 后，Resolver SHALL 原子切换该环境路由，后续新 Job 固定新组件；已入队/运行 Job 保持原快照。

#### Scenario: 仅发布应用
- **WHEN** 管理员发布合法 Application revision 但未激活
- **THEN** Publication 出现在历史中，所有环境路由保持原值

#### Scenario: 激活测试环境
- **WHEN** 管理员将合法 Publication 激活到 test
- **THEN** test 新入口按该 Application 创建 Job，production 和已有 Job 不受影响

#### Scenario: 停用环境
- **WHEN** 管理员显式停用 deployment
- **THEN** 新入口不再解析该应用，Publication 历史仍保留
