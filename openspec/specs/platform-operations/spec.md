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

<!-- Reconciled from mcp_new capability: `platform-runtime-acceptance` -->

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

<!-- Reconciled from mcp_new capability: `canonical-baseline-governance` -->

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
默认Compose SHALL 新增`file-service`并用`file-worker`替换现有`attachment-worker`服务，不长期并存两个附件消费者，也不新增独立`file-mcp`容器。`file-service`同时承载内部REST与File MCP接口；`file-worker`继续消费原附件队列并承担附件导入、工作区过期、保留内容和提交暂存清理；现有Delivery Dispatcher继续独立运行。

#### Scenario: 从现有部署升级
- **WHEN** 现有附件队列中存在ready或unacked消息并部署新版本
- **THEN** `file-worker`使用兼容队列声明继续消费
- **AND** 不因服务名变化删除队列、丢失消息或重复导入附件

#### Scenario: Compose服务清单检查
- **WHEN** 运维启动默认文件工作区部署
- **THEN** 服务包含`file-service`和`file-worker`且不包含独立`file-mcp`或长期`attachment-worker`

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
File Service readiness MUST 验证PostgreSQL schema、MinIO私有bucket访问、Principal JWKS、Manifest和内部流式接口依赖；File Worker readiness MUST 验证RabbitMQ队列契约、File Service内部API和清理调度可用性。平台运维视图 SHALL 展示附件、提交暂存、工作区过期、保留清理和 File Domain Outbox 的安全积压计数与最近结果，不得仅以容器running声明可用。

#### Scenario: MinIO进程可达但bucket无权限
- **WHEN** File Service能连接MinIO endpoint但无法读取或写入受控bucket
- **THEN** readiness返回失败并阻止文件能力被宣称为已接线

#### Scenario: File Worker存在清理积压
- **WHEN** 到期内容因瞬时错误等待重试
- **THEN** 运维状态显示有界积压、最早到期时间和安全错误分类
- **AND** 不显示文件名、正文、对象键或凭据

#### Scenario: File Domain Outbox存在待发布事件
- **WHEN** 附件导入或文件版本事务已提交领域事件但维护发布尚未完成
- **THEN** File Worker维护链路将安全事件投影到统一审计并把Outbox标记为`PUBLISHED`
- **AND** 运维状态显示待发布数量、最早事件时间和安全失败码，不显示文件名、正文、对象键或凭据

#### Scenario: 历史Outbox积压升级后恢复
- **WHEN** 升级前已有长期`PENDING`文件领域事件
- **THEN** 下一次维护周期按确定顺序幂等发布并清空积压
- **AND** 不创建无人消费的RabbitMQ队列或重复文件版本

### Requirement: Compose完整配置Service Principal签发与刷新链路
默认Compose MUST 只维护一套平台Principal签名私钥和公开JWKS：现有平台API身份模块与Agent Worker只在需要签发对应Token时挂载同一私钥，File Service、ONES MCP及后续MCP只挂载同一公开`PRINCIPAL_JWKS`；不得声明或挂载第二套Service Principal私钥/JWKS。平台API还 MUST 挂载角色隔离的File Worker、Delivery Worker bootstrap credential，并让每个Worker只挂载自己的bootstrap credential。部署 MUST 使用按需签发和到期前刷新，不得要求宿主机预先提供短时Service JWT文件。密钥初始化 MUST 幂等生成统一Principal密钥/JWKS与bootstrap材料、拒绝不完整统一密钥组并保持私钥和bootstrap文件owner-only。

#### Scenario: 新环境首次启动
- **WHEN** 运维运行受控密钥初始化后启动默认Compose
- **THEN** 统一Principal密钥/JWKS及所有Service Principal bootstrap bind source均存在且容器可创建
- **AND** File Worker和Delivery Worker能从平台身份接口取得可验证的角色JWT

#### Scenario: 检查角色Secret挂载
- **WHEN** 运维检查API、File Service、File Worker与Delivery Worker的Compose Secret
- **THEN** API拥有统一Principal签名私钥和两份bootstrap credential，File Service只有统一公开JWKS
- **AND** 每个Worker只有自己的bootstrap credential且没有签名私钥、JWKS或另一角色Secret

#### Scenario: 短时JWT到期
- **WHEN** 已缓存Service JWT进入刷新窗口或过期
- **THEN** Worker通过固定平台身份地址换取新JWT并继续调用
- **AND** 不回退到静态JWT、共享Token或未认证内部请求

