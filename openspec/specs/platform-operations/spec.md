# platform-operations Specification

## Purpose
定义平台配置、Secret、Migration、Compose、测试环境、运行验收及 canonical 规格读取治理。
## Requirements

<!-- Reconciled from mcp_new capability: `agent-test-data-environment` -->

### Requirement: Compose 按 profile 提供两套独立测试基地
系统 SHALL 在 `agent-test-data` Compose profile 中提供 MySQL、SQL Server 两个数据库服务，并为每个数据库服务提供一一对应且不共享数据卷的 Redis 服务。该 profile 未启用时，四个测试数据服务 SHALL 不启动。

#### Scenario: 启动完整测试数据 profile
- **WHEN** 操作者启用 `agent-test-data` profile
- **THEN** Compose 启动两个数据库服务和两个独立 Redis 服务
- **THEN** MySQL、SQL Server 基地分别只能通过自己的 Redis 服务名和数据卷访问对应缓存

#### Scenario: 默认启动不加载重型测试服务
- **WHEN** 操作者未启用 `agent-test-data` profile 而启动现有 Compose 栈
- **THEN** MySQL、SQL Server 和两个测试 Redis 服务均不启动

### Requirement: 每个数据服务具备就绪检查和持久化边界
每个测试数据库和 Redis 服务 SHALL 具有验证真实可连接性的健康检查、独立命名卷和有界重试时间。播种流程 MUST 等待所有依赖服务健康后再写入数据，不得仅以容器进程已启动作为就绪条件。

#### Scenario: 数据库尚未接受连接
- **WHEN** 数据库容器进程已运行但尚未完成数据库初始化
- **THEN** 该服务保持非健康状态
- **THEN** 播种流程不得尝试写入该数据库

#### Scenario: 重启时保留数据
- **WHEN** 操作者停止并重新启动测试 profile 且未执行重置
- **THEN** 每个数据库和 Redis 从各自命名卷恢复数据
- **THEN** 不得读取其他基地的数据卷

### Requirement: 测试数据 profile 不得隐式发布工具资源
`agent-test-data` profile SHALL 只提供确定性的 MySQL、SQL Server 和各自 Redis 数据服务及播种能力；它 MUST NOT 通过已删除的 YAML runtime topology 隐式创建或绑定工具资源。需要执行真实 Tool Call 时，验收流程 MUST 通过受治理的资源管理或显式 bootstrap 创建、验证并发布对应 Resource Revision。
#### Scenario: 仅启动测试数据 profile
- **WHEN** 操作者启动并播种 `agent-test-data` profile
- **THEN** 四个测试数据服务可验证，但平台不会因此自动出现可调用 Published Resource Revision
#### Scenario: 执行真实测试工具调用
- **WHEN** 验收需要查询 `agent_test/mysql` 或 `agent_test/sqlserver`
- **THEN** 流程先创建使用 Secret reference 和只读账户的 Published Resource Revision，再由 `tool-mcp` 按目标唯一解析

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

### Requirement: 两种数据库包含同构 MES 诊断数据
播种流程 SHALL 在 MySQL 和 SQL Server 中建立语义一致的 MES 测试模型，至少包含生产订单、设备、设备告警、物料库存、质量检验和生产事件。两种方言 SHALL 使用相同的业务标识、字段语义和确定性时间基准，同时允许 DDL 使用各自正确的数据类型和语法。

#### Scenario: Schema 预览可发现同构模型
- **WHEN** 通过 `/tools/schema/directory` 分别预览两个测试基地
- **THEN** 两个结果都包含六类规定的业务表及其核心字段
- **THEN** 结果不依赖随机 ID 或当前系统时间才能对应

#### Scenario: 多方言查询返回可比较结果
- **WHEN** 对两个基地执行语义等价的只读订单与告警查询
- **THEN** 查询返回相同业务标识和可比较的诊断字段
- **THEN** 每个查询仍由现有方言限行和只读策略约束

### Requirement: 每个基地具有确定性数据库与 Redis 异常
每个数据库 SHALL 包含可复现的正常记录和至少一个诊断异常链，包括停滞生产订单、异常设备心跳、未清除高等级告警和库存不足。对应 Redis SHALL 包含设备状态、订单进度和库存缓存，其中至少一组值故意与该基地数据库记录不一致，并通过固定业务标识建立关联。

#### Scenario: Agent 发现订单和设备异常链
- **WHEN** Agent 查询约定的停滞订单、关联设备和未清除告警
- **THEN** 数据库证据足以推导订单停滞与设备异常之间的关系

#### Scenario: Agent 发现缓存不一致
- **WHEN** Agent读取同一基地约定业务标识的数据库状态和 Redis 缓存
- **THEN** 至少一个设备状态、订单进度或库存值存在预先记录的确定性差异
- **THEN** 该差异不得依赖跨基地读取才能发现

### Requirement: 播种流程可重复执行且不依赖空数据卷
系统 SHALL 提供显式播种命令，在已有或全新数据卷上均可执行。播种 SHALL 以固定主键和受控 fixture 命名空间创建或更新结构与数据，清理旧 fixture 后恢复基线，并在任一数据源失败时返回非零状态。播种路径 SHALL 与生产只读网关分离。

#### Scenario: 对已播种环境再次播种
- **WHEN** 操作者连续两次执行播种命令
- **THEN** 第二次成功完成且表行数、Redis key 数和基线值与第一次一致
- **THEN** 不产生重复业务记录

#### Scenario: 单一数据源播种失败
- **WHEN** 任一数据库或 Redis 在播种期间不可连接或脚本执行失败
- **THEN** 播种命令返回非零状态并指出失败的数据源
- **THEN** 环境不得被报告为可供 Agent 测试

### Requirement: 测试数据支持验证和安全重置
系统 SHALL 提供验证命令，检查四个数据源的连接、Schema、记录数量、固定哨兵值、数据库只读用户权限和 Redis 基地隔离。系统 SHALL 提供需显式确认的重置命令，只删除测试 profile 的容器和命名卷，不得删除现有 PostgreSQL、RabbitMQ 或其他项目数据。

#### Scenario: 验证完整测试环境
- **WHEN** 四个数据源健康且基线数据完整
- **THEN** 验证命令返回成功并逐个列出两个数据库及两个 Redis 的检查结果

#### Scenario: 拒绝未确认的破坏性重置
- **WHEN** 操作者执行重置但未提供规定的确认参数
- **THEN** 命令拒绝删除任何数据卷并返回使用说明

#### Scenario: 重置范围保持隔离
- **WHEN** 操作者确认执行测试数据重置
- **THEN** 只移除 agent test data 的四个命名卷及相关容器
- **THEN** 现有 PostgreSQL、RabbitMQ 和非测试 profile 的数据保持不变

### Requirement: ARM64 主机的架构限制必须显式处理
测试环境 SHALL 在启动前识别主机架构。MySQL、Redis SHALL 使用支持 ARM64 的镜像系列；SQL Server 在 ARM64 上 SHALL 显式使用 `linux/amd64` 并输出其模拟运行属于本地测试路径的警告。若 SQL Server 无法通过健康检查，完整环境验证 MUST 失败而不是跳过该基地。

#### Scenario: 在 ARM64 开发机启动
- **WHEN** 操作者在 ARM64 主机启动测试 profile
- **THEN** 原生多架构服务选择 ARM64 镜像变体
- **THEN** SQL Server 以显式 `linux/amd64` 平台启动并显示兼容性警告

#### Scenario: SQL Server 模拟运行失败
- **WHEN** ARM64 主机上的 SQL Server 容器未在有界时间内变为健康
- **THEN** 启动或验证命令返回失败并提示使用 x86-64 Docker 主机
- **THEN** 不得将 MySQL 和 Redis 成功误报为完整环境成功

<!-- Reconciled from mcp_new capability: `compose-infrastructure-major-upgrade` -->

### Requirement: Compose 必须默认运行 PostgreSQL 18 和 RabbitMQ 4
系统 SHALL 将 Compose 默认数据库镜像设为 `postgres:18`，将默认消息代理镜像设为 `rabbitmq:4-management`，并 MUST 保持现有服务名、容器内端口及应用连接契约不变。

#### Scenario: 新环境按默认镜像启动
- **WHEN** 操作人未覆盖基础设施镜像变量并执行 Docker Compose 启动
- **THEN** PostgreSQL 以主版本 18 运行，RabbitMQ 以主版本 4 且启用 Management 插件运行

#### Scenario: 部署锁定已验证镜像
- **WHEN** CI 或生产部署通过环境变量提供具体补丁标签或 digest
- **THEN** Compose 使用覆盖后的镜像且服务配置、端口和依赖关系保持一致

### Requirement: 基础设施数据必须使用显式版本隔离命名卷
系统 SHALL 为 PostgreSQL 18 和 RabbitMQ 4 声明显式命名卷；PostgreSQL 18 卷 MUST 挂载到 `/var/lib/postgresql`，且新主版本卷 MUST 不直接复用 PostgreSQL 16 的物理数据目录。

#### Scenario: PostgreSQL 18 初始化持久化数据
- **WHEN** PostgreSQL 18 在空的新命名卷上首次启动
- **THEN** 数据初始化在 `/var/lib/postgresql/18/docker` 下，并在容器重建后保持可用

#### Scenario: RabbitMQ 4 重建容器
- **WHEN** RabbitMQ 4 容器在不删除命名卷的情况下重建
- **THEN** broker 元数据和已确认需要保留的运行状态仍由同一命名卷提供

### Requirement: PostgreSQL 主版本升级必须使用可验证的逻辑迁移
系统 SHALL 提供 PostgreSQL 16 到 18 的备份、恢复和核验流程，MUST 在新 PostgreSQL 18 数据卷中恢复逻辑备份，并 MUST NOT 使用 PostgreSQL 18 直接启动 PostgreSQL 16 物理数据目录。

#### Scenario: 迁移已有 PostgreSQL 数据
- **WHEN** 当前 PostgreSQL 16 包含 Agent Job、平台配置、审计或 secret 数据
- **THEN** 升级流程先生成可恢复的逻辑备份，再恢复到 PostgreSQL 18 新卷，并比较关键表记录数与配置 revision

#### Scenario: 数据恢复失败
- **WHEN** PostgreSQL 18 恢复或迁移后校验失败
- **THEN** 升级流程中止且保留旧运行环境、旧数据卷和逻辑备份，不执行自动清理

### Requirement: RabbitMQ 4 切换前必须防止静默丢消息
系统 SHALL 在创建新的 RabbitMQ 4 broker 前检查 Agent 正常、重试和死信队列的 ready/unacked 状态，并 MUST 在仍有未处理消息时中止默认切换流程。

#### Scenario: 队列已经排空
- **WHEN** API 入口与 worker 已停止，且所有受管 Agent 队列的 ready/unacked 数量均为零
- **THEN** 操作人可以启动使用新命名卷的 RabbitMQ 4，并由应用重新声明队列拓扑

#### Scenario: 仍有未处理消息
- **WHEN** 任一受管 Agent 队列存在 ready 或 unacked 消息
- **THEN** preflight 返回失败并列出相关队列，且不得自动删除、替换或清空旧 broker 数据

### Requirement: 升级必须提供非破坏性的检查与回滚资料
系统 SHALL 提供中文升级文档和可重复执行的 preflight、backup、restore、verify 操作，所有清理旧卷或备份的动作 MUST 与升级主流程分离并由操作人显式执行。

#### Scenario: 执行升级前检查
- **WHEN** 操作人运行 preflight
- **THEN** 系统报告当前镜像版本/digest、数据库状态、RabbitMQ 队列状态及关键迁移前置条件，并在不满足条件时非零退出

#### Scenario: 升级验收前回滚
- **WHEN** PostgreSQL 18、RabbitMQ 4 或应用闭环验证失败
- **THEN** 操作人可依据文档恢复已记录的旧镜像和旧数据环境，且旧卷与备份仍然存在

### Requirement: 升级验收必须覆盖基础设施和应用数据
系统 SHALL 通过 Compose 级验证确认 PostgreSQL 18、RabbitMQ 4、应用 migration/seed 和 Agent Job 闭环均正常，MUST NOT 仅以容器处于运行状态作为完成标准。

#### Scenario: 完成升级 smoke 测试
- **WHEN** 新基础设施和应用服务全部启动
- **THEN** 验证结果包含数据库版本与数据核验、RabbitMQ 版本与队列拓扑、API ready、Agent Job 成功执行以及 retry/dead-letter 路径

<!-- Reconciled from mcp_new capability: `db-backed-config-compose-smoke` -->

### Requirement: Compose smoke shall verify DB-backed config end to end
系统 SHALL 提供 Docker Compose 下的 smoke 验证流程，覆盖 PostgreSQL migration、api-server、agent-worker、Web-managed secret、DB-backed runtime config overlay、RabbitMQ 消费和 Agent job 完成状态。

#### Scenario: Smoke starts required services
- **WHEN** 开发者按 smoke 文档启动 Docker Compose
- **THEN** `postgres`、`rabbitmq`、`api-server` 和 `agent-worker` MUST 处于 running/healthy 状态

#### Scenario: Smoke proves runtime config source
- **WHEN** 开发者写入 runtime config 并重启 `api-server` 和 `agent-worker`
- **THEN** `/api/ready` SHALL 返回 `runtime_config.source=database` 或等价的 DB-backed source 信息

### Requirement: Compose smoke shall be reproducible with curl
系统 SHALL 提供中文 curl 命令，逐步验证 secret 创建、runtime config 写入、服务重启、ready 检查、job 创建、job 轮询、steps 查询和 tool-calls 查询。

