# platform-operations Specification

## Purpose
定义平台配置、Secret、Migration、Compose、测试环境、运行验收及 canonical 规格读取治理。

## Requirements

<!-- Migrated from canonical source capability: `agent-test-data-environment` -->

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

### Requirement: 拓扑定义两个数据库基地及各自 Redis
`backend/config/internal_platform_topology.example.yaml` SHALL 增加 `agent_test` 环境，并定义 `mysql`、`sqlserver` 两个无车间分层基地。每个基地 SHALL 配置对应数据库引擎和一个独立 standalone Redis 连接，所有主机、用户和密码 SHALL 通过 `secret://agent_test/...` 引用解析，不得在 YAML 中出现明文凭据。

#### Scenario: 解析 MySQL 测试基地
- **WHEN**平台解析 `environment=agent_test`、`base=mysql`
- **THEN** 它解析到 MySQL 测试数据库和 MySQL 基地专用 Redis
- **THEN** 返回给 Agent 的拓扑摘要不包含主机、端口、用户名或密码

#### Scenario: 不允许跨基地 Redis 绑定
- **WHEN** 平台分别解析 `agent_test/mysql` 和 `agent_test/sqlserver`
- **THEN** 两个资源绑定使用两个不同的 Redis 服务主机

### Requirement: 环境变量模板覆盖运行与播种凭据
`.env.example` SHALL 声明测试镜像、宿主端口、数据库初始化凭据、只读运行凭据、两个 Redis 的只读凭据及播种凭据，并使用明显的本地占位值；本地 `.env` SHALL 提供可运行配置。Compose SHALL 只向需要相应凭据的服务传递变量，不得把数据库管理凭据传给 Internal API Platform 或 Agent Worker。

#### Scenario: Internal API Platform 连接测试基地
- **WHEN** Internal API Platform 通过 topology secret ref 解析测试基地
- **THEN** 它只获得该基地的只读数据库凭据和只读 Redis 凭据
- **THEN** 数据库管理凭据与 Redis 播种用户凭据不出现在其环境中

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


<!-- Migrated from canonical source capability: `compose-infrastructure-major-upgrade` -->

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


<!-- Migrated from canonical source capability: `db-backed-config-compose-smoke` -->

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


<!-- Migrated from canonical source capability: `feature-configuration-simplification` -->

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


<!-- Migrated from canonical source capability: `platform-config-api` -->

### Requirement: Platform configuration API exposes topology management
系统 SHALL 提供 Web 配置平台使用的 REST API，用于管理环境、基地、车间、稳定 Resource Identity、Resource Draft、验证结果、不可变 Revision、应用发布绑定和 Secret reference。

#### Scenario: List topology
- **WHEN** 管理端请求平台 topology 列表
- **THEN** 系统返回启用和禁用的环境、基地、车间以及必要的分页或过滤信息

#### Scenario: Create resource draft
- **WHEN** 管理端为某作用域提交合法的 DB、Redis 或 Loki Draft
- **THEN** 系统保存 Draft、写入配置审计，并明确返回 DRAFT、published 与 effective 状态

#### Scenario: Bind resource revision
- **WHEN** 业务应用发布选择一个可用 Resource Revision
- **THEN** 系统保存具体 revision binding，而不是浮动 Resource Identity

### Requirement: Platform configuration API validates domain invariants
系统 SHALL 在保存配置前校验领域约束，包括编码唯一性、父子关系存在、资源类型合法、secret ref 合法、只读工具边界和配置 JSON schema。

#### Scenario: Duplicate environment code rejected
- **WHEN** 管理端创建已存在编码的环境
- **THEN** 系统拒绝请求并返回冲突错误

#### Scenario: Invalid workshop parent rejected
- **WHEN** 管理端创建车间但指定不存在的基地
- **THEN** 系统拒绝请求并返回校验错误

#### Scenario: Mutation tool binding rejected
- **WHEN** 管理端试图为 MVP 诊断流程启用写库、删 Redis 或重启服务类工具
- **THEN** 系统拒绝保存配置，因为第一版只允许只读诊断工具

### Requirement: YAML topology import upserts database configuration
系统 SHALL 将 YAML import 限定为 bootstrap 或显式迁移操作；导入结果只能创建或更新 PostgreSQL topology 与 Resource Draft，MUST NOT 自动发布或覆盖现有 Published Revision。

#### Scenario: Import new yaml topology
- **WHEN** 授权管理员导入包含新环境、基地、车间和资源配置的 YAML
- **THEN** 系统创建对应 topology 与 Draft，返回 created、updated、skipped 和 requires-secret-migration 统计