### Requirement: Job Sandbox容量和隔离配置必须可验证
Python Runtime 的临时文件系统配置 MUST 支持第一阶段 15 MiB 单文件与受控多文件物化，并对每个 Job 实施独立沙盒容量、文件数量、路径和生命周期限制。Compose MUST 不再使用无法容纳一个合法输入及安全处理开销的 32 MiB 无差别配置；实际容量必须由受控部署配置决定、在启动时校验并在健康状态中只显示非敏感上限。

#### Scenario: 沙盒容量小于合法最小处理需求
- **WHEN** Runtime 配置无法容纳一个 15 MiB 输入、对应输出和必要临时开销
- **THEN** Runtime readiness 失败而不是在 Agent 执行中无界磁盘失败

#### Scenario: 单Job达到沙盒上限
- **WHEN** 继续物化或生成文件会超过当前 Job 沙盒容量
- **THEN** Runtime 在写入前拒绝并返回安全、有界错误

### Requirement: TypeScript Runtime退役必须经过显式运行态门禁
平台 MUST 在删除 TypeScript Runtime 服务、客户端或部署配置前，对每个目标环境执行只读预检并保存脱敏证据。预检 MUST 覆盖 TypeScript Agent Definition/Publication、Application revision/deployment、非终态 Job、retry/outbox/queue、模型探测配置和运行依赖；任一未解析执行事实 MUST 阻止删除阶段。

#### Scenario: 存在活动TypeScript应用引用
- **WHEN** 任一环境仍有 deployment 指向引用 `typescript-v1` Agent Publication 的 Application Publication
- **THEN** 退役门禁失败并要求创建、发布和显式激活 Python 替代版本

#### Scenario: 存在非终态TypeScript Job
- **WHEN** 任一 `typescript-v1` Job 仍处于 PENDING、RUNNING、RETRY_WAIT 或其它可继续执行状态，或队列中仍有对应消息
- **THEN** 系统不得删除 TypeScript Runtime、改写 runtime kind 或跨 Runtime fallback
- **AND** Job 必须按原 Runtime 排空、取消或进入确定终态

#### Scenario: 只剩历史TypeScript事实
- **WHEN** 所有环境不存在活动引用和非终态 TypeScript Job，但仍有历史 Definition、Publication、终态 Job 或审计
- **THEN** 平台允许删除 TypeScript 运行服务，同时保留这些事实的原始 runtime kind 和只读查询能力

#### Scenario: 预检无法覆盖目标环境
- **WHEN** 退役工具无法读取任一目标数据库、队列或部署状态
- **THEN** 门禁失败且不得用当前本地环境的零计数替代未知环境证据

### Requirement: 文件schema变更只由Migrator执行且不在迁移中删除对象
文件工作区表、约束、索引、Publication字段、Job File Manifest、提交暂存、版本、保留与清理事实 MUST 通过新的前向migration由一次性Migrator应用。历史附件到期时间 SHALL 从原始创建时间与有效策略回填；migration事务 MUST NOT访问或删除MinIO对象，实际删除只能由File Worker经File Service在迁移完成后可重试执行。

#### Scenario: 历史附件已经到期
- **WHEN** migration计算出附件到期时间早于当前时间
- **THEN** 数据库记录待清理事实
- **AND** migration完成前不删除对象

### Requirement: 文件工作区验收覆盖真实端到端链路
Compose验收 MUST 使用合成TXT和假凭据证明钉钉或受控Channel入口、File Worker、File Service、PostgreSQL、MinIO、RabbitMQ、Agent Worker、所选Runtime、Job Sandbox、File MCP、版本提交、Delivery Outbox和钉钉交付形成新鲜链路。验收还 MUST 覆盖Principal拒绝、越权文件、UTF-8/大小/配额拒绝、版本冲突、幂等重试、沙盒清理、暂存清理、交付重试和Secret不泄漏；不得以容器healthy替代业务证据。

#### Scenario: TXT修改成功
- **WHEN** 合成用户上传合法TXT并要求修改
- **THEN** 证据关联原附件、工作区、Job清单、沙盒物化、Commit ID、新版本、Delivery和最终回复
- **AND** 全链路不包含真实Secret或业务文件

#### Scenario: 版本冲突验收
- **WHEN** 两个合成Job基于同一版本提交不同内容
- **THEN** 只有一个成为当前版本，另一个成为冲突候选
- **AND** 两个Job与每个提交结果均可审计