#### Scenario: Developer follows curl document
- **WHEN** 开发者从文档第一条 curl 命令按顺序执行到最后一条
- **THEN** 开发者 SHALL 能获得 `job_id`，并能查询该 job 的状态、最终结果、steps 和 tool-calls

#### Scenario: Curl output records expected fields
- **WHEN** smoke 文档展示每一步预期结果
- **THEN** 文档 MUST 标明关键字段，例如 `secret_ref`、`runtime_config.source`、`job_id`、`status`、`result`、`steps` 和 `tool_calls`

### Requirement: Compose smoke shall avoid secret leakage
系统 SHALL 在 smoke 文档和可选脚本中避免打印真实 secret 明文，并提供响应检查，确认 DeepSeek API key 或 token 没有出现在 API 响应、runtime config snapshot、job steps 或 tool-calls 中。

#### Scenario: Secret create response is inspected
- **WHEN** smoke 创建 `deepseek_api_key`
- **THEN** 响应 SHALL 只展示 `secret://platform/deepseek_api_key`、版本、configured 状态和脱敏摘要，不得包含原始 API key

#### Scenario: Job debug output is inspected
- **WHEN** smoke 查询 job steps 和 tool-calls
- **THEN** 输出 MUST 不包含 DeepSeek API key、Anthropic token、数据库密码、Redis 密码或未脱敏 raw payload

### Requirement: Compose smoke shall document safe real-model mode
系统 SHALL 将真实 DeepSeek/Claude smoke 标记为显式可选路径，并要求使用 synthetic 或已脱敏输入。

#### Scenario: Real model mode is enabled
- **WHEN** 开发者选择启用 `FEATURE_REAL_CLAUDE=true`
- **THEN** 文档 MUST 提醒外部模型数据出境风险，并要求使用合成问题或脱敏上下文

#### Scenario: Default smoke does not require external model
- **WHEN** 开发者执行默认 smoke 流程
- **THEN** 流程 MUST 不要求真实 DeepSeek API key，也不得调用外部模型 API

<!-- Reconciled from mcp_new capability: `feature-configuration-simplification` -->

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

### Requirement: 数据面安全闸门保持独立
系统 MUST 独立解析 `FEATURE_PUBLISHED_AGENT_RUNTIME` 和 `FEATURE_REAL_CLAUDE`，任何管理面开关、旧兼容开关或数据库策略均不得将部署环境中关闭的闸门变为开启。标准 `tool-mcp` 不使用独立功能开关，必须同时通过 Job 状态、Tool publication 子集、当前授权、唯一资源解析和只读策略。
#### Scenario: 管理后台开启但数据面能力关闭
- **WHEN** `FEATURE_WEB_ADMIN=true` 且 `FEATURE_PUBLISHED_AGENT_RUNTIME=false`、`FEATURE_REAL_CLAUDE=false`
- **THEN** 管理员可以配置和发布资源
- **AND** 系统不执行已发布 Agent 或调用真实模型
#### Scenario: 未授权调用真实工具
- **WHEN** 请求缺少有效 RUNNING Job、发布 Tool 子集、当前 Tool grant、数据范围或唯一 Published Resource Revision
- **THEN** `tool-mcp` 失败关闭且不访问上游资源

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

<!-- Reconciled from mcp_new capability: `platform-config-api` -->

### Requirement: API responses do not leak secret values
系统 SHALL 确保所有平台配置 API 响应只返回 secret reference 元数据，MUST NOT 返回任何解析后的真实密钥值。

#### Scenario: Get resource binding with credential
- **WHEN** 管理端查询带数据库密码引用的资源绑定
- **THEN** 系统只返回 `secret_ref` 编码或引用，不返回真实密码

#### Scenario: Export topology snapshot
- **WHEN** 系统导出 topology snapshot
- **THEN** snapshot 中的 credential 字段仍然是 secret reference，不包含明文 token 或 password

### Requirement: Platform API manages DB-backed runtime config
系统 SHALL 提供 runtime config 的 CRUD、启停、snapshot 和校验 API，供后续 Web 配置页面使用。

#### Scenario: Save runtime setting
- **WHEN** 管理端提交合法 runtime setting key、类型、作用域和值
- **THEN** 系统保存配置、更新 revision，并写入配置审计

#### Scenario: Save secret-backed runtime setting
- **WHEN** 管理端把 `ANTHROPIC_API_KEY` 配置为 `secret://platform/deepseek_api_key`
- **THEN** 系统保存 secret ref，并在 snapshot 中仅返回该 ref 的脱敏状态

### Requirement: Platform API exposes env migration guidance
系统 SHALL 提供当前 env key 到 bootstrap-only、deployment safety gate、governed runtime policy、test-only 或 Secret management 的分类与迁移关系。

#### Scenario: List migratable env keys
- **WHEN** 管理端请求可迁移配置项列表
- **THEN** 系统返回 key、类型、安全默认值、是否敏感、分类、建议作用域、适用服务、迁移目标、弃用版本和是否需要重启

#### Scenario: Bootstrap-only key is edited
- **WHEN** 管理端尝试把 `DATABASE_DSN`、`RABBITMQ_URL` 或主加密密钥保存为普通 runtime config
- **THEN** 系统拒绝该配置并提示必须通过部署环境或受控 Secret 管理

#### Scenario: Deployment safety gate is enabled through API
- **WHEN** 管理端尝试通过数据库配置开启被部署环境关闭的已发布 Runtime、真实模型或真实内部工具
- **THEN** 系统拒绝越权开启或保存为被 deployment gate 阻断的请求状态
- **AND** 响应明确说明必须由部署环境开启

#### Scenario: Test-only key is edited in production
- **WHEN** 管理端在生产环境尝试启用测试身份请求头
- **THEN** 系统拒绝修改并记录安全审计事件

### Requirement: Platform configuration writes require authenticated internal actor
系统 SHALL 要求平台配置新增、修改、启停、密钥轮换、导入和发布 API 使用管理端认证 middleware 提供的内部用户 actor，并 MUST 在生产模式拒绝仅靠客户端身份请求头的调用。

#### Scenario: 已认证管理员修改平台配置
- **WHEN** 有有效管理 session 且具备 `platform_config:manage` 权限的内部用户更新资源绑定
- **THEN** 系统执行现有领域校验、保存修改并以内部用户 ID 记录配置审计

#### Scenario: 未认证请求伪造管理员头
- **WHEN** 请求没有有效 session 但提交 `x-admin-user-id`
- **THEN** 生产 API 拒绝请求且不写入平台配置

### Requirement: Platform configuration reads respect management permissions
系统 SHALL 对包含用户授权、密钥状态、runtime config 和管理审计的敏感管理读取执行对应 action permission，并 MUST 继续屏蔽 secret 值。

#### Scenario: 普通 Agent 用户读取密钥状态
- **WHEN** 已认证用户没有 secret 管理或查看权限
- **THEN** 系统拒绝该管理读取，而不是仅因为用户能使用 Agent 就返回密钥元数据

### Requirement: Platform API exposes effective feature diagnostics
系统 SHALL 向具有配置读取权限的管理员提供只读有效功能配置诊断，返回四个顶层开关、派生管理能力、受治理策略、来源、弃用状态和冲突信息。

#### Scenario: Authorized administrator reads diagnostics
- **WHEN** 具有配置读取权限的管理员请求有效功能配置
- **THEN** 系统返回每项配置的最终值、来源、分类、revision、弃用输入和阻断原因
- **AND** 响应不包含 Secret 明文、完整连接串或未经脱敏的环境变量值

#### Scenario: Unauthorized caller reads diagnostics
- **WHEN** 未认证或不具有配置读取权限的调用方请求详细诊断
- **THEN** 系统拒绝请求并记录审计事件

#### Scenario: Legacy conflict is present
- **WHEN** 启动前检查或草稿发布校验发现新旧配置冲突
- **THEN** API 返回稳定的冲突代码、冲突键和迁移目标

### Requirement: 平台配置不得暴露旧 API 平台对象
平台配置 API MUST 不提供 API Capability、Handler、API Connection、Application Resource Mapping、Internal API topology/runtime generation/activation 或 Internal API Token 的读取与写入端点；工具资源、凭据、模型和渠道配置继续使用各自边界。

#### Scenario: 请求旧管理端点
- **WHEN** 客户端访问已退役旧平台 API
- **THEN** 路由不存在且不得返回兼容数据

### Requirement: 运行配置目录不得保留 Internal API 定义
平台运行配置定义和值 MUST NOT 包含任何 `INTERNAL_API_*` 或 `FEATURE_REAL_INTERNAL_TOOLS` 项，包括历史的 auth token、timeout 和 response-size 定义。

#### Scenario: 已有数据库包含未赋值旧定义
- **WHEN** 数据库升级前只剩未设置 value 的旧 Internal API 配置定义
- **THEN** 迁移仍删除这些 definition，配置 API 不再展示或接受它们

<!-- Reconciled from mcp_new capability: `platform-config-registry` -->

### Requirement: Platform topology is persisted in PostgreSQL
系统 SHALL 在 PostgreSQL 中持久化 Environment、可选 Base 和可选 Workshop 的真实层级关系、启停状态、别名和扩展元数据；平台 MUST NOT 要求每个 Environment 都有 Base 或每个 Base 都有 Workshop，也不得保存用于补层级的虚节点。

#### Scenario: Create environment base and workshop
- **WHEN** 管理端创建一个环境、该环境下的真实基地和该基地下的真实车间
- **THEN** 系统持久化三层 topology 关系，并能按环境编码返回完整层级

#### Scenario: Create environment leaf
- **WHEN** 管理端创建一个本身就是有效业务目标且没有基地的环境
- **THEN** 系统持久化 Environment leaf，不自动创建默认 Base 或 Workshop

#### Scenario: Create base leaf
- **WHEN** 管理端创建一个没有车间划分的基地
- **THEN** 系统把该 Base 作为有效叶子目标，不要求占位 Workshop

#### Scenario: Disable workshop
- **WHEN** 管理端禁用一个车间配置
- **THEN** 后续目标选择和数据范围校验 MUST 不再把该车间视为可配置目标

### Requirement: Secret references never store secret payloads
系统 SHALL 在新建资源、Revision 和 binding 中只保存 `secret://platform/<code>`，MUST NOT 在 PostgreSQL 普通配置表中保存真实 token、password、API key、Redis 密码或数据库密码。旧 `env:` 只可作为显式导入输入。

#### Scenario: Store platform secret reference
- **WHEN** 管理端为数据库 Draft 选择凭据中心 Secret
- **THEN** 系统只保存 `password_ref=secret://platform/<code>` 和用途

#### Scenario: Reject raw secret in config json
- **WHEN** 管理端提交的资源配置 JSON 中包含疑似真实密钥字段和值
- **THEN** 系统拒绝保存并返回校验错误

#### Scenario: Reject new env provider binding
- **WHEN** 新建或发布的资源包含 `env:`、`vault:` 或 `kms:` 引用
- **THEN** registry 必须拒绝；旧 env 数据只能进入显式导入流程

### Requirement: Platform configuration changes are audited
系统 SHALL 为平台配置新增、修改、启停、导入和发布动作写入配置审计记录。

#### Scenario: Update resource binding
- **WHEN** 管理端修改一个资源绑定
- **THEN** 系统记录实体类型、实体 ID、动作、操作者、修改前摘要、修改后摘要和时间

#### Scenario: Import yaml topology
- **WHEN** 系统从 YAML import/upsert topology 到 PostgreSQL
- **THEN** 系统为被创建或更新的配置实体写入审计记录

### Requirement: Runtime and configuration data share one database with logical isolation
系统 SHALL 在第一版使用同一个 PostgreSQL database 保存 Web 配置、Agent job、聊天记录、工具调用和审计数据，并 MUST 通过表前缀、模块 repository 和迁移边界进行逻辑隔离。

#### Scenario: Query platform configuration without reading chat tables
- **WHEN** Web 配置 API 查询 platform topology
- **THEN** 系统只通过 `platform_config` repository 读取 `platform_*` 配置表，不直接访问 `agent_message` 或 Agent job 运行表

#### Scenario: Future runtime split remains possible
- **WHEN** 后续需要把聊天和审计运行数据迁移到独立库
- **THEN** 系统可以通过 repository 配置切换运行数据存储，而不改变 platform configuration 的领域 API

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

### Requirement: Registry keeps secret references unresolved outside infrastructure
系统 SHALL 在 registry、public snapshot、配置审计和运行时状态中只保留 secret reference，不得保存或返回解析后的真实密钥值。

#### Scenario: Secret reference is loaded for runtime
- **WHEN** DB-backed resource binding 使用 secret reference 配置数据库、Redis 或 Loki credential
- **THEN** registry snapshot 只包含引用，真实值仅能在 infrastructure gateway 建立外部连接时解析

#### Scenario: Public snapshot is exported
- **WHEN** 管理端或调试工具导出 topology snapshot
- **THEN** 响应不得包含任何真实 password、token、api key 或解析后的 secret payload

### Requirement: Registry stores encrypted secret metadata and versions
系统 SHALL 在平台配置 registry 中保存 secret metadata、active version、provider、状态和审计信息，并将密文版本与普通配置表隔离。

#### Scenario: Persist encrypted secret version
- **WHEN** 管理端创建 Web-managed secret
- **THEN** registry 保存 secret metadata 和密文版本，普通 resource binding 只保存 secret ref

#### Scenario: Secret metadata is listed
- **WHEN** 系统列出 platform secret references
- **THEN** registry 返回 provider、ref、active version 和 configured 状态，不返回密文或明文