#### Scenario: Import existing yaml topology
- **WHEN** 相同稳定编码和内容被再次导入
- **THEN** 系统幂等处理，不创建重复对象或 Published Revision

#### Scenario: Import attempts to overwrite published resource
- **WHEN** YAML 内容与现有 Published Revision 不同
- **THEN** 系统创建新 Draft 并要求重新验证、发布，不得直接改变有效运行时

### Requirement: API exposes runtime topology snapshot
系统 SHALL 提供只读 snapshot API，展示 PostgreSQL 中当前 published/effective Resource Revision、应用 binding、runtime generation、Last Known Good 和安全错误摘要。

#### Scenario: Snapshot from database
- **WHEN** PostgreSQL 中存在已发布且成功装载的 topology 与资源
- **THEN** snapshot API 返回 source 为 database，并同时标明 published revision 与 effective revision

#### Scenario: Snapshot validation error
- **WHEN** Published Revision 缺少可解析 Secret 或运行时无法装载
- **THEN** snapshot API 返回 degraded/blocked 状态和脱敏错误，不得静默回退 YAML

### Requirement: API responses do not leak secret values
系统 SHALL 确保所有平台配置 API 响应只返回 secret reference 元数据，MUST NOT 返回任何解析后的真实密钥值。

#### Scenario: Get resource binding with credential
- **WHEN** 管理端查询带数据库密码引用的资源绑定
- **THEN** 系统只返回 `secret_ref` 编码或引用，不返回真实密码

#### Scenario: Export topology snapshot
- **WHEN** 系统导出 topology snapshot
- **THEN** snapshot 中的 credential 字段仍然是 secret reference，不包含明文 token 或 password

### Requirement: Imported topology can be verified as runtime-ready
系统 SHALL 让通过 YAML import 或平台配置 API 写入的 topology 能被验证为 Internal API Platform 可消费的 runtime snapshot。

#### Scenario: YAML import produces database snapshot
- **WHEN** 管理端导入合法 topology YAML 到 PostgreSQL
- **THEN** `/api/platform/topology-snapshot` 返回 source 为 database 或可被运行时加载的 DB-backed snapshot，并包含启用资源数量和访问授权摘要

#### Scenario: Imported topology has validation errors
- **WHEN** 导入后的启用资源绑定缺少运行时必须字段
- **THEN** snapshot API 返回配置错误详情，并且不得把该配置标记为 runtime valid

### Requirement: Platform configuration API supports runtime verification workflow
系统 SHALL 提供足够的只读 API 输出，让开发者或后续 Web 平台确认当前 DB 配置能驱动只读诊断工具。

#### Scenario: Verify effective topology
- **WHEN** 开发者查询平台 topology snapshot
- **THEN** 响应包含启用 environment/base/workshop、resource binding 作用域、resource kind、secret reference 摘要和配置 revision/hash

#### Scenario: Verify disabled resource exclusion
- **WHEN** 管理端禁用某个 resource binding 后查询 topology snapshot
- **THEN** snapshot 不包含该禁用资源，且 revision/hash 发生可观测变化

### Requirement: Platform configuration API documents restart or reload semantics
系统 SHALL 文档化基于 revision 轮询、完整快照构建、原子切换和 Last Known Good 的热加载语义。

#### Scenario: 新 revision 成功激活
- **WHEN** Internal API Platform 检测到可装载的新 Published Revision
- **THEN** 新请求使用新 generation，进行中请求继续使用其已捕获的旧 generation

#### Scenario: 新 revision 激活失败
- **WHEN** 新快照构建失败
- **THEN** 文档和 API 明确显示 published 不等于 effective，并保留 Last Known Good

### Requirement: Platform API accepts secret values through write-only fields
系统 SHALL 提供平台密钥管理 API，允许管理端通过 write-only 字段提交 secret 明文值，并只返回 secret ref、状态和脱敏摘要。

#### Scenario: Create secret through API
- **WHEN** 管理端调用 secret 创建接口并提交明文 value
- **THEN** API 返回 secret metadata 和 `secret_ref`，响应中不包含明文 value

#### Scenario: Read secret through API
- **WHEN** 管理端查询 secret 详情
- **THEN** API 返回 configured/version/updated_at/masked_summary，不返回明文 value

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

### Requirement: Resource API 必须实施技术发布门禁
Resource API MUST 在发布前校验字段 schema、`secret://platform/` 引用、连接、只读账号、Provider 可用性和当前 Draft digest；本次不要求审核审批。

