## ADDED Requirements

### Requirement: 测试数据 profile 不得隐式发布工具资源
`agent-test-data` profile SHALL 只提供确定性的 MySQL、SQL Server 和各自 Redis 数据服务及播种能力；它 MUST NOT 通过已删除的 YAML runtime topology 隐式创建或绑定工具资源。需要执行真实 Tool Call 时，验收流程 MUST 通过受治理的资源管理或显式 bootstrap 创建、验证并发布对应 Resource Revision。

#### Scenario: 仅启动测试数据 profile
- **WHEN** 操作者启动并播种 `agent-test-data` profile
- **THEN** 四个测试数据服务可验证，但平台不会因此自动出现可调用 Published Resource Revision

#### Scenario: 执行真实测试工具调用
- **WHEN** 验收需要查询 `agent_test/mysql` 或 `agent_test/sqlserver`
- **THEN** 流程先创建使用 Secret reference 和只读账户的 Published Resource Revision，再由 `tool-mcp` 按目标唯一解析

### Requirement: 普通部署只暴露三个顶层功能开关
系统 SHALL 将 `FEATURE_WEB_ADMIN`、`FEATURE_PUBLISHED_AGENT_RUNTIME` 和 `FEATURE_REAL_CLAUDE` 作为普通部署模板中的顶层 `FEATURE_*` 配置。标准 `tool-mcp` 是否可执行由固定服务部署、Agent/Application Tool 子集、当前授权和 Published Resource Revision 共同决定，不得恢复独立真实工具开关。

#### Scenario: 查看普通部署模板
- **WHEN** 部署人员查看 `.env.example`、Compose 示例或普通部署文档
- **THEN** 系统只将三个顶层功能开关列为需要决策的 `FEATURE_*` 配置

#### Scenario: 开启管理后台
- **WHEN** `FEATURE_WEB_ADMIN=true`
- **THEN** 系统同时启用管理 Web、统一身份、Web Session、RBAC 和业务应用控制面
- **AND** 系统不自动开启已发布 Agent Runtime 或真实模型

#### Scenario: 关闭管理后台
- **WHEN** `FEATURE_WEB_ADMIN=false`
- **THEN** 系统不暴露管理 Web 和管理 API
- **AND** 已发布 Channel 和 Agent Runtime 仍仅由各自的数据面闸门与发布配置决定

## MODIFIED Requirements

### Requirement: 环境变量模板覆盖运行与播种凭据
`.env.example` SHALL 声明测试镜像、宿主端口、数据库初始化凭据、只读运行凭据、两个 Redis 的只读凭据及播种凭据，并使用明显的本地占位值；本地 `.env` MAY 提供可运行配置。Compose SHALL 只向播种服务传递管理/播种凭据；`tool-mcp` MUST 通过 Published Resource Revision 的 `secret://platform/<code>` 在基础设施适配器内解析只读凭据，不得直接接收测试数据库管理凭据。

#### Scenario: tool-mcp 连接测试基地
- **WHEN** `tool-mcp` 为 `agent_test/mysql` 或 `agent_test/sqlserver` 解析唯一 Published Resource Revision
- **THEN** 它只在对应资源适配器内获得该数据源的只读数据库或 Redis 凭据
- **THEN** 数据库管理凭据与 Redis 播种用户凭据不出现在 Runtime、Worker 或 MCP Tool 参数中

#### Scenario: 示例配置可安全提交
- **WHEN** `.env.example` 被提交到版本库
- **THEN** 其中只包含本地开发占位值和说明
- **THEN** 不包含任何生产连接信息或真实密钥

### Requirement: 数据面安全闸门保持独立
系统 MUST 独立解析 `FEATURE_PUBLISHED_AGENT_RUNTIME` 和 `FEATURE_REAL_CLAUDE`，任何管理面开关、旧兼容开关或数据库策略均不得将部署环境中关闭的闸门变为开启。标准 `tool-mcp` 不使用独立功能开关，必须同时通过 Job 状态、Tool publication 子集、当前授权、唯一资源解析和只读策略。

#### Scenario: 管理后台开启但数据面能力关闭
- **WHEN** `FEATURE_WEB_ADMIN=true` 且 `FEATURE_PUBLISHED_AGENT_RUNTIME=false`、`FEATURE_REAL_CLAUDE=false`
- **THEN** 管理员可以配置和发布资源
- **AND** 系统不执行已发布 Agent 或调用真实模型