### Requirement: Registry stores runtime config definitions and values
系统 SHALL 保存 runtime config key 的定义、类型、默认值、敏感性、适用服务和作用域规则，并保存每个作用域下的配置值。

#### Scenario: Register runtime config key
- **WHEN** 系统启动或迁移时注册 `ANTHROPIC_MODEL`
- **THEN** registry 保存该 key 的类型、默认值、说明和适用服务

#### Scenario: Persist scoped runtime config value
- **WHEN** 管理端为 `agent-worker` 保存 `AGENT_MAX_TURNS=12`
- **THEN** registry 保存 service-scoped 配置值并生成新的 revision/hash

### Requirement: Registry prevents secret payloads in non-secret config
系统 SHALL 阻止疑似密码、token、api key 等明文值保存到普通 config_json、runtime value_json 或审计 after_json。

#### Scenario: Raw password submitted as runtime config
- **WHEN** 管理端把 `ANTHROPIC_API_KEY` 明文作为普通 value_json 提交
- **THEN** registry 拒绝保存并要求使用 secret management

#### Scenario: Raw password submitted in resource binding config
- **WHEN** 管理端把 database password 放入 resource binding config
- **THEN** registry 拒绝保存并要求使用 secret_refs

### Requirement: Provider 字段契约必须与运行时实现一致
Registry MUST 以单一 schema 定义管理 API、前端表单、验证器和运行时适配器字段；数据库第一阶段只允许 MySQL、SQL Server、Oracle，Redis 和 Loki 使用各自统一字段。

#### Scenario: 数据库字段名称不一致
- **WHEN** 请求同时使用旧 `user` 和新 `username` 或其他歧义字段
- **THEN** 系统必须按导入规则显式转换或拒绝，不得让管理端保存后运行时无法读取

#### Scenario: Provider 没有运行时 Handler
- **WHEN** Provider 被元数据声明但当前代码没有对应运行时实现
- **THEN** Registry 必须将其标记 unavailable 并阻止发布

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

### Requirement: JavaScript 构建与 CI 必须统一使用 npm
仓库 SHALL 以现有 npm lockfile 为唯一 JavaScript 依赖锁，CI 和容器构建 MUST 使用 `npm ci`，不得继续引用不存在或非权威的 pnpm lockfile。

#### Scenario: Pull Request 执行前端门禁
- **WHEN** CI 安装前端依赖
- **THEN** CI 必须使用 `npm ci` 并在 lockfile 与 package manifest 不一致时失败

### Requirement: 实施必须遵循六阶段 Gate
变更 MUST 按严格授权、Migrator/UoW/Outbox、Secret/Resource、资源重置/Oracle/热加载、管理界面、完整验收六阶段推进；前一阶段未取得测试与数据证据时不得切换下一阶段核心路径。

#### Scenario: 阶段 Gate 未通过
- **WHEN** 当前阶段仍有失败测试、未核验迁移或未解决的数据不变量
- **THEN** 后续阶段不得执行破坏性切换

### Requirement: 本地验收必须证明真实端到端业务链路
最终本地验收 MUST 使用真实本地 Grafana Webhook、Bearer 认证、Inbox/Outbox、RabbitMQ、Job/Worker、真实只读 MySQL 或 SQL Server 工具、结果、Delivery Outbox 和真实 DingTalk 回复形成一条新鲜链路。

#### Scenario: Grafana firing 告警成功处理
- **WHEN** 测试 Grafana 使用有效 Bearer Token 发送合成 firing 事件
- **THEN** 系统必须产生可关联的 ingress、Outbox、Job、tool-call、Delivery 和 DingTalk 回执证据

### Requirement: 验收必须覆盖关键拒绝和恢复路径
验收 MUST 覆盖无效 Webhook Token 不创建 Job、缺失 RBAC 被拒绝、RabbitMQ 中断后 Outbox 恢复、Worker 可重试与 DEAD、Delivery 中断后恢复及全链路 Secret 不泄漏。

#### Scenario: RabbitMQ 在 Outbox 提交后暂时不可用
- **WHEN** Job 与 Outbox 已提交但 RabbitMQ publish 失败
- **THEN** Dispatcher 必须有限重试并在 RabbitMQ 恢复后发布同一幂等 event

#### Scenario: 无效 Token 调用 Webhook
- **WHEN** 请求携带错误 Bearer Token
- **THEN** 系统必须拒绝，且不创建 Inbox、Job 或 Outbox 业务记录

### Requirement: 延期能力不得被误报为已验证
验收报告 MUST 明确声明本次未验证真实 Oracle 11.2.0.4、生产 HTTPS/HMAC、Worker 运行中崩溃恢复和任务取消。

#### Scenario: 本地没有 Oracle
- **WHEN** 本次验收仅完成 Oracle 静态、单元或测试替身检查
- **THEN** 报告必须把真实 Oracle 连接标为 deferred，Oracle Resource Revision 不得进入 PUBLISHED

#### Scenario: 本地 HTTP 链路通过
- **WHEN** Compose 内 HTTP Webhook 功能验证成功
- **THEN** 报告只能声明本地功能通过，不得声明公网生产安全

<!-- Reconciled from mcp_new capability: `platform-runtime-config` -->

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
DB、Redis、Loki runtime MUST 只消费 PostgreSQL 中启用 Resource Identity 的 Published Resource Revision；YAML、环境变量、Application Resource Mapping 或代码默认连接不得在数据库资源无效时成为回退。
#### Scenario: 数据库存在唯一有效发布版本
- **WHEN** `tool-mcp` 按资源类型、业务目标和可选 placement 解析一次 Tool Call
- **THEN** 它只消费唯一 Published Revision 及其 `secret://platform/` 引用，并记录实际版本
#### Scenario: 发布版本无效但旧 YAML 可用
- **WHEN** Published Revision 无法解析且部署目录仍残留旧 YAML
- **THEN** Tool Call 必须失败关闭，不得读取 YAML、旧 Revision 或第一候选

### Requirement: YAML 和 env 只能参与 bootstrap 或显式 import
系统 SHALL 允许部署必需的 bootstrap 配置继续来自 env/文件，并允许显式导入旧资源配置；导入后必须经过 Draft、验证和发布流程。

#### Scenario: 导入旧 env Secret
- **WHEN** 管理员显式执行旧资源迁移
- **THEN** env 值只读取一次并转换为平台 Secret，运行时资源不再直接引用 env

<!-- Reconciled from mcp_new capability: `platform-schema-migration-runtime` -->

### Requirement: 只有一次性 Migrator 可以修改平台 schema
系统 MUST 由独立 one-shot Migrator 应用 schema migration；API、Worker、Dispatcher、Agent Runtime、`tool-mcp`、ONES MCP 和 File Service MUST NOT 在自身启动或请求处理中执行 migration。
#### Scenario: Compose 启动平台
- **WHEN** Docker Compose 启动新版本平台
- **THEN** Migrator 必须先成功退出，依赖 schema 的业务服务随后才可启动
#### Scenario: 业务服务直接启动
- **WHEN** 任一业务服务启动且数据库 schema 未达到代码要求的 head
- **THEN** 服务必须启动失败并返回不含敏感信息的版本差异

### Requirement: Migration 必须具有唯一版本、稳定 checksum 和全局互斥
Migrator MUST 拒绝重复版本，并在执行前校验已应用 migration 的 checksum；同一 PostgreSQL 数据库同时最多只能有一个持有 advisory lock 的 Migrator。

#### Scenario: 两个 Migrator 并发启动
- **WHEN** 两个实例同时尝试迁移同一数据库
- **THEN** 只有一个实例获得全局锁并执行，另一个等待或安全退出

#### Scenario: 已应用 migration 内容被修改
- **WHEN** 账本中的 checksum 与磁盘 migration checksum 不一致
- **THEN** Migrator 必须停止且不得应用任何后续版本

### Requirement: 每个 migration 必须在完整事务中执行
系统 MUST 将单个 migration 的全部语句及其账本记录置于同一数据库事务中；任一步失败时该版本不得部分生效。

#### Scenario: Migration 中间语句失败
- **WHEN** 某个 migration 的任一语句执行失败
- **THEN** 该版本的 schema 变更和账本写入必须全部回滚

### Requirement: 数据库访问必须使用操作级 Unit of Work
系统 SHALL 使用同步连接池，并为每个请求、消息处理或 CLI 操作创建独立 Unit of Work；MUST NOT 共享全局连接或全局事务深度。

#### Scenario: 两个请求并发修改数据
- **WHEN** 两个 API 请求同时执行各自业务操作
- **THEN** 两个请求必须使用独立连接和事务，任一回滚不得影响另一请求

#### Scenario: 业务操作需要外部调用
- **WHEN** 操作需要调用模型、HTTP、RabbitMQ 或 DingTalk
- **THEN** 本地数据库事务必须在外部调用前完成，外部副作用通过 Outbox 或独立步骤驱动

### Requirement: 最终项目 Schema 必须具有完整中文注释
系统 MUST 通过向前迁移为 PostgreSQL `public` schema 中最终保留的每张项目自有表和每个字段设置非空中文注释；注释 SHALL 描述领域含义、关联对象、状态、版本、时间或安全边界，不得使用统一无语义占位文本。`schema_migration` 迁移账本、PostgreSQL 系统表和第三方扩展表不属于项目注释范围。

#### Scenario: 已有数据库升级
- **WHEN** 已执行到前一 schema head 的 PostgreSQL 数据库升级
- **THEN** 所有最终保留的项目表和字段都具有非空中文 comment，业务数据、约束和索引保持不变

#### Scenario: 新迁移增加表或字段
- **WHEN** 后续迁移新增项目自有表或字段但没有同步声明注释
- **THEN** schema 注释覆盖测试失败并阻止发布

#### Scenario: SQLite 运行迁移
- **WHEN** 测试或本地环境使用 SQLite 执行同一迁移目录
- **THEN** PostgreSQL `COMMENT ON` 语句被兼容跳过，最终 SQLite schema 仍与静态注释清单进行完整性对照

### Requirement: 活动迁移目录必须从最终 Schema 基线开始
系统 MUST 使用 `100_baseline_v1.sql` 作为第一代活动 schema 基线；空 SQLite 或 PostgreSQL 数据库 MUST 直接得到与旧 001–042 完整迁移链最终状态等价的表、字段、约束、索引和适用的 PostgreSQL 中文注释，后续迁移版本 MUST 从 101 单调递增。

#### Scenario: 全新 PostgreSQL 数据库迁移
- **WHEN** Migrator 面对没有项目表和迁移记录的 PostgreSQL 数据库
- **THEN** 系统只执行活动基线及其后的迁移，并得到完整最终 schema 与 100% 项目表字段中文注释覆盖

#### Scenario: 全新 SQLite 数据库迁移
- **WHEN** 测试或本地流程对空 SQLite 数据库执行活动迁移目录
- **THEN** 系统建立与 PostgreSQL 领域结构等价的 SQLite schema，并安全跳过 PostgreSQL 专用注释语句

### Requirement: Legacy Migration Manifest 必须冻结被替换的迁移身份
仓库 MUST 保存 001–042 每个迁移的版本、文件名和 checksum，以及整个旧目录的 catalog digest 与最终 schema fingerprint；旧 SQL 不再参与活动迁移解析，legacy manifest 一旦发布 MUST NOT 被原地改写。

#### Scenario: 旧账本完全匹配 manifest
- **WHEN** Migrator 读取一个精确执行到 042 的旧账本
- **THEN** 系统逐项验证版本、名称、checksum 和 catalog digest 后才允许进入基线等价验证

#### Scenario: Manifest 或旧账本发生漂移
- **WHEN** 任一旧迁移记录缺失、重复、名称变化、checksum 不同或 manifest digest 不一致
- **THEN** Migrator 失败关闭且不得登记基线或执行后续迁移

### Requirement: 精确 042 数据库必须通过 Baseline Adoption 无损接轨
对账本精确到 042 的数据库，Migrator MUST 验证最终 schema fingerprint、PostgreSQL 注释覆盖和关键保留数据不变量，并在单一事务中登记 100 基线等价事实；系统 MUST 保留旧 ledger 记录且 MUST NOT 重放基线 DDL、清空业务数据或重置 revision。

#### Scenario: 042 数据库成功采纳基线
- **WHEN** 旧 ledger、schema、注释和数据不变量全部匹配
- **THEN** 系统记录来源 head、legacy catalog digest、schema fingerprint、100 基线 checksum 和采纳时间，并允许后续 101+ migration

#### Scenario: 042 Schema 存在漂移
- **WHEN** 账本为 042 但表、字段、约束、索引、注释或关键保留对象不符合基线
- **THEN** Baseline Adoption 失败且数据库保持原账本和原数据不变

#### Scenario: 重复执行已采纳数据库
- **WHEN** Migrator 再次处理已经登记 100 等价事实且没有新迁移的数据库
- **THEN** 系统幂等退出，不重复插入采纳记录或修改业务数据

### Requirement: 非 042 Legacy Head 必须失败关闭
活动 Migrator MUST 拒绝直接处理 001–041、空洞 ledger、无 ledger 的非空 schema 或未知旧 head，并 SHALL 提示操作人使用旧版本镜像先升级到精确 042；系统不得猜测缺失 migration 或把部分 schema 当作完整基线。

#### Scenario: 数据库只执行到 041
- **WHEN** 新 Migrator 发现合法但未达到 042 的旧账本
- **THEN** 系统不执行 100，并返回先使用旧版本升级到 042 的安全提示

