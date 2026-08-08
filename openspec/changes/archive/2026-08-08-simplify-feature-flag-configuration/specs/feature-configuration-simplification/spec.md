## ADDED Requirements

### Requirement: 普通部署只暴露四个顶层功能开关
系统 SHALL 将 `FEATURE_WEB_ADMIN`、`FEATURE_PUBLISHED_AGENT_RUNTIME`、`FEATURE_REAL_CLAUDE` 和 `FEATURE_REAL_INTERNAL_TOOLS` 作为普通部署模板中唯一的顶层 `FEATURE_*` 配置。数据库、RabbitMQ、主加密密钥等 bootstrap 配置不属于该数量限制。

#### Scenario: 查看普通部署模板
- **WHEN** 部署人员查看 `.env.example`、Compose 示例或普通部署文档
- **THEN** 系统只将四个顶层功能开关列为需要决策的 `FEATURE_*` 配置

#### Scenario: 开启管理后台
- **WHEN** `FEATURE_WEB_ADMIN=true`
- **THEN** 系统同时启用管理 Web、统一身份、Web Session、RBAC 和业务应用控制面
- **AND** 系统不自动开启已发布 Agent Runtime、真实模型或真实内部工具

#### Scenario: 关闭管理后台
- **WHEN** `FEATURE_WEB_ADMIN=false`
- **THEN** 系统不暴露管理 Web 和管理 API
- **AND** 已发布 Channel 和 Agent Runtime 仍仅由各自的数据面闸门与发布配置决定

### Requirement: 数据面安全闸门保持独立
系统 MUST 独立解析 `FEATURE_PUBLISHED_AGENT_RUNTIME`、`FEATURE_REAL_CLAUDE` 和 `FEATURE_REAL_INTERNAL_TOOLS`，任何管理面开关、旧兼容开关或数据库策略均不得将部署环境中关闭的闸门变为开启。

#### Scenario: 管理后台开启但真实能力关闭
- **WHEN** `FEATURE_WEB_ADMIN=true` 且三个数据面安全闸门均为 `false`
- **THEN** 管理员可以配置和发布资源
- **AND** 系统不执行已发布 Agent、不调用真实模型且不调用真实内部工具

#### Scenario: 数据库策略尝试越过部署闸门
- **WHEN** 部署环境将 `FEATURE_REAL_INTERNAL_TOOLS=false` 且运行策略请求启用真实工具
- **THEN** 有效配置保持真实工具关闭
- **AND** 诊断结果标记该运行策略被部署闸门阻断

### Requirement: 所有组件使用统一有效功能配置
系统 SHALL 通过单一解析器生成不可变的有效功能配置，API、Worker、Bootstrap wiring 和健康诊断 MUST 使用该解析结果，不得自行解释环境变量默认值或优先级。

#### Scenario: 相同输入被不同服务解析
- **WHEN** API 与 Worker 使用相同部署环境和相同发布配置启动
- **THEN** 两者得到相同的有效功能值、来源和诊断结果

#### Scenario: 数据库运行配置不可用
- **WHEN** 运行策略存储不可达且没有可用的最后发布快照
- **THEN** 系统采用不会扩大权限或开启外部调用的安全默认值
- **AND** readiness 标记为 degraded 或 failed，并给出机器可读错误代码

### Requirement: 旧功能开关具有受限兼容期
系统 SHALL 在一个明确发布版本内识别被替代的旧功能开关，输出去敏弃用告警，并在兼容期结束后删除其直接部署入口。兼容适配 MUST NOT 扩大权限、开启外部调用或自动发布领域配置。

#### Scenario: 只配置无冲突旧开关
- **WHEN** 部署仅包含仍在兼容期内的旧功能开关
- **THEN** 系统按记录的旧行为生成兼容配置
- **AND** 系统输出旧键、迁移目标和移除版本，不输出敏感值

#### Scenario: 新旧配置冲突
- **WHEN** 新顶层开关或已发布领域策略与旧功能开关表达互相矛盾的结果
- **THEN** 系统拒绝启动或拒绝发布
- **AND** 错误明确列出冲突键及迁移目标，不静默选择任一方

#### Scenario: 兼容适配涉及数据面
- **WHEN** 任一旧开关被解析
- **THEN** 适配器不得把三个数据面安全闸门从关闭变为开启

### Requirement: 测试身份能力不得进入生产
系统 MUST 将测试身份请求头能力分类为 test-only。生产环境中不得通过环境变量、数据库配置或请求内容启用该能力。

#### Scenario: 生产环境误开测试身份请求头
- **WHEN** 生产环境配置 `FEATURE_TEST_IDENTITY_HEADERS=true`
- **THEN** 系统拒绝启动并报告 test-only 配置违规

#### Scenario: 测试环境显式启用
- **WHEN** 测试环境显式启用测试身份请求头且测试配置允许
- **THEN** 系统允许该测试适配器工作并在诊断快照中标记为 test-only

### Requirement: 细粒度功能由已发布领域策略控制
系统 SHALL 使用受版本和审计保护的领域配置控制 Webhook 接入、连续会话、附件处理和权限迁移，不得继续以普通部署模板中的全局开关作为其长期事实源。

#### Scenario: 草稿策略被编辑
- **WHEN** 管理员编辑 Connector/Trigger、上下文或附件策略草稿但尚未发布
- **THEN** 运行中行为保持使用上一已发布版本

#### Scenario: 领域策略被发布
- **WHEN** 管理员发布经过校验的领域策略
- **THEN** 后续运行使用新 revision
- **AND** 系统记录 actor、前后版本和发布时间

#### Scenario: 执行配置迁移
- **WHEN** 迁移工具根据旧全局开关生成领域配置
- **THEN** 生成结果保持为待确认草稿
- **AND** 迁移工具不得自动发布、修改消息路由或开启外部调用