#### Scenario: 未授权调用真实工具
- **WHEN** 请求缺少有效 RUNNING Job、发布 Tool 子集、当前 Tool grant、数据范围或唯一 Published Resource Revision
- **THEN** `tool-mcp` 失败关闭且不访问上游资源

### Requirement: Registry exposes stable runtime revision
系统 SHALL 为 Environment/Base/Workshop topology、Resource Identity 和 Resource Revision 暴露规范化 revision 或 content hash，用于审计管理变更和证明每次 Tool Call 的实际资源事实。Resource Revision 的 content hash MUST 同时覆盖 Provider 连接配置、Secret references 和数据范围 bindings；系统 MUST NOT 生成 Application Resource Mapping、独立范围 Policy Revision、activation generation 或 Job-frozen Resource Revision。

#### Scenario: Configuration changes revision
- **WHEN** Environment/Base/Workshop 或 Resource 发布新的不可变 revision
- **THEN** 对应 revision/hash 发生变化，既有 Published Revision 内容保持不变

#### Scenario: Tool Call reports revision
- **WHEN** `tool-mcp` 为一次调用解析唯一 Published Resource Revision
- **THEN** Tool Call 与 MCP Operation Audit 包含 Tool identifier/schema hash、Resource ID/revision/content hash 和实际 placement 的安全摘要

#### Scenario: Resource draft changes only
- **WHEN** 管理员修改尚未发布的 Resource Draft
- **THEN** 既有 Published Revision 与当前 Tool Call 解析结果不发生变化

#### Scenario: Resource scope binding changes
- **WHEN** 管理员修改 Draft 中的 DB table prefix、Redis namespace 或 Loki selector conditions
- **THEN** 同一个 Draft revision 和 content hash 变化，旧技术验证失效且 Published Revision 保持不变

### Requirement: 工具资源运行时只能消费 PostgreSQL 已发布版本
DB、Redis、Loki runtime MUST 只消费 PostgreSQL 中启用 Resource Identity 的 Published Resource Revision；YAML、环境变量、Application Resource Mapping 或代码默认连接不得在数据库资源无效时成为回退。

#### Scenario: 数据库存在唯一有效发布版本
- **WHEN** `tool-mcp` 按资源类型、业务目标和可选 placement 解析一次 Tool Call
- **THEN** 它只消费唯一 Published Revision 及其 `secret://platform/` 引用，并记录实际版本

#### Scenario: 发布版本无效但旧 YAML 可用
- **WHEN** Published Revision 无法解析且部署目录仍残留旧 YAML
- **THEN** Tool Call 必须失败关闭，不得读取 YAML、旧 Revision 或第一候选

### Requirement: 只有一次性 Migrator 可以修改平台 schema
系统 MUST 由独立 one-shot Migrator 应用 schema migration；API、Worker、Dispatcher、Agent Runtime、`tool-mcp`、ONES MCP 和 File Service MUST NOT 在自身启动或请求处理中执行 migration。

#### Scenario: Compose 启动平台
- **WHEN** Docker Compose 启动新版本平台
- **THEN** Migrator 必须先成功退出，依赖 schema 的业务服务随后才可启动

#### Scenario: 业务服务直接启动
- **WHEN** 任一业务服务启动且数据库 schema 未达到代码要求的 head
- **THEN** 服务必须启动失败并返回不含敏感信息的版本差异

### Requirement: Real model safety mode shall be visible in documentation
系统 SHALL 在 README 或测试文档中明确说明 `FEATURE_REAL_CLAUDE=true` 与 DeepSeek/Claude API 环境变量的风险边界和推荐测试数据策略。

#### Scenario: 开发者启用真实模型
- **WHEN** 开发者准备设置 `FEATURE_REAL_CLAUDE=true`
- **THEN** 文档 SHALL 提醒该模式会调用外部模型 API，并要求使用合成或脱敏数据

#### Scenario: 只验证工具链
- **WHEN** 开发者只需要验证 `python-agent-runtime -> tool-mcp -> Published Resource Revision` 链路
- **THEN** 文档 SHALL 提供不调用真实外部模型的受控测试路径

### Requirement: Registry must separate Resource Identity, Draft, verification and Revision state
Registry MUST 分别持久化 Resource Identity、Resource Draft、Verification Evidence 和不可变 Published Resource Revision；连接与数据范围属于同一 Draft/Revision，运行 Tool Call 的当前解析与健康事实不得覆盖任一治理状态。