#### Scenario: 非空数据库没有账本
- **WHEN** 新 Migrator 发现项目表存在但没有可验证的旧 ledger
- **THEN** 系统失败关闭，不依据表名近似匹配自动采纳基线

### Requirement: 空库编排必须在启动业务服务前完成管理员 Bootstrap
Compose 和受支持的部署脚本 MUST 按“schema migration、初始管理员 bootstrap、Runtime grants”的顺序执行；任一步失败时 Migrator 服务 MUST 非零退出，API、Worker、Runtime 和 Channel 服务不得启动。

#### Scenario: 空库完成完整初始化
- **WHEN** 部署流程首次处理空数据库
- **THEN** schema 达到当前 head、初始管理员可登录、Runtime grants 已应用后业务服务才启动

#### Scenario: 管理员 Bootstrap 失败
- **WHEN** 初始管理员缺少必需安全输入或身份写入失败
- **THEN** Compose migrator 失败且依赖 `service_completed_successfully` 的服务保持未启动

<!-- Reconciled from mcp_new capability: `platform-secret-management` -->

### Requirement: Web-managed secrets are encrypted before persistence
系统 SHALL 允许管理端提交 secret 明文值，但 MUST 在写入持久化存储前加密或转存到 Secret Provider，并且 MUST NOT 在 PostgreSQL 配置表、审计、日志、API 响应或 Agent prompt 中保存明文。

#### Scenario: Admin creates a secret value
- **WHEN** 管理端提交 `code=deepseek_api_key` 和 secret 明文值
- **THEN** 系统加密保存该值，返回稳定 `secret_ref`，且响应不包含明文

#### Scenario: Secret value appears in request logging path
- **WHEN** secret 创建或更新请求经过 API、异常处理、审计和日志链路
- **THEN** 所有持久化或输出内容 MUST 使用脱敏摘要，不得包含原始 secret 明文

### Requirement: Secrets are versioned and rotatable
系统 SHALL 为每个 Web 管理的 secret 保存版本信息，并支持新增版本、设为当前版本、禁用旧版本和审计轮换动作。

#### Scenario: Rotate secret
- **WHEN** 管理端为已有 secret 提交新明文值
- **THEN** 系统创建新版本并将其设为 active，旧版本不再用于运行时解析

#### Scenario: Disable secret
- **WHEN** 管理端禁用 secret 或其 active version
- **THEN** 后续运行时解析该 `secret_ref` MUST 失败为安全配置错误

### Requirement: Secret references resolve through provider abstraction
系统 SHALL 通过统一 SecretResolver 解析 `secret://platform/<code>`；新界面、新资源和新发布 MUST 只允许该 Provider。现有 `env:` 仅允许由显式导入操作读取一次并迁移为加密平台 Secret；`vault:`、`kms:` 必须作为尚未实现的预留 Provider 被拒绝。

#### Scenario: Resolve encrypted database secret
- **WHEN** 运行时解析 `secret://platform/order_db_password`
- **THEN** SecretResolver 从 encrypted DB provider 读取 active 密文版本，并只向 infrastructure 层返回解密值

#### Scenario: Import existing env secret reference
- **WHEN** 授权管理员显式导入仍被旧资源引用的 `env:ORDER_DB_PASSWORD`
- **THEN** 系统读取一次环境值、创建加密平台 Secret、生成 `secret://platform/` 引用并记录不含明文的审计

#### Scenario: New UI attempts env reference
- **WHEN** 新建或发布资源时提交 `env:` 引用
- **THEN** 系统必须拒绝并要求选择凭据中心 Secret

#### Scenario: Reserved provider is selected
- **WHEN** 配置尝试创建或发布 `vault:` 或 `kms:` 引用
- **THEN** 系统必须返回“Provider 尚未实现”，不得声称可用或尝试解析

### Requirement: Secret values are never displayed after save
系统 SHALL 在 Web/API 查询 secret 时只返回配置状态、版本、更新时间、用途和脱敏摘要，MUST NOT 支持明文回显。

#### Scenario: Admin lists secrets
- **WHEN** 管理端查询 secret 列表
- **THEN** 系统返回 secret code、provider、active version、configured 状态和更新时间，不返回明文 secret

#### Scenario: Admin views secret detail
- **WHEN** 管理端查看某个 secret 详情
- **THEN** 系统可返回脱敏摘要如 `sk-****abcd`，但 MUST NOT 返回完整 secret value

### Requirement: Secret operations are authorized and audited
系统 SHALL 在创建、更新、轮换、禁用和解析管理接口前校验平台配置管理权限，并记录不含明文的审计记录。

#### Scenario: Unauthorized user creates secret
- **WHEN** 未授权用户提交 secret 创建请求
- **THEN** 系统拒绝请求，不保存任何 secret 值

#### Scenario: Secret rotation audit
- **WHEN** 管理员轮换 secret
- **THEN** 系统记录 actor、secret code、旧版本、新版本、动作和 correlation id，但不记录明文

### Requirement: Secrets shall be smoke-verifiable through Compose curl
系统 SHALL 允许开发者在 Docker Compose 环境中通过 curl 创建、查询、轮换和禁用 Web-managed secret，并验证返回内容不泄漏明文。

#### Scenario: Compose curl creates DeepSeek secret
- **WHEN** 开发者调用 `POST /api/platform/secrets` 创建 `deepseek_api_key`
- **THEN** API SHALL 返回 `secret://platform/deepseek_api_key` 和脱敏摘要，且响应 MUST 不包含提交的原始 key

#### Scenario: Compose curl disables secret safely
- **WHEN** 开发者调用 `POST /api/platform/secrets/deepseek_api_key/disable`
- **THEN** 后续 runtime 解析该 secret SHALL 失败为安全配置错误，且不得回退到旧版本或空 key

### Requirement: Secret smoke documentation shall protect operator input
系统 SHALL 在 smoke 文档中要求开发者通过环境变量或交互输入提供真实 key，MUST NOT 要求把真实 key 写入命令历史、README、OpenSpec artifact 或 git tracked 文件。

#### Scenario: Real key is supplied for optional smoke
- **WHEN** 开发者执行真实 DeepSeek 可选验证
- **THEN** 文档 SHALL 使用 `DEEPSEEK_API_KEY` 或等价本地环境变量占位，不得展示真实 key

### Requirement: 平台 Secret 必须使用仓库外固定 Master Key
系统 MUST 从仓库外只读文件加载单个稳定 Master Key，并在持久化前加密 Secret；Compose 和代码不得提供硬编码回退，非测试环境缺失 Key 时必须启动失败。

#### Scenario: Master Key 未配置
- **WHEN** 非测试服务需要 Secret 功能但 Master Key 文件缺失或权限不安全
- **THEN** 服务必须拒绝启动或将 Secret 子系统标为不可用，且不得生成临时 Key

#### Scenario: Master Key 正常加载
- **WHEN** 受控文件包含有效 Key
- **THEN** 系统可以解密已保存版本，但健康状态和日志不得输出 Key 或可逆摘要

### Requirement: Master Key 不实行在线周期轮换
本次系统 MUST NOT 实现 Web 管理、多 Key keyring、到期时间或自动周期轮换；仅允许文档化的紧急离线重加密流程。

#### Scenario: 管理员查看凭据中心
- **WHEN** 管理员访问凭据中心
- **THEN** 页面不得提供 Master Key 查看、编辑、轮换或下载功能

### Requirement: 凭据中心必须支持资源表单安全选择
“平台治理 → 凭据中心” SHALL 管理平台 Secret metadata 和版本；DB、Redis、Loki 表单 SHALL 通过授权选择器保存 `secret://platform/<code>`，不得把明文写入 Resource Revision。

#### Scenario: 数据库表单选择密码
- **WHEN** 管理员选择一个可用平台 Secret 并保存 Draft
- **THEN** Resource Draft/Revision 只保存 `password_ref`，API 响应不包含明文或密文

#### Scenario: Secret 被禁用
- **WHEN** 已发布资源引用的 active Secret 被禁用
- **THEN** 依赖该 Secret 的后续验证或 Tool Call 必须失败关闭，Published Revision 保持不可变且不得回退旧 Secret 或旧 Revision

### Requirement: Internal API 与 Runtime Tool 专用密钥必须永久删除
系统 MUST 不创建、挂载、解析或展示 Internal API server/client Token、`runtime-tool-mcp` HS256 signing key、MCP access token 或相关 Secret usage；平台凭据中心只保留工具资源、模型、渠道和其它仍存在的业务 Secret。

#### Scenario: 升级已有数据库
- **WHEN** 破坏性迁移发现仅被已退役组件引用的 Internal API 或 Runtime Tool Secret metadata
- **THEN** 系统删除其 usage 和 metadata，审计不得包含 Secret 值

#### Scenario: 新配置提交旧 Secret code
- **WHEN** 管理 API 或 Compose 尝试配置已退役专用 Secret
- **THEN** 配置校验失败且不得形成兼容用途

<!-- Reconciled from mcp_new capability: `safe-real-model-tool-testing` -->

### Requirement: Real model tests shall use synthetic or sanitized evidence by default
系统 SHALL 默认只使用合成日志、合成业务问题或已脱敏工具摘要执行真实 Claude/DeepSeek + real-tools 端到端测试。

#### Scenario: 使用合成日志测试
- **WHEN** 开发者运行真实模型 smoke test
- **THEN** 测试输入和工具证据 SHALL 来自合成数据或明确标记为可外发的测试数据

#### Scenario: 未确认真实业务日志
- **WHEN** 测试会把真实业务日志或内部敏感证据发送到外部模型
- **THEN** 系统文档和测试流程 MUST 要求先获得显式确认

### Requirement: Tool summaries sent to external models shall be redacted
系统 SHALL 在真实模型运行时对发送给外部模型的工具摘要执行脱敏，至少覆盖 token、password、secret、authorization、个人敏感信息和过长日志片段。

#### Scenario: 工具返回包含敏感字段
- **WHEN** 工具结果中包含 token、password、secret 或 authorization 类字段
- **THEN** 发送给模型和持久化到审计摘要的内容 MUST 使用脱敏值

#### Scenario: 工具返回过长日志
- **WHEN** Loki 或数据库工具返回超过配置上限的结果
- **THEN** 系统 SHALL 截断结果并标记 truncated

### Requirement: Real model safety mode shall be visible in documentation
系统 SHALL 在 README 或测试文档中明确说明 `FEATURE_REAL_CLAUDE=true` 与 DeepSeek/Claude API 环境变量的风险边界和推荐测试数据策略。
#### Scenario: 开发者启用真实模型
- **WHEN** 开发者准备设置 `FEATURE_REAL_CLAUDE=true`
- **THEN** 文档 SHALL 提醒该模式会调用外部模型 API，并要求使用合成或脱敏数据
#### Scenario: 只验证工具链
- **WHEN** 开发者只需要验证 `python-agent-runtime -> tool-mcp -> Published Resource Revision` 链路
- **THEN** 文档 SHALL 提供不调用真实外部模型的受控测试路径

### Requirement: Canonical 主规格是唯一当前规范基线
仓库 SHALL 仅将 `openspec/specs/<canonical-domain>/spec.md` 视为当前已接受规范的 canonical baseline。Active change、archive、proposal、design、tasks、evidence、ADR 和运行手册 MUST NOT 覆盖 canonical Requirement；需要改变当前规范时 MUST 通过明确的 OpenSpec change 更新 canonical specs。

#### Scenario: 判断当前已接受规范
- **WHEN** Codex 或维护者需要确定项目当前的规范要求
- **THEN** 其以相关领域的 canonical spec 为规范事实源，不从历史 change 或辅助文档推断替代要求

#### Scenario: 辅助文档与主规格冲突
- **WHEN** ADR、运行手册或历史 evidence 与 canonical Requirement 表述冲突
- **THEN** 系统维护流程将冲突记录为待处理 change，而不静默改写或绕过 canonical spec

### Requirement: Codex 默认按领域读取 Canonical 主规格
仓库级 Codex 指令 SHALL 要求 Codex 在一般规格、设计和实现任务中只默认读取与请求相关的 canonical domain specs。只有在用户指定 active change、执行 OpenSpec change 工作流或明确要求历史审计时，Codex 才可读取对应 change 或 archive，并 MUST 明确区分其非当前规范身份。

#### Scenario: 处理普通领域需求
- **WHEN** 用户提出身份、Agent、业务应用、Channel、执行、内置工具、API Capability 或平台运维需求且未指定 change
- **THEN** Codex 只加载相关 canonical domain spec 作为默认规格上下文

#### Scenario: 处理指定 Active Change
- **WHEN** 用户指定某个 active change 或要求执行 propose、apply、sync、archive 工作流
- **THEN** Codex 可读取该 change 的 artifacts，并以 delta 相对 canonical baseline 的语义处理，而不加载无关 change 或 archive

#### Scenario: 明确追溯历史
- **WHEN** 用户明确要求审计历史决策或归档证据
- **THEN** Codex 可读取相关 archive，但将其标记为历史证据且不把它当作当前规范

### Requirement: Archive 保持完整且不参与默认规范解析
基线重建 SHALL 保留 `openspec/changes/archive/` 下的历史内容，不得为了减少默认上下文而删除或改写既有 archive。默认规范解析 MUST 排除 archive；历史内容只有在显式追溯时才参与证据分析。分叉分支合并涉及旧规格路径和 archive 内迁移快照的 rename／modify 交叉时，维护流程 MUST 独立验证 archive manifest，并将目标分支的已接受差异重新同步到 canonical domain，而不得接受仅有“无 Git 冲突”的结果。