#### Scenario: 单个授权发布者发布
- **WHEN** 用户具备发布权限且 Draft 为当前 VERIFIED 内容
- **THEN** 系统可以直接创建不可变 Published Revision 并审计

#### Scenario: Draft 在验证后被修改
- **WHEN** Draft digest 与最近验证结果不一致
- **THEN** 发布必须拒绝并要求重新验证

### Requirement: 破坏性资源重置不得暴露为普通 CRUD
全量资源重置 MUST 只通过受控维护 CLI 的 report/prepare/apply/verify 执行，普通 Web/API 删除不得物理删除 Published Revision。

#### Scenario: 管理员从页面删除已发布资源
- **WHEN** 管理员对 Published Resource 使用普通删除操作
- **THEN** API 必须拒绝，并提供 disable/archive 语义


<!-- Migrated from canonical source capability: `platform-config-registry` -->

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
- **THEN** 后续 topology snapshot MUST 不包含该车间的启用资源映射

### Requirement: Resource bindings are persisted by scope
系统 SHALL 通过 Application Publication 的不可变 Mapping 在 PostgreSQL 中持久化 DB、Redis、Loki 等逻辑资源槽绑定；一个 slot MUST 支持 1..N 条 `业务目标范围 + 可选 placement → 精确 Resource Revision + 适用策略 Revision` 映射，并 MUST 在发布时拒绝缺失、重叠或歧义组合。

#### Scenario: Bind database to base
- **WHEN** 管理端为一个 Base 的数据库 slot 选择 Published Resource Revision
- **THEN** 系统在新 Application Publication 中保存精确 revision，并允许其 Workshop 后代通过各自 Published Partition Policy 继承

#### Scenario: Bind cloud and edge resources
- **WHEN** 同一逻辑目标的一个 slot 配置 cloud 和 edge 两个 Published Resource Revision
- **THEN** 系统保存两条 placement 不同的不可变 Mapping

#### Scenario: Bind global Loki to environment policy
- **WHEN** 应用使用 global Loki 查询一个 Environment
- **THEN** 系统保存精确 Loki Resource Revision 和该 Environment 的 Published Loki Scope Policy Revision

#### Scenario: Binding resolves ambiguously
- **WHEN** 环境级和基地级 Mapping 在同一 slot、placement 下同时覆盖一个有效叶子目标
- **THEN** Application Publish 拒绝且不保存部分 Publication

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
系统 SHALL 为 topology、Resource Revision、Application Resource Mapping、Workshop Partition Policy 和 Loki Scope Policy 暴露规范化 revision 或 hash，用于证明 runtime snapshot 与 Application Publication 及 Job Snapshot 一致。

#### Scenario: Configuration changes revision
- **WHEN** Environment/Base/Workshop、资源映射或任一策略发布新的不可变 revision
- **THEN** 对应 Draft 或新 Publication 的 revision/hash 发生变化，既有 Publication hash 保持不变

#### Scenario: Runtime reports revision
- **WHEN** Internal API Platform 从 Job Snapshot 解析一次工具调用
- **THEN** 运行状态和审计包含 Publication、Resource 与 Policy 的 ID/revision/hash 摘要

#### Scenario: Resource draft changes only
- **WHEN** 管理员修改尚未发布的 Resource 或 Policy Draft
- **THEN** 既有 Published 和 Effective revision/hash 不发生变化

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

### Requirement: Registry must separate resource, policy and publication lifecycle state
Registry MUST 分别持久化 Resource/Policy Draft、Verification Evidence、不可变 Published Revision、Application Publication Binding 和 Runtime Effective 状态；任何一个状态不得被另一个状态覆盖或合并成单一 `enabled` 字段。

#### Scenario: Published resource is not effective
- **WHEN** Resource Revision 已发布但运行时装载失败
- **THEN** Registry 查询同时返回 Published Revision 与不同的 Effective/health 状态，不误报为已生效

#### Scenario: Policy draft changes after verification
- **WHEN** Workshop 或 Loki Policy Draft 的规范化内容变化
- **THEN** 旧 Verification Evidence 失效，但上一 Published Revision 和依赖 Job 保持不变

### Requirement: Resource Identity 与 Resource Revision 生命周期必须独立管理
系统 SHALL 分别管理稳定 Resource Identity 的 `enabled`、`disabled`、`archived` 状态和不可变 Resource Revision 的 `PUBLISHED`、`DISABLED`、`ARCHIVED` 状态；Revision 生命周期动作 MUST NOT 隐式改写 Identity，管理 API 和界面 MUST 分开展示并筛选两层状态。

