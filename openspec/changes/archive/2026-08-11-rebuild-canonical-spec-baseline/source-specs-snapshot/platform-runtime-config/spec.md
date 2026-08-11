# platform-runtime-config Specification

## Purpose
TBD - created by archiving change web-managed-secrets-and-env-config. Update Purpose after archive.
## Requirements
### Requirement: Runtime settings are persisted as typed configuration
系统 SHALL 将可 Web 配置的运行参数以 typed key 形式持久化到 PostgreSQL，而不是保存整份 `.env` 文本。

#### Scenario: Save boolean runtime flag
- **WHEN** 管理端配置 `FEATURE_REAL_CLAUDE=true`
- **THEN** 系统以 boolean 类型保存该 key，并在运行时配置快照中返回类型和值

#### Scenario: Reject invalid typed value
- **WHEN** 管理端把 `AGENT_MAX_TURNS` 配置为非整数值
- **THEN** 系统拒绝保存并返回配置校验错误

### Requirement: Runtime settings support service and business scopes
系统 SHALL 支持按 global、service、project、environment、base、workshop、connector 等作用域保存 runtime config，并按确定性优先级合并。

#### Scenario: Service override wins over global
- **WHEN** global 配置 `AGENT_MAX_TURNS=8` 且 `agent-worker` service 配置 `AGENT_MAX_TURNS=12`
- **THEN** agent-worker 运行时配置使用 `12`

#### Scenario: Workshop scoped default is selected
- **WHEN** 钉钉消息映射到 `sanjiu/guanlan/GL001` 且存在 workshop-scoped 默认服务配置
- **THEN** 创建 Agent job 时使用该 scoped 默认值

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

### Requirement: Runtime config changes are versioned and auditable
系统 SHALL 为 runtime config 的新增、修改、禁用、发布或回滚记录版本和审计。

#### Scenario: Update runtime config
- **WHEN** 管理端修改 `ANTHROPIC_MODEL`
- **THEN** 系统增加配置 revision，记录修改前后摘要和 actor

#### Scenario: Disable runtime config
- **WHEN** 管理端禁用一个 service-scoped config
- **THEN** 后续 effective snapshot 不再包含该 override，并回退到下一优先级配置

### Requirement: Runtime config overlay shall be smoke-verifiable after service restart
系统 SHALL 支持在 Docker Compose 环境中通过 curl 写入 DB-backed runtime config，并在重启服务后通过 `/api/ready` 证明 overlay 已生效。

#### Scenario: Compose smoke writes runtime config
- **WHEN** 开发者通过 `/api/platform/runtime-config/values` 写入 `ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`ANTHROPIC_API_KEY` 和 `AGENT_MAX_TURNS`
- **THEN** runtime config snapshot SHALL 显示这些 key 的 effective source 来自数据库，并对敏感 key 只显示 `secret_ref` 和 configured 状态

#### Scenario: Compose smoke restarts services
- **WHEN** 开发者写入 runtime config 后重启 `api-server` 和 `agent-worker`
- **THEN** `/api/ready` SHALL 报告 DB-backed runtime config source/revision/hash，且不得泄漏敏感值

### Requirement: Runtime config smoke shall document degraded fallback
系统 SHALL 在 smoke 文档中说明 runtime config 加载失败、DB 不可用、secret 缺失或类型错误时的 degraded 表现和排查命令。

#### Scenario: Secret-backed config is missing
- **WHEN** runtime config 指向不存在或禁用的 `secret://platform/<code>`
- **THEN** ready/debug 输出 SHALL 标记 degraded 或安全配置错误，并且文档 SHALL 指引开发者检查 secret 状态和 runtime config snapshot

### Requirement: 工具资源运行时只能消费 PostgreSQL 已发布版本
DB、Redis、Loki runtime MUST 只从 PostgreSQL Published Resource Revision 和应用发布 binding 构建快照；YAML、环境变量或代码默认值不得在数据库版本无效时成为资源回退。

#### Scenario: 数据库存在有效发布版本
- **WHEN** Internal API Platform 构建工具资源快照
- **THEN** 它只消费已发布 revision、具体 binding 和 `secret://platform/` 引用

#### Scenario: 发布版本无效但 YAML 可用
- **WHEN** 数据库 revision 无法装载且部署中仍有旧 YAML
- **THEN** 运行时必须保持 Last Known Good 或阻止相关应用，不得使用 YAML 替代

### Requirement: YAML 和 env 只能参与 bootstrap 或显式 import
系统 SHALL 允许部署必需的 bootstrap 配置继续来自 env/文件，并允许显式导入旧资源配置；导入后必须经过 Draft、验证和发布流程。

#### Scenario: 导入旧 env Secret
- **WHEN** 管理员显式执行旧资源迁移
- **THEN** env 值只读取一次并转换为平台 Secret，运行时资源不再直接引用 env

### Requirement: 资源快照必须支持无锁读取和原子 generation 切换
运行时 MUST 为每个请求捕获单个不可变 effective generation；热加载不得让同一请求混用两个 Resource Revision。

#### Scenario: 请求执行期间发生热加载
- **WHEN** 新 generation 在一个工具请求执行中完成激活
- **THEN** 当前请求继续使用启动时捕获的 generation，后续请求使用新 generation