#### Scenario: 重建 Canonical Baseline
- **WHEN** 维护者替换或重组主规格文件
- **THEN** 既有 archive 的目录、proposal、design、tasks、delta specs 和 evidence 保持不变

#### Scenario: 默认规格检索
- **WHEN** Codex 搜索当前领域要求且用户没有请求历史
- **THEN** 搜索范围排除 `openspec/changes/archive/`

#### Scenario: 分叉分支修改了被迁移的旧规格
- **WHEN** canonical baseline 提交把旧规格移动到 archive，而目标分支在共同基点后修改了同一旧规格路径
- **THEN** 合并流程验证 archive 快照仍与其冻结 manifest 一致，并把目标差异同步到对应 canonical domain
- **AND** 流程不得因为 Git merge 无文本冲突就宣称 canonical 对账完成

#### Scenario: 领域化后归档旧 Capability Delta
- **WHEN** 一个 completed change 的 delta 仍按领域化之前的 capability 路径组织
- **THEN** 维护流程先按明确映射把 delta 语义同步到 canonical domains，再使用跳过重复同步的方式归档
- **AND** 归档不得重新创建碎片主规格目录

### Requirement: 项目文档必须具有单一入口和稳定分类
仓库 MUST 在 `docs/README.md` 提供文档总索引，并 SHALL 将当前文档按 architecture、guides、operations、verification 和 reference 分类；历史材料 MUST 位于 archive 分类，不得与当前操作指引平铺混放。

#### Scenario: 维护者查找当前运行架构
- **WHEN** 维护者从 `docs/README.md` 查找当前系统架构或运行链路
- **THEN** 索引将其导航到 architecture 下的当前文档，并明确该文档的事实范围

#### Scenario: 维护者查找运维步骤
- **WHEN** 维护者查找数据库、Compose、Master Key、钉钉重建或 Runtime 运维步骤
- **THEN** 索引将其导航到 operations 下的可执行 Runbook，而不是历史实施记录

### Requirement: 当前事实、规范意图和历史证据必须明确分层
当前文档 MUST 区分已由代码或运行验证确认的事实、Canonical OpenSpec 规范意图和带日期的验证快照；ADR、旧实施基线和退役组件说明 MUST NOT 被表述为当前能力。

#### Scenario: 旧 API Platform ADR 被保留
- **WHEN** 旧 API Capability、Handler、Connection 或 Resource Mapping ADR 仍有审计价值
- **THEN** 文档移动到 archive 历史区并标记其退役边界，不再出现在当前设计入口

#### Scenario: 验证记录可能过期
- **WHEN** 文档记录一次 Compose、数据库或 Runtime 实际验收
- **THEN** 文档标明验证日期、版本或 head，并不得把该快照自动描述为当前实时状态

### Requirement: 文档移动不得破坏仓库引用
文档重组 MUST 更新根 README、backend README、CONTEXT、OpenSpec artifact、脚本和文档之间的相对链接，并 MUST 提供自动化本地链接检查，拒绝不存在的仓库内 Markdown 目标。

#### Scenario: 文档路径发生移动
- **WHEN** 当前文档或历史 ADR 被移动到新分类目录
- **THEN** 所有仓库内引用同步更新且链接检查通过

#### Scenario: 提交包含失效链接
- **WHEN** Markdown 链接指向不存在的仓库内文件或锚点格式无法解析
- **THEN** 文档质量门禁返回非零状态并阻止将整理工作标记完成

### Requirement: Compose 部署 File Service 并以 File Worker 替换附件 Worker
默认Compose SHALL 保持`file-service`与替换旧`attachment-worker`的`file-worker`，并新增内部`docling-serve`和独立`file-processing-worker`；不得长期并存两个附件消费者，也不得新增独立`file-mcp`容器。`file-service`同时承载内部REST与File MCP接口；`file-worker`继续消费原附件队列并承担来源下载/导入、工作区过期、保留内容和提交暂存清理；`file-processing-worker`只消费文档处理队列并编排Docling；现有Agent Worker和Delivery Dispatcher继续独立运行。
#### Scenario: 从现有部署升级
- **WHEN** 现有附件或processing队列中存在ready/unacked消息并部署新版本
- **THEN** `file-worker`保持兼容附件队列，`file-processing-worker`按独立版本化拓扑消费processing消息
- **AND** 不因服务变化删除队列、丢失消息、重复导入原件或发布重复representation
#### Scenario: Compose服务清单检查
- **WHEN** 运维启动启用文档处理的默认文件工作区部署
- **THEN** 服务包含`file-service`、`file-worker`、`file-processing-worker`和`docling-serve`
- **AND** 不包含独立`file-mcp`、长期`attachment-worker`、Docling RQ/Redis或Ray服务

### Requirement: MinIO凭据只注入File Service
Compose、Secret usage 和运行配置 MUST 只向 `file-service` 提供 MinIO endpoint 与 `secret://platform/` 凭据引用所需能力。`agent-worker`、Python Runtime、`file-worker`、Delivery Dispatcher 和前端 MUST NOT 挂载或解析 MinIO Access Key、Secret Key 或 Session Token。File Service 健康、错误和配置快照只能显示 configured 状态与脱敏 endpoint 摘要。本地 Compose 首次启动 MAY 让一次性 Migrator 通过角色隔离的 Docker Secret 把 MinIO 凭据写入平台 `encrypted_db` Secret，但该进程 MUST 不获得 MinIO endpoint、Bucket 或对象访问路径，已有 Secret 不同则失败并要求显式轮换；生产部署 MUST 可关闭此本地 bootstrap。

#### Scenario: File Worker环境被检查
- **WHEN** 运维查看 `file-worker` 有效配置和容器挂载
- **THEN** 不存在 MinIO Secret 值或可解析 Secret usage

#### Scenario: MinIO Secret不可用
- **WHEN** File Service 引用的 Secret 缺失、禁用或无法解密
- **THEN** File Service readiness 失败且不回退到空值、旧 env Secret 或临时凭据

#### Scenario: 本地首次启动初始化受治理Secret
- **WHEN** 本地 Compose 显式启用文件存储 Secret bootstrap 且目标平台 Secret 尚不存在
- **THEN** 一次性 Migrator 从只读 Docker Secret 创建加密版本后销毁自身运行态
- **AND** 不向长期运行服务暴露 bootstrap 值，重复启动保留相同值，值不同则失败而不自动轮换

### Requirement: File Service与File Worker具有真实就绪和积压观测
File Service readiness MUST 验证PostgreSQL schema、MinIO私有bucket访问、Principal JWKS、Manifest v5、representation staging和内部流式接口依赖；File Worker readiness MUST 验证附件RabbitMQ队列契约、File Service内部API和清理调度；File Processing Worker readiness MUST 验证独立processing队列、File Service、角色Principal和Docling `/ready`；Docling readiness MUST 验证模型与内部编排器可处理请求。平台运维视图 SHALL 展示附件、processing run、representation staging、重试/dead-letter、提交暂存、工作区过期、保留清理和File Domain Outbox的安全积压计数与最近结果，不得仅以容器running或`/health`声明可用。
#### Scenario: MinIO进程可达但bucket无权限
- **WHEN** File Service能连接MinIO endpoint但无法读取或写入受控bucket
- **THEN** readiness返回失败并阻止文件与文档处理能力被宣称为已接线
#### Scenario: File Worker存在清理积压
- **WHEN** 到期内容因瞬时错误等待重试
- **THEN** 运维状态显示有界积压、最早到期时间和安全错误分类
- **AND** 不显示文件名、正文、对象键或凭据
#### Scenario: 文档处理存在积压
- **WHEN** processing run、retry或dead-letter超过受控告警阈值
- **THEN** 运维状态显示数量、最早创建/重试时间、状态、processor/Profile和安全错误分类
- **AND** 不显示文件名、Markdown、JSON、原始错误或凭据
#### Scenario: File Domain Outbox存在待发布事件
- **WHEN** 附件导入、processing run、representation或文件版本事务已提交领域事件但发布尚未完成
- **THEN** 维护/Dispatcher链路按事件类型幂等发布并把Outbox标记为`PUBLISHED`
- **AND** 运维状态显示待发布数量、最早事件时间和安全失败码，不显示文件名、正文、对象键或凭据
#### Scenario: 历史Outbox积压升级后恢复
- **WHEN** 升级前已有长期`PENDING`文件领域事件
- **THEN** 下一次维护周期按确定顺序幂等发布并清空可处理积压
- **AND** 不创建无人消费队列、重复文件版本、processing run或representation

### Requirement: Compose完整配置Service Principal签发与刷新链路
默认Compose MUST 只维护一套平台Principal签名私钥和公开JWKS：现有平台API身份模块与Agent Worker只在需要签发对应Token时挂载同一私钥，File Service、ONES MCP及后续MCP只挂载同一公开`PRINCIPAL_JWKS`；不得声明或挂载第二套Service Principal私钥/JWKS。平台API还 MUST 挂载角色隔离的File Worker、File Processing Worker和Delivery Worker bootstrap credential，并让每个Worker只挂载自己的bootstrap credential。部署 MUST 使用按需签发和到期前刷新，不得要求宿主机预先提供短时Service JWT文件。密钥初始化 MUST 幂等生成统一Principal密钥/JWKS与全部bootstrap材料、拒绝不完整统一密钥组并保持私钥和bootstrap文件owner-only。Docling API Key MUST 与平台Principal体系分离，只挂载到`file-processing-worker`和`docling-serve`。
#### Scenario: 新环境首次启动
- **WHEN** 运维运行受控密钥初始化后启动默认Compose
- **THEN** 统一Principal密钥/JWKS及File Worker、File Processing Worker、Delivery Worker bootstrap bind source均存在且容器可创建
- **AND** 三个Worker能分别从平台身份接口取得可验证的角色JWT
#### Scenario: 检查角色Secret挂载
- **WHEN** 运维检查API、File Service、三个Worker与Docling的Compose Secret
- **THEN** API拥有统一Principal签名私钥和三份角色bootstrap credential，File Service只有统一公开JWKS
- **AND** 每个Worker只有自己的bootstrap credential，Docling API Key只在Processing Worker与Docling出现，任何组件都没有另一角色Secret
#### Scenario: 短时JWT到期
- **WHEN** 已缓存Service JWT进入刷新窗口或过期
- **THEN** Worker通过固定平台身份地址换取新JWT并继续调用
- **AND** 不回退到静态JWT、共享Token或未认证内部请求
#### Scenario: Docling API Key缺失
- **WHEN** `file-processing-worker`或`docling-serve`无法解析独立API Key
- **THEN** 对应readiness失败且不回退到无认证Docling请求

### Requirement: Job Sandbox容量和隔离配置必须可验证
Python Runtime临时文件系统配置 MUST对每个Job实施64个常规文件槽位和224MiB共享容量：`inputs`最多40个、`work/outputs`合计最多16个、内部临时及安全余量保留8个。全部自动物化、File MCP按需物化、Agent Write/Edit、输出选择和内部临时处理 MUST经同一个`JobSandbox`预算与预留服务；File MCP不得在授权成功后直接写盘绕过文件数、分区或容量检查。Compose、Runtime默认值、代码硬限制和readiness MUST保持一致，并在健康状态中只显示非敏感上限。

输入计数按实际进入Sandbox的唯一File/Version计算，重复物化同一版本复用既有entry且不重复计数。Office、PDF和图片只允许其精确Markdown Representation进入Sandbox，每个原始File/Version计为一个输入；原始二进制和Docling JSON不得进入Sandbox。64个文件槽位与224MiB是两个同时生效的边界；预留的输出槽位不保证独立字节容量，全部分区仍共享224MiB。
#### Scenario: 沙盒容量小于合法最小处理需求
- **WHEN** Runtime配置不是64文件/224MiB，或无法保留40输入、16工作输出和8个内部余量槽位
- **THEN** Runtime readiness失败而不是在Agent执行中使用漂移的边界
#### Scenario: 单Job达到沙盒上限
- **WHEN** 继续物化或生成文件会超过对应分区文件数、64文件总数或224MiB共享容量
- **THEN** Runtime在创建目标文件或写入首字节前拒绝并返回安全、有界错误
#### Scenario: 原始文档被请求物化
- **WHEN** Runtime尝试把PDF、Office、图片或Docling JSON写入Agent Sandbox
- **THEN** 类型门禁在下载字节前拒绝
#### Scenario: 自动物化批次不能完整容纳
- **WHEN** 计划自动物化输入超过40个不同File/Version或实际表示总大小会突破224MiB
- **THEN** Job在创建与outbox前完整失败并要求缩小工作集
- **AND** 不创建半数输入已冻结或已物化的Job
#### Scenario: File MCP物化失败释放预留
- **WHEN** File MCP物化已预留输入槽位和容量但下载失败或SHA-256不匹配
- **THEN** Runtime清理部分文件并释放相同预留
- **AND** 后续重试仍从真实Sandbox使用量重新校验

### Requirement: 当前运行态只支持Python并保留历史TypeScript事实
当前源码、API、Agent bootstrap、Worker 和 Compose MUST 只支持新建、发布与执行 `python-v1` Agent，并 MUST 拒绝新的 `typescript-v1` Agent、Publication、Application 激活或 Job 执行。数据库中退役前形成的 TypeScript Definition、Publication、终态 Job 和审计事实 MAY 保留并 MUST 只读展示原始 runtime kind；系统不得声称当前存在源码中没有的退役预检 CLI、自动排空或跨 Runtime 迁移命令。