#### Scenario: Published resource call fails
- **WHEN** Resource Revision 已发布但当前 Secret、驱动或上游连接失败
- **THEN** Registry 保留 Published Revision，并通过验证摘要或最近 Tool Call 安全错误展示运行事实，不创建 Effective generation 或 Last Known Good

#### Scenario: Resource data scope changes after verification
- **WHEN** Resource Draft 的连接配置、Secret reference 或 `scope_bindings` 变化
- **THEN** 旧 Verification Evidence 失效，但上一 Published Revision 保持不变

### Requirement: Resource Identity 与 Resource Revision 生命周期必须独立管理
系统 SHALL 分别管理稳定 Resource Identity 的 `enabled`、`disabled`、`archived` 状态和不可变 Resource Revision 的 `PUBLISHED`、`DISABLED`、`ARCHIVED` 状态；Revision 生命周期动作 MUST NOT 隐式改写 Identity，管理 API 和界面 MUST 分开展示并筛选两层状态。

#### Scenario: 归档最新 Resource Revision
- **WHEN** 管理员把一个 Loki Resource 的最新 Revision 从 DISABLED 归档
- **THEN** 该 Revision 变为 ARCHIVED，Resource Identity 保持 enabled，并仍可显式从该历史 Revision 复制新 Draft

#### Scenario: 停用 Resource Identity
- **WHEN** 管理员使用当前 Identity revision 显式停用一个 enabled Resource Identity
- **THEN** Identity 变为 disabled，后续创建、保存、验证和发布 Draft 均被阻止，既有 Resource Revision 和历史 Tool Call 不被改写，新的资源调用不能再解析该 Identity

#### Scenario: 恢复 Resource Identity
- **WHEN** 管理员使用当前 Identity revision 显式恢复一个 disabled Resource Identity
- **THEN** Identity 变为 enabled 并允许后续 Draft 管理，历史 Revision 状态保持不变

#### Scenario: 安全归档 Resource Identity
- **WHEN** disabled Identity 没有活动 Draft 且没有 PUBLISHED Revision
- **THEN** 管理员可以用当前 Identity revision 把它归档为不可恢复终态并记录审计

#### Scenario: Identity 仍有治理依赖
- **WHEN** 管理员尝试归档仍有活动 Draft 或 PUBLISHED Revision 的 Identity
- **THEN** 系统失败关闭并返回不含 Secret 的依赖摘要，不改变 Identity 或任何 Revision

#### Scenario: Identity 并发状态已变化
- **WHEN** 生命周期请求携带的 expected Identity revision 已过期
- **THEN** 系统以并发冲突拒绝请求，要求刷新后重试

### Requirement: Registry must enforce optional placement representation
Registry SHALL 只在 Resource Identity 实际存在物理位置差异时保存 `cloud` 或 `edge` placement；无 placement 的 Resource address MUST 保存为缺省值而非字符串占位，并且单个 Resource Identity 不得同时包含多个 placement。

#### Scenario: Save non-placement resource
- **WHEN** 管理端保存一个没有云边差异的 Redis Resource Identity
- **THEN** Registry 持久化缺省 placement 并拒绝 `none`、`standalone` 或 `default`

#### Scenario: Save one placement value
- **WHEN** 管理端保存 edge Resource Identity
- **THEN** Registry 只保存枚举值 `edge`，不把它写入 Environment/Base/Workshop code

## REMOVED Requirements

### Requirement: 拓扑定义两个数据库基地及各自 Redis
**Reason**: 该 Requirement 依赖已删除的 `backend/config/internal_platform_topology.example.yaml` 和 YAML runtime topology。
**Migration**: 测试数据 profile 只提供数据源；真实 Tool Call 通过显式创建并发布的受治理 Resource Revision 接入。

### Requirement: 普通部署只暴露四个顶层功能开关
**Reason**: `FEATURE_REAL_INTERNAL_TOOLS` 已永久删除，当前模板只有三个顶层功能开关。
**Migration**: 使用新增的 `普通部署只暴露三个顶层功能开关`。

### Requirement: Resource bindings are persisted by scope
**Reason**: Application Resource Mapping、slot 和 Job-frozen Resource Revision 已删除。
**Migration**: Resource Identity 自身保存 environment/base/workshop/placement 地址，`tool-mcp` 每次调用唯一解析当前 Published Revision。

### Requirement: 资源快照必须支持无锁读取和原子 generation 切换
**Reason**: 旧 effective generation/activation runtime 已删除。
**Migration**: 每次 Tool Call 从单个 Published Resource Revision 和 Secret 版本构造一致连接事实；失败时不回退。