#### Scenario: 归档最新 Resource Revision
- **WHEN** 管理员把一个 Loki Resource 的最新 Revision 从 DISABLED 归档
- **THEN** 该 Revision 变为 ARCHIVED，Resource Identity 保持 enabled，并仍可显式从该历史 Revision 复制新 Draft

#### Scenario: 停用 Resource Identity
- **WHEN** 管理员使用当前 Identity revision 显式停用一个 enabled Resource Identity
- **THEN** Identity 变为 disabled，后续创建、保存、验证和发布 Draft 均被阻止，但既有 Resource Revision、Application Publication 和 Job Snapshot 不被改写

#### Scenario: 恢复 Resource Identity
- **WHEN** 管理员使用当前 Identity revision 显式恢复一个 disabled Resource Identity
- **THEN** Identity 变为 enabled 并允许后续 Draft 管理，历史 Revision 状态保持不变

#### Scenario: 安全归档 Resource Identity
- **WHEN** disabled Identity 没有活动 Draft、没有 PUBLISHED Revision 且没有活动 Application Publication 引用
- **THEN** 管理员可以用当前 Identity revision 把它归档为不可恢复终态并记录审计

#### Scenario: Identity 仍有治理依赖
- **WHEN** 管理员尝试归档仍有活动 Draft、PUBLISHED Revision 或活动 Application Publication 引用的 Identity
- **THEN** 系统失败关闭并返回不含 Secret 的依赖摘要，不改变 Identity 或任何 Revision

#### Scenario: Identity 并发状态已变化
- **WHEN** 生命周期请求携带的 expected Identity revision 已过期
- **THEN** 系统以并发冲突拒绝请求，要求刷新后重试

### Requirement: Registry must enforce optional placement representation
Registry SHALL 只在资源实际存在物理位置差异时保存 `cloud` 或 `edge` placement；无 placement 的 Mapping MUST 保存为缺省值而非字符串占位，并且同一 Mapping 不得同时包含多个 placement。

#### Scenario: Save non-placement resource
- **WHEN** 管理端保存一个没有云边差异的 Redis Mapping
- **THEN** Registry 持久化缺省 placement 并拒绝 `none`、`standalone` 或 `default`

#### Scenario: Save one placement value
- **WHEN** 管理端保存 edge Resource Mapping
- **THEN** Registry 只保存枚举值 `edge`，不把它写入 Environment/Base/Workshop code


<!-- Migrated from canonical source capability: `platform-runtime-acceptance` -->

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


<!-- Migrated from canonical source capability: `platform-runtime-config` -->

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


<!-- Migrated from canonical source capability: `platform-schema-migration-runtime` -->

### Requirement: 只有一次性 Migrator 可以修改平台 schema
系统 MUST 由独立 one-shot Migrator 应用 schema migration；API、Worker、Dispatcher 和 Internal API Platform MUST NOT 在自身启动或请求处理中执行 migration。

#### Scenario: Compose 启动平台
- **WHEN** Docker Compose 启动新版本平台
- **THEN** Migrator 必须先成功退出，业务服务随后才可启动

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


<!-- Migrated from canonical source capability: `platform-secret-management` -->

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
- **THEN** 相关资源必须重新装载失败或进入 MISCONFIGURED，并保留 Last Known Good 行为


<!-- Migrated from canonical source capability: `safe-real-model-tool-testing` -->

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
- **WHEN** 开发者只需要验证真实 Loki/Internal API Platform 链路
- **THEN** 文档 SHALL 提供 `FEATURE_REAL_CLAUDE=false` 的测试路径

<!-- Migrated from baseline governance: `rebuild-canonical-spec-baseline` -->

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
基线重建 SHALL 保留 `openspec/changes/archive/` 下的历史内容，不得为了减少默认上下文而删除或改写既有 archive。默认规范解析 MUST 排除 archive；历史内容只有在显式追溯时才参与证据分析。

#### Scenario: 重建 Canonical Baseline
- **WHEN** 维护者替换或重组主规格文件
- **THEN** 既有 archive 的目录、proposal、design、tasks、delta specs 和 evidence 保持不变

#### Scenario: 默认规格检索
- **WHEN** Codex 搜索当前领域要求且用户没有请求历史
- **THEN** 搜索范围排除 `openspec/changes/archive/`