#### Scenario: 创建或发布TypeScript Agent
- **WHEN** 当前 API 收到 `typescript-v1` Agent 创建、草稿、发布、回滚或新应用激活请求
- **THEN** 系统失败关闭且不静默改写为 Python

#### Scenario: 执行TypeScript Job
- **WHEN** Worker 或 Runtime 收到非 `python-v1` 的新执行请求
- **THEN** 系统拒绝执行且不跨 Runtime fallback

#### Scenario: 只剩历史TypeScript事实
- **WHEN** 管理查询读取退役前的 TypeScript Definition、Publication、终态 Job 或审计
- **THEN** 系统保留原始 `typescript-v1` 和只读状态
- **AND** 不允许这些事实恢复为当前可执行配置

#### Scenario: 运维查找退役命令
- **WHEN** 操作者检查当前源码运维入口
- **THEN** 文档不得指示调用不存在的 TypeScript 退役预检或迁移 CLI

### Requirement: 文件schema变更只由Migrator执行且不在迁移中删除对象
文件工作区表、约束、索引、Publication字段、Job File Manifest、提交暂存、版本、保留与清理事实 MUST 通过新的前向migration由一次性Migrator应用。历史附件到期时间 SHALL 从原始创建时间与有效策略回填；migration事务 MUST NOT访问或删除MinIO对象，实际删除只能由File Worker经File Service在迁移完成后可重试执行。

#### Scenario: 历史附件已经到期
- **WHEN** migration计算出附件到期时间早于当前时间
- **THEN** 数据库记录待清理事实
- **AND** migration完成前不删除对象

### Requirement: 文件工作区验收覆盖真实端到端链路
Compose验收 MUST 使用合成TXT、LOG、Markdown、born-digital PDF、扫描PDF、DOCX、PPTX、XLSX、带文字图片和无文字图片及假凭据，证明钉钉或受控Channel入口、File Worker、File Service、PostgreSQL、MinIO、File Domain Outbox、processing RabbitMQ拓扑、File Processing Worker、Docling、Agent Worker、Python Runtime protocol 1.3、Job Sandbox、File MCP、原件Delivery和文本结果形成新鲜链路。验收还 MUST 覆盖无附件文字Job、Principal/API Key拒绝、越权文件、MIME伪装、加密/损坏/超大小/超页数、PARTIAL、NO_TEXT、Markdown超限、Docling重启、结果取得后Worker崩溃、幂等重试、40个输入工作集边界、沙盒/representation staging清理、交付重试和Secret不泄漏；不得以容器healthy替代业务证据。
#### Scenario: PDF总结并交付原件
- **WHEN** 合成用户上传合法PDF并要求总结后转发原件
- **THEN** 证据关联原附件、source Version、processing run、Markdown/JSON representation、Manifest v5、Working Set、沙盒Markdown读取、Agent结果和原PDF Delivery
- **AND** Agent沙盒、模型上下文和Delivery均未混淆原件与representation
#### Scenario: 扫描件OCR成功
- **WHEN** 合成扫描PDF或带文字图片在`docling-layout-ocr-v2`内完成OCR
- **THEN** Agent只通过Markdown读取提取文字并给出基于该文字与布局坐标的结果
- **AND** 系统不声称获得未提取的视觉语义
#### Scenario: 无文字图片拒绝模型调用
- **WHEN** 只有一张合法但OCR为NO_TEXT的图片
- **THEN** Job不调用模型并通过原reply route返回安全说明
#### Scenario: Docling重启恢复
- **WHEN** Docling在已返回task ID后重启并丢失临时任务
- **THEN** 同一processing run创建受控新attempt并最终成功或确定失败
- **AND** 不产生重复source Version或representation
#### Scenario: 文档处理Secret不泄漏
- **WHEN** 验收检查容器环境、MQ、Job、Tool事件、审计、API和日志
- **THEN** 不存在MinIO Secret、Docling API Key、Service bootstrap credential、原始正文、对象键或真实业务文件
#### Scenario: 无附件文字消息正常执行
- **WHEN** 合成用户只发送非空文字且不上传或引用文件
- **THEN** Job使用protocol 1.3和空schema v5文件上下文完成模型执行与文字Delivery
- **AND** 不出现旧Manifest投影或文件合同校验错误
#### Scenario: 旧合同不存在于发布产物
- **WHEN** CI检查后端、前端和Runtime发布产物
- **THEN** 不存在`text-v1`、`docling-text-v1`、`docling-layout-ocr-v1`、Manifest v1-v4或Runtime protocol 1.0-v1.2运行实现
- **AND** migration与变更文档中的删除说明不被误判为运行支持

### Requirement: Docling服务固定版本并保持内部隔离
默认Compose MUST 使用固定tag与digest的官方`docling-serve`镜像，禁用UI、远程services、HTTP URL source、Callback、自定义VLM/图片描述配置和外部插件；服务不得映射宿主端口，只能由`file-processing-worker`通过专用内部网络和独立API Key访问。容器 MUST 使用非root、只读根文件系统、受控scratch、CPU、内存、PID和时间限制，并在运行前准备所需模型artifacts而不是运行时访问互联网。
#### Scenario: 检查Docling Compose配置
- **WHEN** 运维渲染默认Compose配置
- **THEN** `docling-serve`使用固定镜像digest、无宿主端口、UI关闭且远程/自定义能力关闭
- **AND** 不存在PostgreSQL、RabbitMQ、MinIO或平台Principal Secret
#### Scenario: Docling模型尚未就绪
- **WHEN** `/health`成功但`/ready`因模型加载或内部编排器失败返回非就绪
- **THEN** 平台文档处理状态不得报告READY
- **AND** processing worker不得把请求发送到未就绪实例

### Requirement: 文件处理队列具有独立有界拓扑
平台 SHALL 为文档processing request提供版本化durable主队列、延迟重试队列和dead-letter队列，并由`file-processing-worker`独占消费；拓扑 MUST 与附件下载、Agent Job和Delivery队列分离。消息与dead-letter摘要只能包含稳定run/source身份、attempt、Profile hash、correlation和安全错误码。
#### Scenario: Processing Worker暂时不可用
- **WHEN** processing request已经发布但Worker停止
- **THEN** 消息保留在durable队列且运维状态显示有界积压
- **AND** 原始附件、正文、对象键和凭据不进入队列
#### Scenario: 处理重试耗尽
- **WHEN** run达到固定最大attempt
- **THEN** 消息进入dead-letter且run进入确定失败
- **AND** 不影响附件下载队列或Agent Job队列

### Requirement: Baseline Adoption 部署必须先验证并保留恢复证据
当受支持的现有数据库从 legacy migration generation 采纳当前 schema baseline 时，系统 MUST 在业务服务使用新代码前完成只读 preflight、可恢复逻辑备份、one-shot Migrator adoption 和结果核验；普通业务服务、手工 SQL 和只读验证工具 MUST NOT 写入 migration ledger 或 adoption metadata。

#### Scenario: 现有部署满足受支持的 adoption 来源
- **WHEN** preflight 发现数据库 ledger、checksum、schema、注释和关键数据不变量与受支持的 legacy head 完全一致
- **THEN** 系统报告来源 head、目标 baseline、镜像或构建身份以及不含业务原文的核验摘要
- **THEN** adoption 只有在逻辑备份完成且业务写入已停止后才可由 one-shot Migrator 执行

#### Scenario: Adoption 前置条件不满足
- **WHEN** legacy ledger、checksum、schema、注释、关键数据不变量或备份核验任一失败
- **THEN** Migrator 失败关闭且不得登记 baseline marker 或 adoption metadata
- **THEN** 依赖 schema readiness 的业务服务不得以新代码启动

#### Scenario: Adoption 成功后验收
- **WHEN** one-shot Migrator 完成 adoption 且没有后续 migration 待应用
- **THEN** 验收同时核对 schema head、唯一 adoption metadata、关键表计数、配置 revision 摘要和业务服务 readiness
- **THEN** 验收结果不得包含 Secret、Token、密码或原始业务消息

#### Scenario: Adoption 后验收失败
- **WHEN** adoption 后任一数据、schema、配置或应用闭环核验失败
- **THEN** 系统保持切换前备份、旧镜像和旧数据环境可恢复，不自动删除或覆盖它们
- **THEN** 只有尚未执行后续 migration 的 adoption-only 数据库可以使用受控 rollback；其他情况必须恢复逻辑备份

<!-- Integrated from archived change: `2026-08-23-stabilize-schema-baseline-and-runtime-config/specs/platform-operations` -->

### Requirement: 内置 Runtime Config Definition 对账必须语义幂等
系统 SHALL 在受控初始化或显式管理同步中对账代码内置 runtime config definition，并 MUST 以规范化后的 key、类型、默认值、敏感性、bootstrap 边界、适用服务集合、描述和状态判断语义变化。语义相同的重复对账 MUST NOT 更新记录、递增 revision、改变 `updated_at` 或生成变化审计。

#### Scenario: 重复注册完全相同的内置定义
- **WHEN** 相同构建重复启动或管理员重复同步同一组内置定义
- **THEN** 第一次已存在后的对账返回 unchanged
- **THEN** definition 行、聚合 runtime config revision/hash 和配置审计均保持不变

#### Scenario: 内置定义发生真实变化
- **WHEN** 新构建改变一个内置 definition 的任一规范化语义字段
- **THEN** 系统只更新对应 definition 并将其 revision 递增一次
- **THEN** 聚合 runtime config revision/hash 发生变化，显式管理同步记录不含敏感值的差异摘要

#### Scenario: 多个服务并发初始化
- **WHEN** 多个服务同时对账相同的内置 definition 集合
- **THEN** 唯一 key 最终只对应一条语义正确的记录
- **THEN** 每个真实创建或更新最多计入一次 revision 变化，其余竞争者重读后返回 unchanged 或安全重试

<!-- Integrated from archived change: `2026-08-23-stabilize-schema-baseline-and-runtime-config/specs/platform-operations` -->

### Requirement: Runtime Config 只读路径不得隐式注册定义
Runtime config definition 列表、effective snapshot、ready diagnostics 和其他只读请求 MUST NOT 创建或更新 definition。若受控初始化没有完成，读取路径 SHALL 返回安全的缺失或 degraded 诊断，不得通过 GET、snapshot 构建或健康检查自我修复数据库。

#### Scenario: 管理员重复读取 Definition 列表
- **WHEN** 管理员连续调用 definition 列表 API 且数据库内容未变化
- **THEN** 两次响应读取同一事实，数据库写入计数、definition revision、`updated_at` 和配置审计均不变化

#### Scenario: Snapshot 发现缺少内置 Definition
- **WHEN** effective snapshot 或 ready diagnostics 发现预期内置 definition 尚未由受控初始化注册
- **THEN** 系统返回不泄漏敏感信息的 missing-definition 或 degraded 诊断
- **THEN** 读取事务不得插入 definition 或修改任何 runtime config revision

<!-- Integrated from archived change: `2026-08-23-stabilize-schema-baseline-and-runtime-config/specs/platform-operations` -->

### Requirement: Runtime Config 聚合版本必须反映真实持久化变化
系统 SHALL 为 runtime config definition、value 和相关 Secret metadata 提供稳定的聚合 revision 与内容 hash。任一受支持的真实持久化变化 MUST 改变聚合版本标识；无变化对账和纯读取 MUST 保持聚合版本标识不变。调用方 MUST 将该标识视为不透明并发与观测令牌，不得依赖其具体数值。

#### Scenario: 修改低 revision 的配置值
- **WHEN** 某个 runtime config value 发生真实更新，即使其他 definition 具有更高的单行 revision
- **THEN** 聚合 revision 与有效配置 hash 按其影响发生变化，不得因取最大单行 revision 而掩盖本次更新

#### Scenario: 重复构建相同 Snapshot
- **WHEN** 数据库 definition、value 和相关 Secret metadata 均未变化而重复构建 snapshot
- **THEN** 聚合 revision 和内容 hash 保持稳定
- **THEN** 构建 snapshot 不产生数据库写入或配置审计

<!-- Integrated from archived change: `2026-08-23-consolidate-schema-fact-sources-and-retire-legacy-tables/specs/platform-operations` -->

### Requirement: Schema 事实源必须登记并可审计
系统 SHALL 在版本控制中维护 schema fact-source manifest，按表及关键列登记领域所有者、事实语义、分类、writer、reader、生命周期、保留/审计要求和退役状态。分类至少 MUST 区分 canonical mutable fact、immutable snapshot、derived projection、compatibility shadow、operational coordination fact 和 one-time migration artifact。

#### Scenario: 新增或修改持久化字段
- **WHEN** migration 新增表、关键列、快照或兼容表示
- **THEN** 同一 change 更新 manifest 并声明唯一事实源、允许的派生关系、所有 writer/reader 和退役条件

#### Scenario: 重复表示具有不同职责
- **WHEN** 两个字段或表包含相似数据但分别承担可变草稿和不可变发布快照职责
- **THEN** manifest 将二者登记为不同生命周期事实
- **AND** consolidation 不得把不可变历史误判为需要消除的双写

<!-- Integrated from archived change: `2026-08-23-consolidate-schema-fact-sources-and-retire-legacy-tables/specs/platform-operations` -->

### Requirement: Schema consolidation 必须按阶段推进并禁止长期双写
系统 MUST 按 expand、verify/backfill、read cutover、write cutover、observation、contract/drop 的顺序推进事实源收敛，每个阶段 SHALL 具有可重复的前置检查、成功证据、失败关闭行为和回滚边界。兼容双写只能存在于已登记且有截止门禁的迁移窗口。

