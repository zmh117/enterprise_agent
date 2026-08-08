## MODIFIED Requirements

### Requirement: Runtime config has explicit bootstrap boundary
系统 SHALL 明确区分 bootstrap-only 配置、deployment safety gate、governed runtime policy 和 test-only 配置。bootstrap-only 配置 MUST NOT 依赖数据库读取；数据库运行配置 MUST NOT 越过部署环境中关闭的数据面安全闸门。

#### Scenario: Database DSN remains bootstrap
- **WHEN** 服务启动
- **THEN** `DATABASE_DSN` 仍从 env 或部署平台读取，用于连接配置数据库

#### Scenario: Queue and master key remain bootstrap
- **WHEN** 服务在读取数据库运行配置前启动
- **THEN** `RABBITMQ_URL` 和 `APP_CONFIG_MASTER_KEY` 从部署环境或受控 Secret 注入获得
- **AND** 系统不尝试从数据库运行配置中自举这些值

#### Scenario: DB runtime config unavailable
- **WHEN** PostgreSQL 不可达或 runtime config snapshot 加载失败
- **THEN** 系统使用代码安全默认值、部署安全闸门和最后一个已验证发布快照
- **AND** 系统不得因回退而扩大权限或开启真实模型、真实工具或已发布 Runtime
- **AND** ready/health 输出标记配置 degraded 或 failed

#### Scenario: Runtime policy requests a disabled deployment capability
- **WHEN** 数据库运行策略请求启用被部署安全闸门关闭的能力
- **THEN** 有效值保持关闭并记录阻断来源

### Requirement: Runtime config snapshot is observable
系统 SHALL 提供只读 runtime config snapshot，展示当前有效值、配置分类、来源、revision/hash、适用服务、弃用输入、是否需要重启和错误摘要，不泄漏 Secret 明文或完整连接信息。

#### Scenario: Query runtime config snapshot
- **WHEN** 管理端或调试工具查询 runtime config snapshot
- **THEN** 系统返回 effective keys、effective values、classification、source、revision/hash、deprecated inputs 和 diagnostics

#### Scenario: Secret-backed setting is shown
- **WHEN** `ANTHROPIC_API_KEY` 由 `secret://platform/deepseek_api_key` 提供
- **THEN** snapshot 只显示 secret ref 和 configured 状态，不显示 API key

#### Scenario: Deployment gate blocks runtime policy
- **WHEN** 已发布运行策略请求启用真实工具但 deployment safety gate 为关闭
- **THEN** snapshot 同时显示策略请求值、最终关闭值和阻断原因

#### Scenario: Management plane is disabled
- **WHEN** `FEATURE_WEB_ADMIN=false`
- **THEN** 公开健康检查只返回总体配置状态和机器可读错误代码
- **AND** 详细配置快照不通过未认证管理接口暴露