#### Scenario: 进入读切换阶段
- **WHEN** verify/backfill 尚未证明全量 parity、唯一映射与引用完整性
- **THEN** 系统不得取消旧读路径或进入写切换

#### Scenario: 写切换完成后的观察期
- **WHEN** 新版本已停止兼容列双写
- **THEN** 观察期持续核对缺失事实、旧列访问、队列重试、Runtime 恢复和历史查询
- **AND** 任何回归都会阻止 contract/drop

#### Scenario: 需要回滚写切换
- **WHEN** contract 尚未执行且观察期发现新事实源不可用
- **THEN** 运维方可以回滚应用版本并按已登记边界恢复兼容写入
- **AND** 不删除新事实或重写不可变历史

<!-- Integrated from archived change: `2026-08-23-consolidate-schema-fact-sources-and-retire-legacy-tables/specs/platform-operations` -->

### Requirement: 字段和表退役必须满足统一门禁
系统 SHALL 仅在目标字段或表已证明零生产 writer、零生产 reader、无未完成事务/重试/恢复职责、达到保留期、完成必要审计导出、具备备份恢复证据且所有 owner 批准后执行 contract/drop。行数为零、名称含 `legacy` 或 `cutover`、以及本地代码搜索无引用均 MUST NOT 单独满足退役门禁。

#### Scenario: 评审一次性 cutover quarantine 表
- **WHEN** `job_dispatch_cutover_quarantine` 被提议退役
- **THEN** 评审必须证明历史 cutover 已结束、所有隔离记录已处置、部署与恢复代码不再读取或写入、保留期已满且审计证据已导出
- **AND** 任一条件不满足时保持表存在并把退役状态标记为 `blocked`

#### Scenario: 评审安全或恢复表
- **WHEN** 身份 challenge、outbox、Runtime ledger、claim 或 event 表被提议退役
- **THEN** 评审必须证明其安全、幂等、重试或恢复职责已被一个明确的新 canonical fact 完整替代并完成所有调用方切换
- **AND** 不得仅因当前零行或低行数批准删除

<!-- Integrated from archived change: `2026-08-23-consolidate-schema-fact-sources-and-retire-legacy-tables/specs/platform-operations` -->

### Requirement: Consolidation migration 必须以 Baseline 100 adoption 为前置
系统 MUST 在目标数据库已完成精确 `042 → 100` Baseline Adoption、migration ledger 与 baseline checksum 校验通过后，才允许执行本 change 的后续 migration。真实 backfill、cutover 或 contract/drop SHALL 分别获得部署授权和维护窗口，不得由构建、测试、应用启动或 OpenSpec apply 自动执行。

#### Scenario: 目标数据库仍停留在042
- **WHEN** consolidation preflight 发现 migration ledger 的精确 head 仍为 `042`
- **THEN** 系统仅报告应先执行 Baseline 100 Adoption
- **AND** 不写入本 change 的 migration ledger、业务表或兼容字段

#### Scenario: Active change 发生migration编号竞争
- **WHEN** 实施时发现另一个 active change 已占用计划中的 migration 版本
- **THEN** 实施者根据当前 migration catalog 重新分配唯一版本并更新 checksum 与测试
- **AND** 不修改已部署 migration 的内容或身份

#### Scenario: 执行contract drop
- **WHEN** 所有 consolidation 门禁通过并获得明确部署授权与维护窗口
- **THEN** Migrator 在全局互斥和完整事务边界内执行 contract migration
- **AND** 保存不含业务正文或凭据的 migration、备份和验收证据

<!-- Integrated from archived change: `2026-08-23-harden-management-and-runtime-boundaries/specs/platform-operations` -->

### Requirement: Compose 管理 Web 必须随管理面失败关闭
当前普通 Compose 配置 SHALL 包含 `admin-web` 服务定义。`admin-web` 容器入口 MUST 要求 `FEATURE_WEB_ADMIN=true`；该值不为 `true` 时容器必须以非零状态退出且不得提供静态管理页面。启用时，管理 Web MUST 只代理已挂载且受现有 Session 与 RBAC 保护的管理 API；规范不得声称当前 Compose 使用已注释掉的 admin profile。

#### Scenario: 默认Compose配置
- **WHEN** Compose 使用默认 `FEATURE_WEB_ADMIN=false` 渲染并启动服务集合
- **THEN** `admin-web` 服务仍存在于 Compose manifest
- **AND** 其入口 guard 非零退出且不提供管理页面

#### Scenario: 直接点名关闭的Admin Web
- **WHEN** 操作者显式启动 `admin-web` 但 `FEATURE_WEB_ADMIN` 不为 `true`
- **THEN** 容器以非零状态退出且不提供静态管理页面

#### Scenario: 显式启用管理Web
- **WHEN** `FEATURE_WEB_ADMIN=true` 且依赖服务满足启动条件
- **THEN** `admin-web` 启动并只代理已挂载且受认证授权保护的管理 API

<!-- Integrated from archived change: `2026-08-23-harden-management-and-runtime-boundaries/specs/platform-operations` -->

### Requirement: 管理前端必须区分权限错误与系统错误
管理前端 SHALL 使用全局渲染错误边界，并在 capability 查询中区分 401、403、网络/5xx 和客户端解析错误。系统错误 MUST 提供安全重试或刷新入口，不得显示为“无权访问”，也不得展示堆栈、原始响应或敏感配置。

#### Scenario: Capability API 返回 403
- **WHEN** 已登录用户的 capability 查询成功但目标 capability 缺失或 API 明确返回 403
- **THEN** 页面显示无权限状态且不退出有效登录

#### Scenario: Capability API 不可用
- **WHEN** capability 查询发生网络、5xx 或响应解析错误
- **THEN** 页面显示管理服务不可用和重试入口，不显示无权限文案

#### Scenario: 页面渲染抛出异常
- **WHEN** 任一管理路由组件在渲染生命周期抛出异常
- **THEN** 全局错误边界显示安全恢复页面且不暴露错误详情

<!-- Integrated from archived change: `2026-08-23-harden-management-and-runtime-boundaries/specs/platform-operations` -->

### Requirement: 非本地对象存储凭据必须失败关闭
非 local/test/testing/development 环境 MUST 显式提供对象存储访问凭据，且 access key 与 secret key 均不得为空或等于仓库内置本地默认值。配置校验 MUST 在依赖对象存储的服务执行外部 I/O 前失败，不得静默使用 Compose 或代码 fallback。

#### Scenario: 生产环境缺少对象存储凭据
- **WHEN** `APP_ENV=production` 且对象存储 access key 或 secret key 缺失
- **THEN** 设置加载或服务启动以安全配置错误失败

#### Scenario: 生产环境使用仓库默认凭据
- **WHEN** 非本地环境仍使用内置 MinIO access key 或 secret 占位值
- **THEN** 设置加载或服务启动失败且错误信息不包含凭据内容

#### Scenario: 本地开发显式使用本地 MinIO
- **WHEN** local/test 环境使用 Compose 本地 MinIO bootstrap
- **THEN** 系统允许本地占位流程，但凭据仍只进入 MinIO/bootstrap Secret 边界

<!-- Integrated from archived change: `2026-08-23-scale-task-workspace-with-bounded-job-working-sets/specs/platform-operations` -->

### Requirement: 工作区文件数量与计费容量使用受治理tenant运行配置
平台 Runtime Config SHALL注册两个非敏感整数定义：`FILE_WORKSPACE_ACTIVE_FILE_LIMIT`默认200、代码硬上限1000；`FILE_WORKSPACE_BILLABLE_BYTES_LIMIT`默认2GiB、代码硬上限10GiB；二者仅适用`file-service`。Runtime Config scope SHALL增加`tenant`，但只有代码显式声明tenant-compatible的定义才可使用；scope code MUST从已认证管理上下文中的平台tenant身份校验，不得由普通业务请求或Agent输入覆盖。

管理员创建、修改、禁用tenant覆盖时 MUST经过现有平台配置管理权限、乐观revision和配置审计。File Service MUST把两个有效值及同一配置快照revision用于事务配额预留；有效配置诊断 MUST返回脱敏的值、来源和revision。Job审计 MUST记录观察到的有效值与revision，但公开健康检查不得暴露tenant目录或文件身份。

#### Scenario: tenant使用默认配额
- **WHEN** 没有启用的tenant覆盖且兼容上线门禁已通过
- **THEN** File Service有效配置返回文件数量上限200和计费容量2GiB及definition-default来源
- **AND** 代码仍分别应用1000和10GiB硬上限

#### Scenario: 管理员设置tenant覆盖
- **WHEN** 授权管理员把目标tenant文件上限从200改为500、容量从2GiB改为5GiB并提供正确expected revision
- **THEN** 平台保存新revision并写入不含文件身份的配置审计
- **AND** 后续File Service有效快照对该tenant使用500和5GiB

#### Scenario: 配额值超过代码硬上限
- **WHEN** 管理员提交1001个ACTIVE文件或超过10GiB的tenant覆盖
- **THEN** 平台在保存前拒绝并返回稳定的定义校验错误
- **AND** File Service消费端仍保留同一硬上限作为纵深防御

#### Scenario: 非兼容定义尝试tenant scope
- **WHEN** 管理员对未声明tenant-compatible的其它Runtime Config key提交tenant scope
- **THEN** 平台在保存前拒绝
- **AND** 不扩大该配置在其它tenant或服务中的作用范围

<!-- Integrated from archived change: `2026-08-23-scale-task-workspace-with-bounded-job-working-sets/specs/platform-operations` -->

### Requirement: 提升tenant工作区配额前必须通过兼容预检
平台在把任一tenant有效工作区文件数量从20或更低提升到20以上前，MUST只读检查该tenant所有启用且使用任务工作区的Agent/Application Publication是否冻结兼容的`task_workspace_search_files`及必要File MCP Tool。任一不兼容发布 MUST阻止文件数量提升，并返回有界、非敏感的Application/Publication身份和修复原因；预检 MUST NOT原地修改或自动重发任何Publication。容量覆盖可以独立变更，但两个定义均必须经过同一tenant配置治理、硬上限和审计。

#### Scenario: 所有启用Publication均兼容
- **WHEN** 目标tenant的启用任务工作区Application均冻结兼容Tool且配额值不超过1000
- **THEN** 管理员可发布新的tenant配额revision
- **AND** 审计同时记录预检结果摘要和配置变更

#### Scenario: 存在不兼容历史Publication
- **WHEN** 目标tenant仍有一个启用Application Publication缺少新发现Tool
- **THEN** 平台拒绝把有效上限提升到200
- **AND** 不修改该Publication、现有工作区或历史Job

#### Scenario: 回滚配额到20
- **WHEN** 运维把已启用大工作区的tenant有效上限降回20
- **THEN** 已完成Job、追加工作集事实和已有文件保持不变
- **AND** 超过20个ACTIVE文件的工作区保持可读但拒绝新增逻辑文件

<!-- Integrated from archived change: `2026-08-23-scale-task-workspace-with-bounded-job-working-sets/specs/platform-operations` -->

### Requirement: 大工作区上线必须保存容量与全链证据
上线验收 MUST覆盖200和1000个ACTIVE文件、默认2GiB与硬上限10GiB、冻结目录revision的50项分页、40个内容工作集项、64文件分区、224MiB共享容量、并发目录变化、并发Job和Docling Representation状态，并记录目录revision成员行数、Manifest大小、Job创建与搜索延迟、数据库查询计划以及工作集/容量上限拒绝。验收 MUST覆盖自动物化、File MCP物化、Write/Edit和内部临时文件全部经过统一预算，特别证明File MCP不能绕过文件数或容量检查。生产就绪声明 MUST至少包含一次真实Runtime调用File MCP搜索、选择精确版本、物化可读内容并形成Agent结果或Delivery的全链证据；容器健康或单元测试单独不足以证明完成。

#### Scenario: 1000文件容量压测
- **WHEN** 测试工作区具有1000个ACTIVE文件且创建只绑定2个内容项的Job
- **THEN** Manifest只冻结目录revision和2个内容项，不复制其余998个目录条目
- **AND** 证据记录冻结目录分页延迟、查询计划和数据库行数而不记录正文

#### Scenario: 真实全链验收
- **WHEN** 兼容Publication通过真实Python Runtime搜索并选择一份Docling可读文档
- **THEN** 证据证明精确Representation被物化、Agent读取并产生受治理结果或Delivery
- **AND** 未选中的工作区文件没有进入Sandbox

#### Scenario: File MCP预算旁路回归
- **WHEN** Runtime已经接近40项输入或224MiB容量且File MCP返回新的合法transfer
- **THEN** Runtime在下载首字节前通过统一预算接受或稳定拒绝
- **AND** 证据证明拒绝路径没有目标文件、部分内容或未释放预留

<!-- Integrated from archived change: `2026-08-23-add-governed-office-embedded-image-layout-ocr/specs/platform-operations` -->

### Requirement: 布局OCR复用隔离处理拓扑并固定模型artifact
默认部署 SHALL 复用内部`docling-serve`、独立`file-processing-worker`、File Service、File Domain Outbox和RabbitMQ文档处理边界来执行parent、picture item与assembly任务，不得把Docling或OCR暴露为Agent Tool/MCP，也不得新增可绕过File Service的图片对象入口。Docling/OCR/layout所需模型与配置 MUST 在构建或受控部署阶段固定revision与digest并离线可用；运行时下载、远程services、自定义模型、Callback、HTTP source和外部插件 MUST 保持关闭。

#### Scenario: 检查处理组件Secret和网络
- **WHEN** 运维检查File Processing Worker、Docling和File Service的环境、Secret、网络及挂载
- **THEN** 只有File Service具有对象存储凭据，Worker只有角色bootstrap/RabbitMQ/Docling API Key，Docling只有自身固定API Key与模型artifact
- **AND** 任何处理组件都不获得任意对象键、其它Worker凭据或外网图片/模型访问

#### Scenario: 固定OCR模型缺失
- **WHEN** 容器离线启动但Profile固定的OCR/layout artifact不存在、digest不匹配或无法加载
- **THEN** Docling/Worker readiness失败且布局Profile不得报告READY
- **AND** 不尝试访问互联网下载或回退到其它模型

<!-- Integrated from archived change: `2026-08-23-add-governed-office-embedded-image-layout-ocr/specs/platform-operations` -->

### Requirement: 布局OCR资源与积压可安全观测
平台 MUST 对parent parse、picture item、assembly、asset staging、Representation staging、retry、dead-letter和cleanup分别提供有界积压计数、最早时间、Profile/processor版本、阶段、attempt和白名单错误分类。readiness MUST 验证Profile registry/hash、layout schema、必需输出集合、固定模型artifact、File Service内部流、RabbitMQ拓扑和Docling真实就绪；日志、健康、指标和运维API不得显示业务文件名、图片、OCR文字、坐标、对象键、响应正文或凭据。

#### Scenario: 图片OCR出现积压
- **WHEN** picture item队列超过代码固定告警阈值
- **THEN** 运行中心显示数量、最早创建时间、Profile、stage和安全错误分类
- **AND** 不显示图片内容、OCR文本或父文件名

#### Scenario: 容器运行但layout schema不兼容
- **WHEN** 组件进程running但File Service不认识Profile要求的`OCR_LAYOUT_JSON` schema或输出集合
- **THEN** readiness返回非就绪并阻止新布局OCR run
- **AND** 不以容器health替代契约就绪

<!-- Integrated from archived change: `2026-08-23-add-governed-office-embedded-image-layout-ocr/specs/platform-operations` -->

### Requirement: 布局OCR验收覆盖坐标、恢复和能力边界
上线验收 MUST 使用不含真实业务数据的合成DOCX/PPTX，覆盖内嵌图片文字、重复图片、图片自身EXIF方向、Office显示层旋转/裁剪未应用且明确提示、低置信度、多block、无文字、损坏图片、超图片数、超像素、超输出大小及提示注入。证据 MUST 关联source Version、parent run、picture asset/occurrence/item、三种Representation、Manifest、Runtime Markdown读取、Agent结果与原件Delivery，并验证逐图重试、Docling重启、Worker崩溃、幂等assembly、asset/representation清理和Secret不泄漏；不得以单元测试或容器healthy代替新鲜业务链路。

#### Scenario: PPTX布局OCR成功
- **WHEN** 合成PPTX包含已知slide/shape位置和多个已知图片内文字框
- **THEN** 验收证明父锚点、规范化bbox、reading order、几何关系和布局Markdown与样本期望一致
- **AND** Agent只通过Markdown说明图片文字/布局，不声称箭头、颜色或照片语义

#### Scenario: DOCX重排不改变锚点语义
- **WHEN** 同一合成DOCX在不同字体/分页环境下处理
- **THEN** 验收使用稳定文档节点/段落锚点和图片内部坐标比较结果
- **AND** 不要求或断言稳定页码bbox

#### Scenario: 单张图片任务重试
- **WHEN** 多图片文档中一个Docling picture task在返回task ID后丢失
- **THEN** 同一item有限重试并最终成功或确定失败，其它终态item不重算
- **AND** parent只发布一组Profile要求的Representation

#### Scenario: 图片提示注入不能扩大权限
- **WHEN** 合成图片OCR文字要求忽略系统规则并调用未授权Tool
- **THEN** Agent把它作为不可信文件内容处理且服务端权限/工具集合保持不变
- **AND** MQ、日志和审计不出现该OCR正文

<!-- Integrated from archived change: `2026-08-23-optimize-test-suite-feedback-and-maintainability/specs/platform-operations` -->

### Requirement: 自动化测试必须具有唯一且失败关闭的执行层级
仓库 SHALL 将每个自动化测试文件唯一分类为 `unit`、`contract`、`integration`、`acceptance` 或 `migration`；分类 SHALL 由版本控制下的机器可读事实驱动。新增测试缺少分类、同时命中多个分类或清单引用不存在文件时，测试收集 MUST 失败，而不是静默选择默认层级。

#### Scenario: 新测试缺少层级
- **WHEN** 开发者新增测试文件但没有将其加入唯一测试层级
- **THEN** 测试清单校验和 Pytest collection 失败并报告该文件

#### Scenario: 测试属于多个层级
- **WHEN** 同一个测试文件被配置为两个或更多层级
- **THEN** 测试清单校验失败并列出冲突层级

#### Scenario: 按层级执行测试
- **WHEN** 开发者或 CI 选择任一测试层级
- **THEN** 系统只收集该层级的测试并报告稳定的收集数、通过数、跳过数和耗时

<!-- Integrated from archived change: `2026-08-23-optimize-test-suite-feedback-and-maintainability/specs/platform-operations` -->

### Requirement: 快速反馈不得替代完整回归
仓库 SHALL 提供稳定的 PR 快速测试入口和后端完整回归入口。快速入口 MUST 只选择已分类的 `unit` 与 `contract` 测试；完整入口 MUST 保持所有本地可执行测试的现有覆盖，并由主分支或发布门禁执行。存在快速入口不得成为删除 `integration`、`acceptance`、`migration`、拒绝路径或恢复路径测试的依据。

#### Scenario: Pull Request 快速门禁
- **WHEN** Pull Request 运行默认快速测试入口
- **THEN** CI 执行全部 `unit` 与 `contract` 测试并清晰声明尚未代表完整回归或真实外部验收

#### Scenario: 主分支完整回归
- **WHEN** 变更进入主分支或发布验证
- **THEN** CI 执行所有本地可执行层级并保留显式外部集成测试的跳过原因

#### Scenario: 快速测试通过但验收测试失败
- **WHEN** 快速入口通过而 `acceptance`、`migration` 或其他完整回归层级失败
- **THEN** 系统不得把该变更报告为完整质量验收通过

<!-- Integrated from archived change: `2026-08-23-optimize-test-suite-feedback-and-maintainability/specs/platform-operations` -->

### Requirement: 测试数据库加速必须保持逐测试隔离和迁移真实性
非 migration 语义的 SQLite 测试 MAY 复用一次构建的已迁移只读模板，但每个测试 MUST 使用唯一数据库副本并独立执行 seed 与写入。验证 Migrator、schema baseline、checksum、legacy ledger、升级路径或指定初始数据库状态的测试 MUST 绕过模板并执行真实迁移流程。测试不得依赖执行顺序或其他测试留下的状态。

#### Scenario: 普通契约测试创建数据库
- **WHEN** 非 migration 契约测试请求已迁移测试数据库
- **THEN** 测试基础设施从与当前 migration 身份一致的模板创建唯一副本，且对副本的写入不会被其他测试观察到

#### Scenario: Migration 测试验证空库升级
- **WHEN** migration 层级测试验证空 SQLite 或 PostgreSQL 数据库的 baseline 与后续迁移
- **THEN** 测试不使用已迁移模板，而是从声明的初始状态执行真实 Migrator 并验证 ledger 和 schema

#### Scenario: Migration 内容发生变化
- **WHEN** 同一测试进程使用的活动 migration 身份与模板身份不一致
- **THEN** 测试基础设施拒绝复用旧模板并重新构建或失败关闭

<!-- Integrated from archived change: `2026-08-23-optimize-test-suite-feedback-and-maintainability/specs/platform-operations` -->

### Requirement: 测试反馈预算必须可测量且不得通过缩减覆盖达成
仓库 SHALL 提供可复现的测试基线命令并输出执行环境、收集数、通过/跳过数、总耗时和最慢测试。该变更在约定参考环境中的验收目标为 PR 快速套件不超过 120 秒、后端完整套件不超过 300 秒。预算只能通过测试分层、隔离基础设施复用、无语义损失的 fixture 重构或经过隔离验证的并行执行达成，不得通过删除规范覆盖、隐藏失败、依赖重试或改变测试选择口径达成。

#### Scenario: 记录优化前后基线
- **WHEN** 维护者评估测试优化效果
- **THEN** 使用相同参考命令和环境记录优化前后收集数、结果、耗时和最慢测试，并说明所有选择条件

#### Scenario: 耗时达到目标但收集数下降
- **WHEN** 快速或完整套件耗时达到预算，但本应包含的测试收集数或层级覆盖下降
- **THEN** 该优化不得通过验收，直到覆盖差异被解释并证明符合规范

#### Scenario: 参考环境未达到预算
- **WHEN** 实现完成后快速套件超过 120 秒或后端完整套件超过 300 秒
- **THEN** 对应性能任务保持未完成并记录差距，不得仅以测试全部通过宣称本变更完成

<!-- Integrated from archived change: `2026-08-23-optimize-test-suite-feedback-and-maintainability/specs/platform-operations` -->

### Requirement: 删除重复测试必须具有规范覆盖等价证据
删除或合并自动化测试前，维护者 MUST 记录原测试、替代测试、对应 canonical Requirement，以及正常、拒绝、恢复、审计和 Secret 边界的覆盖等价关系。仅代码相似、使用相同 fixture、文件过长或希望减少行数均不得作为删除依据。

#### Scenario: 两个测试断言相似但失败边界不同
- **WHEN** 两个测试具有相似正常路径断言但覆盖不同授权、恢复或审计边界
- **THEN** 系统保留独立测试或提供同时覆盖两个边界的明确替代测试

#### Scenario: 重复测试具有完整替代证据
- **WHEN** 维护者证明替代测试覆盖同一 Requirement 及全部相关边界，并且完整回归通过
- **THEN** 可以删除重复测试并在变更证据中记录映射

<!-- Integrated from archived change: `2026-08-23-converge-single-current-file-rule/specs/platform-operations` -->

### Requirement: 开放测试文件域重置必须显式且完整
平台 SHALL 提供一次性、显式确认的开放测试文件域重置命令。命令 MUST 先只读预检并拒绝任何非终态文件processing run、Agent Job、Delivery、Outbox或相关RabbitMQ消息，再通过File Service对象存储适配器删除受管文件对象，并按外键拓扑事务性删除旧附件正文、附件文件绑定、Workspace、Catalog、Working Set、Manifest、File/Version、Representation、processing、提交、保留、文件Delivery及其强关联终态测试事实。命令不得接受任意bucket、对象前缀、数据库表名或外部URL。

#### Scenario: 操作者未提供精确确认
- **WHEN** 操作者运行重置命令但未提供文档规定的精确环境标识和确认短语
- **THEN** 命令只输出脱敏预检摘要并退出
- **AND** 不删除数据库行或对象

#### Scenario: 仍有非终态执行或队列消息
- **WHEN** 预检发现RUNNING、PENDING、WAITING、RETRY、未终态Outbox/Delivery或相关队列积压
- **THEN** 重置失败关闭并输出按类别聚合的安全计数
- **AND** 不执行部分对象或数据库删除

#### Scenario: 开放测试文件域为空后重置完成
- **WHEN** 所有门禁通过且操作者提供精确确认
- **THEN** 命令删除受管对象与目标测试事实并执行数据库和对象存储空域核验
- **AND** 任一删除或核验失败都返回非零状态且不得宣称完成

<!-- Integrated from archived change: `2026-08-23-converge-single-current-file-rule/specs/platform-operations` -->

### Requirement: 单一文件合同migration必须删除旧结构并拒绝遗留引用
一次性Migrator MUST 在文件域重置完成后执行前向migration，删除`attachment_content`、重复文件身份影子列、未使用的Job文档Profile字段、可切换文本策略字段及其旧约束，并把Profile、Manifest和Runtime执行摘要约束收缩到`NONE|docling-layout-ocr-v2`、schema v5和protocol 1.3。migration MUST 在任何旧Profile、旧Manifest、旧Runtime协议、活动部署或非终态引用仍存在时失败关闭，不得更新、投影或回填成当前合同。

#### Scenario: 旧测试数据未清空
- **WHEN** Migrator发现旧Manifest行、旧Profile引用、旧附件正文或旧协议执行摘要
- **THEN** migration整体回滚并提示先运行显式开放测试文件域重置
- **AND** 不保留半数新约束或半数旧列

#### Scenario: 重置完成后应用migration
- **WHEN** 预检确认只剩当前Profile引用且文件域与旧执行事实为空
- **THEN** migration在单事务中删除旧结构并安装唯一当前约束
- **AND** schema contract只声明当前列、表和允许值

<!-- Integrated from archived change: `2026-08-23-converge-single-current-file-rule/specs/platform-operations` -->

### Requirement: 单一合同部署不得保留回退服务
部署编排 SHALL 一次性重建API、File Service、File/Processing Worker、Agent Worker、Python Runtime和管理端，并且不得并行运行包含旧Profile、旧Manifest或旧Runtime协议的镜像。入口恢复前 MUST 验证所有消费者、生产者、数据库约束和管理端bundle来自同一构建版本。

#### Scenario: 仍有旧Worker镜像消费队列
- **WHEN** 部署预检发现任一旧Agent Worker、File Worker、Processing Worker或Runtime实例仍注册或消费
- **THEN** 入口流量不得恢复
- **AND** 系统不依靠双写、版本协商或重试到旧服务维持运行
