# platform-operations Specification

## Purpose

定义部署拓扑、配置与Secret、Schema迁移、运行就绪、测试及规范治理的当前责任边界，确保基础设施启动、数据变更、故障恢复和验收声明均可按代码与明确证据核对。

## 领域边界

资源选择/技术验证语义见 builtin-tool-resource，Provider操作见 governed-api-capability，Job与外部操作执行见 execution-delivery，文件内容和处理状态分别见两个文件领域。本领域保留基础设施、部署和验收职责；knowledge目前仅是平台存储和受限离线导入。

## 实现依据与验证边界

代码：`docker-compose.yml`、`backend/docker/docling-serve/Dockerfile`、`backend/app/shared/migrations.py`、`backend/app/shared/schema_baseline.py`、`backend/app/shared/feature_configuration.py`、`backend/app/modules/platform_config/application/runtime_config.py`、`backend/app/modules/knowledge/`、`backend/app/cli/import_ones_knowledge.py`、`backend/migrations/`。

检查入口：`Makefile`、`scripts/check_markdown_links.py`、`backend/tests/test_runtime_config_reconciliation.py`、`backend/tests/test_schema_migration_runtime.py`、`backend/tests/test_knowledge_import.py`。

本规格于 2026-09-16 按当前代码重建。代码与测试定义可定位实现和覆盖范围；本次文档重建不代表执行了真实模型、Provider、数据库升级或部署验收。

## Requirements

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
- **WHEN** 通过 固定MCP `get_schema_directory` 分别预览两个测试基地
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
系统 SHALL 向具有配置读取权限的管理员提供只读有效功能配置诊断，返回三个顶层开关、派生管理能力、受治理策略、来源、弃用状态和冲突信息。

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
系统 SHALL 使用同一个 PostgreSQL database 保存 Web 配置、Agent job、聊天记录、工具调用和审计数据，并 MUST 通过表前缀、模块 repository 和迁移边界进行逻辑隔离。

#### Scenario: Query platform configuration without reading chat tables
- **WHEN** Web 配置 API 查询 platform topology
- **THEN** 系统只通过 `platform_config` repository 读取 `platform_*` 配置表，不直接访问 `agent_message` 或 Agent job 运行表

#### Scenario: Future runtime split remains possible
- **WHEN** 后续需要把聊天和审计运行数据迁移到独立库
- **THEN** 系统可以通过 repository 配置切换运行数据存储，而不改变 platform configuration 的领域 API

### Requirement: Registry exposes stable runtime revision
系统 SHALL 为 Environment/Base/Workshop topology、Resource Identity 和 Resource Revision 暴露规范化 revision 或 content hash，用于审计管理变更和证明每次 Tool Call 的实际资源事实。新 Resource Revision 的 content hash MUST 同时覆盖 Provider 连接配置、Secret references、数据范围 bindings 和资源角色 placement；系统 MUST NOT 生成 Application Resource Mapping、独立范围 Policy Revision、activation generation 或 Job-frozen Resource Revision。历史角色事实须从旧身份配置保留，不根据资源名称猜测，且不得重写旧发布哈希。

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

#### Scenario: 已有资源修改角色
- **WHEN** 管理员从现有发布版本新建草稿并修改资源角色
- **THEN** 系统保存角色到该草稿并使旧验证失效，重新验证发布后才以新角色解析；其他资源与旧发布不变

#### Scenario: 升级前草稿验证不覆盖角色
- **WHEN** 升级前草稿哈希尚未纳入角色
- **THEN** 系统要求先保存草稿并重新技术验证，不复用旧验证发布

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
Registry MUST 以单一 schema 定义管理 API、前端表单、验证器和运行时适配器字段；数据库Provider只允许 MySQL、SQL Server、Oracle，Redis 和 Loki 使用各自统一字段。

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

### Requirement: 资源角色必须按当前代码合同保存
Registry SHALL 将placement作为DB/Redis资源的可选精确角色，遵守shared/resource_role.py的1–64位中文、字母数字及_.:-语法；空值表示未指定，不限于cloud/edge枚举，也不将default等合法名称当成保留占位。Loki拒绝非空角色。角色随Draft及Published Revision保存，哈希与技术验证覆盖它，不能只改Identity影响旧发布。

#### Scenario: 自定义角色
- **WHEN** 管理员为数据库或Redis保存合法自定义资源角色
- **THEN** 该值进入当前Draft及其hash，必须重新验证发布后才影响调用目标。

#### Scenario: 角色留空或不合法
- **WHEN** 管理员清空角色，或向Loki提交非空角色
- **THEN** 清空按未指定保存；Loki非空与不符合语法的值被拒绝。

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
系统 MUST 通过向前迁移为 PostgreSQL public 和 knowledge schema 中最终保留的每张项目自有表和每个字段设置非空中文注释；注释 SHALL 描述领域含义、关联对象、状态、版本、时间或安全边界，不得使用统一无语义占位文本。schema_migration 迁移账本、PostgreSQL 系统表和第三方扩展表不属于项目注释范围。

#### Scenario: 已有数据库升级
- **WHEN** 已执行到前一 schema head 的 PostgreSQL 数据库升级
- **THEN** 所有最终保留的项目表和字段都具有非空中文 comment，业务数据、约束和索引保持不变

#### Scenario: 新迁移增加表或字段
- **WHEN** 后续迁移新增项目自有表或字段但没有同步声明注释
- **THEN** schema 注释覆盖测试失败并阻止发布

#### Scenario: SQLite 运行迁移
- **WHEN** 测试或本地环境使用 SQLite 执行同一迁移目录
- **THEN** PostgreSQL COMMENT ON 语句被兼容跳过，最终 SQLite schema 仍与静态注释清单进行完整性对照

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
仓库 SHALL 只把 AGENTS.md 与 openspec/specs/README.md 列出的十个领域 spec.md 作为当前已接受规范；索引、当前架构摘要、ADR、active change 与 archive 都不是第二套基线。用户要求按代码重建时 SHALL 核对代码事实并记录修正；日常实现与规范有差异时 MUST 明示差异并通过明确变更解决，不能让旧文档静默覆盖代码事实或新规范。

#### Scenario: 判断领域规范
- **WHEN** Codex处理普通领域需求
- **THEN** 先按领域索引定位相关spec，再核对所需代码；不递归加载十个领域及历史change。

#### Scenario: 重建规范
- **WHEN** 维护者按明确授权修正旧规范
- **THEN** 保存来源映射和未完成验收边界，旧文本保留为历史快照。

### Requirement: Codex 默认按领域读取 Canonical 主规格
一般设计、实现、评审与诊断 SHALL 默认只读取请求相关的 canonical spec；查询代码不是加载历史规范。仅当用户点名change或当前执行propose/apply/sync/archive时才读对应active artifacts；仅在明确历史、审计或追溯任务中才读相关archive。工作流 MUST 将碎片capability映射到现有领域，不得仅按旧delta目录名重建第十一个主规格。

#### Scenario: 普通领域请求
- **WHEN** 用户询问ONES工具或钉钉外部操作且未指定change
- **THEN** 默认读取governed-api-capability；身份或异步确认涉及其他边界时再读对应相关领域。

#### Scenario: 归档碎片change
- **WHEN** 历史delta以dingtalk-mcp或governed-ones-task-update等能力名组织
- **THEN** 先按当前代码与领域映射对账，再跳过重复spec复制归档；不恢复旧碎片目录。

#### Scenario: 历史追溯
- **WHEN** 用户明确要求核对一项历史决策
- **THEN** 只读取相关archive并标记为历史证据，不覆盖canonical。

### Requirement: Archive 保持完整且不参与默认规范解析
基线重建 MUST 保留既有archive的文件路径和内容。历史active关闭 SHALL 原样移动到日期化archive，保留任务勾选、delta、proposal、design和evidence；归档不等于任务完成或真实验收通过。归档前后 MUST 校验文件清单及SHA-256，并单独记录未完成事项、现代码的规范归属与已失效的历史部署步骤。

#### Scenario: 关闭未完成验收的change
- **WHEN** 用户明确批准关闭含未完成任务的历史change
- **THEN** 未勾选项保持未勾选，关闭记录列出验收欠账，不生成虚假通过证据。

#### Scenario: 验证旧archive
- **WHEN** 重建结束后检查归档树
- **THEN** 所有既有文件路径和摘要与重建前一致，新增目录单独记录。

#### Scenario: 分叉合并触及旧路径
- **WHEN** 旧分支修改了已迁到历史快照的主规格
- **THEN** 维护者核对快照完整性和新领域对账，不以Git无冲突代替语义核对。

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
默认Compose SHALL 保持`file-service`与替换旧`attachment-worker`的`file-worker`，并部署内部`docling-serve`和两个独立`file-processing-worker`实例；不得长期并存两个附件消费者，也不得新增独立`file-mcp`容器。`file-service`同时承载内部REST与File MCP接口；`file-worker`继续消费原附件队列并承担来源下载/导入、工作区过期、保留内容和提交暂存清理；`file-processing-worker`只消费文档处理队列并编排Docling；现有Agent Worker和Delivery Dispatcher继续独立运行。
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

### Requirement: 文件schema变更只由Migrator执行且不在迁移中删除对象
文件工作区表、约束、索引、Publication字段、Job File Manifest、提交暂存、版本、保留与清理事实 MUST 通过新的前向migration由一次性Migrator应用。历史附件到期时间 SHALL 从原始创建时间与有效策略回填；migration事务 MUST NOT访问或删除MinIO对象，实际删除只能由File Worker经File Service在迁移完成后可重试执行。

#### Scenario: 历史附件已经到期
- **WHEN** migration计算出附件到期时间早于当前时间
- **THEN** 数据库记录待清理事实
- **AND** migration完成前不删除对象

### Requirement: 文件工作区验收覆盖真实端到端链路
Compose验收 MUST 使用合成TXT、LOG、Markdown、born-digital PDF、扫描PDF、DOCX、PPTX、XLSX、带文字图片和无文字图片及假凭据，证明钉钉或受控Channel入口、File Worker、File Service、PostgreSQL、MinIO、File Domain Outbox、processing RabbitMQ拓扑、File Processing Worker、Docling、Agent Worker、Python Runtime 当前 Runtime 协议（见 execution-delivery）、Job Sandbox、File MCP live对账、Runtime effective registry、Prompt contract、原件Delivery和文本结果形成新鲜链路。验收还 MUST 覆盖无附件文字Job、Principal/API Key拒绝、越权文件、MIME伪装、加密/损坏/超大小/超页数、PARTIAL、NO_TEXT、Markdown超限、Docling重启、结果取得后Worker崩溃、幂等重试、40个输入工作集边界、沙盒/representation staging清理、交付重试、工具契约失败关闭和Secret不泄漏；不得以容器healthy替代业务证据。

#### Scenario: PDF总结并交付原件
- **WHEN** 合成用户上传合法PDF并要求总结后转发原件
- **THEN** 证据关联原附件、source Version、processing run、Markdown/JSON representation、Manifest v5、Working Set、沙盒Markdown读取、工具契约观测、Agent结果和原PDF Delivery
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
- **WHEN** 验收检查容器环境、MQ、Job、Tool事件、工具契约观测、审计、API和日志
- **THEN** 不存在MinIO Secret、Docling API Key、Service bootstrap credential、Principal JWT；普通日志与安全事件不得包含完整Prompt、完整Tool Schema或原始正文，授权完整运行审计的独立存储边界以execution-delivery为准；不得出现、对象键或真实业务文件

#### Scenario: 无附件文字消息正常执行
- **WHEN** 合成用户只发送非空文字且不上传或引用文件
- **THEN** Job使用当前 Runtime 协议（见 execution-delivery）和空schema v5文件上下文完成模型执行与文字Delivery
- **AND** 工具契约观测明确区分适用的Runtime effective事实与未绑定的File MCP观测

#### Scenario: File MCP缺少冻结提交工具
- **WHEN** 受控验收替身使Job冻结`file_create_commit_intent`但File MCP `tools/list`不声明该工具
- **THEN** Runtime在模型调用前产生`DRIFT`观测并以稳定错误失败关闭
- **AND** 运行记录详情显示`MISSING_REMOTE`且不依赖模型文字回答

#### Scenario: Runtime派生工具不被误报
- **WHEN** 匹配的File MCP与Job Snapshot使Runtime按规则注册`select_sandbox_output`
- **THEN** 运行记录把它显示为`runtime_derived`并关联`file_create_commit_intent`授权前提
- **AND** 不要求File MCP `tools/list`声明该派生工具

#### Scenario: 旧合同不存在于发布产物
- **WHEN** CI检查后端、前端和Runtime发布产物
- **THEN** 不存在`text-v1`、`docling-text-v1`、`docling-layout-ocr-v1`、Manifest v1-v4或Runtime protocol 1.0-v1.3可执行实现
- **AND** 历史只读Schema、migration与变更文档中的旧版本说明不被误判为运行支持

### Requirement: Docling服务固定版本并保持内部隔离
默认Compose MUST 使用仓库Dockerfile构建的`docling-serve`包装镜像，其上游基础镜像固定tag与多架构OCI index digest，并由代码发布合同同时固定每个受支持平台的子manifest digest；部署现场不得通过环境变量或override替换模型artifact期望摘要。服务 MUST 禁用UI、远程services、HTTP URL source、Callback、自定义VLM/图片描述配置和外部插件；服务不得映射宿主端口，只能由`file-processing-worker`通过专用内部网络和独立API Key访问。容器 MUST 使用非root、只读根文件系统、受控scratch、CPU、内存、PID和时间限制，并在运行前准备所需模型artifacts而不是运行时访问互联网。

#### Scenario: 检查Docling Compose配置
- **WHEN** 运维渲染默认Compose配置
- **THEN** `docling-serve`的Dockerfile上游基础镜像使用固定OCI index digest、发布合同包含当前平台对应的固定子manifest、无宿主端口、UI关闭且远程/自定义能力关闭
- **AND** 不存在PostgreSQL、RabbitMQ、MinIO、平台Principal Secret或`DOCLING_MODEL_ARTIFACT_DIGEST`部署覆盖

#### Scenario: Docling模型尚未就绪
- **WHEN** `/health`成功但`/ready`因模型加载、artifact校验或内部编排器失败返回非就绪
- **THEN** 平台文档处理状态不得报告READY
- **AND** processing worker不得把请求发送到未就绪实例

#### Scenario: OCI index的平台成员不符合发布合同
- **WHEN** 发布校验发现固定index解析出的AMD64或ARM64子manifest与代码发布映射不一致
- **THEN** 镜像发布和部署失败
- **AND** 不通过修改环境变量、采用本地缓存镜像或忽略平台差异继续启动

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

### Requirement: Runtime Config 只读路径不得隐式注册定义
Runtime config definition 列表、effective snapshot、ready diagnostics 和其他只读请求 MUST NOT 创建或更新 definition。若受控初始化没有完成，读取路径 SHALL 返回安全的缺失或 degraded 诊断，不得通过 GET、snapshot 构建或健康检查自我修复数据库。

#### Scenario: 管理员重复读取 Definition 列表
- **WHEN** 管理员连续调用 definition 列表 API 且数据库内容未变化
- **THEN** 两次响应读取同一事实，数据库写入计数、definition revision、`updated_at` 和配置审计均不变化

#### Scenario: Snapshot 发现缺少内置 Definition
- **WHEN** effective snapshot 或 ready diagnostics 发现预期内置 definition 尚未由受控初始化注册
- **THEN** 系统返回不泄漏敏感信息的 missing-definition 或 degraded 诊断
- **THEN** 读取事务不得插入 definition 或修改任何 runtime config revision

### Requirement: Runtime Config 聚合版本必须反映真实持久化变化
系统 SHALL 为 runtime config definition、value 和相关 Secret metadata 提供稳定的聚合 revision 与内容 hash。任一受支持的真实持久化变化 MUST 改变聚合版本标识；无变化对账和纯读取 MUST 保持聚合版本标识不变。调用方 MUST 将该标识视为不透明并发与观测令牌，不得依赖其具体数值。

#### Scenario: 修改低 revision 的配置值
- **WHEN** 某个 runtime config value 发生真实更新，即使其他 definition 具有更高的单行 revision
- **THEN** 聚合 revision 与有效配置 hash 按其影响发生变化，不得因取最大单行 revision 而掩盖本次更新

#### Scenario: 重复构建相同 Snapshot
- **WHEN** 数据库 definition、value 和相关 Secret metadata 均未变化而重复构建 snapshot
- **THEN** 聚合 revision 和内容 hash 保持稳定
- **THEN** 构建 snapshot 不产生数据库写入或配置审计

### Requirement: Schema 事实源必须登记并可审计
系统 SHALL 在版本控制中维护 schema fact-source manifest，按表及关键列登记领域所有者、事实语义、分类、writer、reader、生命周期、保留/审计要求和退役状态。分类至少 MUST 区分 canonical mutable fact、immutable snapshot、derived projection、compatibility shadow、operational coordination fact 和 one-time migration artifact。

#### Scenario: 新增或修改持久化字段
- **WHEN** migration 新增表、关键列、快照或兼容表示
- **THEN** 同一 change 更新 manifest 并声明唯一事实源、允许的派生关系、所有 writer/reader 和退役条件

#### Scenario: 重复表示具有不同职责
- **WHEN** 两个字段或表包含相似数据但分别承担可变草稿和不可变发布快照职责
- **THEN** manifest 将二者登记为不同生命周期事实
- **AND** consolidation 不得把不可变历史误判为需要消除的双写

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

### Requirement: 布局OCR复用隔离处理拓扑并固定模型artifact
默认部署 SHALL 复用内部`docling-serve`、独立`file-processing-worker`、File Service、File Domain Outbox和RabbitMQ文档处理边界来执行parent、picture item与assembly任务，不得把Docling或OCR暴露为Agent Tool/MCP，也不得新增可绕过File Service的图片对象入口。Docling/OCR/layout所需模型与配置 MUST 在构建或受控部署阶段固定revision、摘要算法、多架构OCI index以及每个受支持平台的子manifest和模型artifact digest并离线可用；完整平台映射 MUST 属于Profile canonical payload，运行时实算仅用于校验所选平台条目且不得反向成为配置。运行时下载、远程services、自定义模型、Callback、HTTP source和外部插件 MUST 保持关闭。

#### Scenario: 检查处理组件Secret和网络
- **WHEN** 运维检查File Processing Worker、Docling和File Service的环境、Secret、网络及挂载
- **THEN** 只有File Service具有对象存储凭据，Worker只有角色bootstrap/RabbitMQ/Docling API Key，Docling只有自身固定API Key与代码发布的模型artifact映射
- **AND** 任何处理组件都不获得任意对象键、其它Worker凭据或外网图片/模型访问

#### Scenario: 固定OCR模型缺失
- **WHEN** 容器离线启动但Profile为当前平台固定的OCR/layout artifact不存在、digest不匹配或无法加载
- **THEN** Docling/Worker readiness失败且布局Profile不得报告READY
- **AND** 不尝试访问互联网下载、采用现场实算值或回退到其它平台/模型

#### Scenario: 两个平台验证同一发布合同
- **WHEN** 发布流程分别验证`linux/amd64`和`linux/arm64`镜像
- **THEN** 每个平台的实际模型目录摘要与完整Profile映射中对应条目一致，且两端Profile hash相同
- **AND** 只有升级固定OCI index或模型内容的代码变更才可更新映射并产生新的Profile hash

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

### Requirement: 测试反馈预算必须可测量且不得通过缩减覆盖达成
仓库 SHALL 提供可复现的测试基线命令并输出执行环境、收集数、通过/跳过数、总耗时和最慢测试。当前Makefile输出durations并按层级选择测试；耗时结论必须注明环境与本次实际结果，历史120/300秒目标不能当作当前已通过事实。预算只能通过测试分层、隔离基础设施复用、无语义损失的 fixture 重构或经过隔离验证的并行执行达成，不得通过删除规范覆盖、隐藏失败、依赖重试或改变测试选择口径达成。

#### Scenario: 记录优化前后基线
- **WHEN** 维护者评估测试优化效果
- **THEN** 使用相同参考命令和环境记录优化前后收集数、结果、耗时和最慢测试，并说明所有选择条件

#### Scenario: 耗时达到目标但收集数下降
- **WHEN** 快速或完整套件耗时达到预算，但本应包含的测试收集数或层级覆盖下降
- **THEN** 该优化不得通过验收，直到覆盖差异被解释并证明符合规范

#### Scenario: 参考环境未达到预算
- **WHEN** 实现完成后快速套件超过 120 秒或后端完整套件超过 300 秒
- **THEN** 对应性能任务保持未完成并记录差距，不得仅以测试全部通过宣称该性能目标已达成

### Requirement: 删除重复测试必须具有规范覆盖等价证据
删除或合并自动化测试前，维护者 MUST 记录原测试、替代测试、对应 canonical Requirement，以及正常、拒绝、恢复、审计和 Secret 边界的覆盖等价关系。仅代码相似、使用相同 fixture、文件过长或希望减少行数均不得作为删除依据。

#### Scenario: 两个测试断言相似但失败边界不同
- **WHEN** 两个测试具有相似正常路径断言但覆盖不同授权、恢复或审计边界
- **THEN** 系统保留独立测试或提供同时覆盖两个边界的明确替代测试

#### Scenario: 重复测试具有完整替代证据
- **WHEN** 维护者证明替代测试覆盖同一 Requirement 及全部相关边界，并且完整回归通过
- **THEN** 可以删除重复测试并在变更证据中记录映射

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

### Requirement: 单一合同部署不得保留回退服务
部署编排 SHALL 一次性重建API、File Service、File/Processing Worker、Agent Worker、Python Runtime和管理端，并且不得并行运行包含旧Profile、旧Manifest或Runtime protocol 1.0至1.3可执行实现的镜像。入口恢复前 MUST 验证所有消费者、生产者、数据库约束和管理端bundle符合同一不可变发布清单，相关服务报告预期`source_revision`、`build_id`和platform，Python Runtime health只声明当前 Runtime 协议（见 execution-delivery）；实际镜像digest可按平台分别记录但不得缺失时伪造。

#### Scenario: 仍有旧Worker镜像消费队列
- **WHEN** 部署预检发现任一旧Agent Worker、File Worker、Processing Worker或Runtime实例仍注册或消费
- **THEN** 入口流量不得恢复
- **AND** 系统不依靠双写、版本协商或重试到旧服务维持运行

#### Scenario: 组件来自不同发布
- **WHEN** API、Agent Worker、Python Runtime或File Service报告的revision/build ID不符合本次发布清单
- **THEN** 部署预检失败并按组件输出安全差异
- **AND** 容器healthy或工具名称偶然相同均不得替代发布一致性证据

#### Scenario: 当前 Runtime 协议（见 execution-delivery）入口恢复
- **WHEN** 所有旧消费者已停止、非终态1.3事实为零、migration成功且新鲜合同与E2E通过
- **THEN** 平台只恢复当前 Runtime 协议（见 execution-delivery）入口和消费者
- **AND** 入口恢复后不回退到protocol 1.3或恢复旧Job执行

### Requirement: 业务MCP与外部操作worker必须保持固定部署及凭据边界
Compose SHALL 部署固定dingtalk-mcp和external-action-worker，隔离Agent模型与Provider凭据。平台API受信配置基础设施可解析Connector Secret，并只向通过内部认证与有效runtime lease的dingtalk-runtime进程提供建立Stream所需AppSecret；业务MCP与外部worker也只在各自受信适配器内解析。Secret MUST NOT进入Agent Runtime/模型、普通管理响应、Job/Tool快照或日志。

#### Scenario: Stream连接取配置
- **WHEN** DingTalk Runtime通过内部认证并持有有效lease请求desired-config
- **THEN** API返回建立连接必需的受信配置，SDK仅在运行内存中消费AppSecret，普通管理接口不回显。

#### Scenario: Agent请求凭据
- **WHEN** Agent或普通管理调用试图取得Connector Secret
- **THEN** 接口/权限边界拒绝，不把Stream内部通道变成凭据读取Tool。

### Requirement: 部署必须注入可比较的组件构建身份
平台 SHALL 为Control Plane、Agent Worker、Python Runtime和File Service注入有界安全构建身份，至少包含固定组件名、源码`source_revision`、发布`build_id`和标准OS/architecture `platform`；部署系统能够准确取得实际镜像摘要时还 SHALL提供`image_digest`。`source_revision`与`build_id` MUST由构建流水线和发布清单产生且不可由Agent、Application、外部请求、模型输出或Job payload覆盖。服务不得挂载Docker socket、查询容器daemon或把可变tag伪装成digest来补全身份。

必需身份缺失或格式无效时，相关服务readiness MUST失败。Control Plane SHALL在Job创建事实中关联自身身份，Worker SHALL在当前 Runtime 协议（见 execution-delivery） invocation事实中关联自身身份，Runtime SHALL在安全事件中声明自身身份，File Service SHALL在已认证MCP初始化元数据中声明自身身份；运行记录只展示这些安全字段，不展示registry凭据、环境变量或原始容器配置。

#### Scenario: 同一发布的组件身份一致
- **WHEN** 部署预检比较API、Agent Worker、Python Runtime和File Service
- **THEN** 各组件`source_revision`和`build_id`符合当前不可变发布清单
- **AND** 任一组件缺失、格式无效或引用另一发布时入口不得恢复

#### Scenario: 部署无法取得镜像digest
- **WHEN** 某本地Compose环境无法准确向容器注入实际镜像digest
- **THEN** 组件明确报告该可选字段未观测，同时仍报告必需revision、build ID和platform
- **AND** 系统不得使用镜像tag、容器ID或猜测值冒充digest

#### Scenario: 跨架构镜像摘要不同
- **WHEN** Mac arm64与Windows或Linux amd64由同一源码revision和build ID构建且工具契约hash一致，但平台与镜像digest不同
- **THEN** 系统把不同digest保留为各自产物证据而不单独判为工具契约漂移
- **AND** 操作者仍可使用platform和digest定位两端实际运行产物

### Requirement: Compose固定部署双Processing Worker和单Docling双执行器
默认Compose MUST 在无需额外scale参数的情况下启动两个独立`file-processing-worker`实例，并只启动一个`docling-serve`容器。两个Processing Worker MUST 使用相同代码镜像、Profile hash、角色权限和processing队列契约，每个实例 MUST 保持单消费者与RabbitMQ `prefetch=1`；Docling MUST 使用`local` engine、`single-use results`和恰好两个共享模型的local execution workers。`docker compose build`后执行`docker compose up -d` MUST 产生该固定拓扑。

#### Scenario: 新环境使用默认命令部署
- **WHEN** 操作者在已初始化Secret且满足资源前提的新环境更新代码、执行Compose build并执行`up -d`
- **THEN** Compose启动两个Processing Worker和一个包含两个local execution workers的Docling容器
- **AND** 不要求操作者修改Profile hash、模型digest、Worker并发参数或额外传入`--scale`

#### Scenario: 两个Processing Worker消费共享队列
- **WHEN** processing队列中同时存在多个父文件或图片任务
- **THEN** 两个实例分别以`prefetch=1`竞争消费独立消息并通过File Service申请全局槽位
- **AND** 单实例进程内并发保持`1`，跨实例总Docling并发由PostgreSQL严格限制为`2`

#### Scenario: 尝试横向扩展本地Docling容器
- **WHEN** 有效Compose配置在`local` engine和`single-use results`模式下解析出两个或更多`docling-serve`副本
- **THEN** 配置校验失败并阻止部署被标记为可用
- **AND** submit、poll和fetch不得依赖未定义的负载均衡粘性命中同一容器

#### Scenario: 检查受限依赖拓扑
- **WHEN** 运维审查文档处理服务、网络和依赖
- **THEN** 拓扑不包含Docling RQ、Redis、Ray或外部调度器
- **AND** Processing Worker不直接取得PostgreSQL凭据，而是通过已认证File Service内部接口协调槽位

### Requirement: 文档处理就绪聚合两个Worker与两个槽位
File Service SHALL 接收每个Processing Worker使用不透明实例ID提交的有时效安全心跳，并 MUST 聚合期望实例数`2`、有效实例数、固定Profile hash、processing队列契约、Docling readiness、Docling执行器配置和两个数据库槽位的占用/隔离状态。只有两个合规Worker、单个双执行器Docling、队列、File Service安全闸门和两个槽位均可验证时，文档处理能力才能报告`READY`；任何实例缺失、配置漂移、第三实例、槽位不确定或依赖不可用都 MUST 报告`CONFIGURED_UNAVAILABLE`，但不得使Business Application管理读写接口整体不可用。

#### Scenario: 一个Worker实例停止心跳
- **WHEN** 两个实例中一个心跳超过固定有效期且另一个仍可安全处理
- **THEN** 聚合状态报告期望实例`2`、有效实例`1`和稳定降级原因码
- **AND** 不因剩余容器running而继续报告完整`READY`

#### Scenario: 出现第三个合规Worker实例
- **WHEN** 滚动部署残留或错误scale使三个实例同时报告有效心跳
- **THEN** 聚合状态失败关闭并报告拓扑漂移
- **AND** 数据库两个槽位上限仍不得扩大

#### Scenario: 运维查看槽位诊断
- **WHEN** 操作者读取文档处理安全诊断
- **THEN** 系统展示槽位总数、占用数、隔离数、Worker有效数量、最早安全时间和白名单原因码
- **AND** 不展示文件名、正文、对象键、外部task ID、凭据或原始异常

#### Scenario: 容器健康但并发链路无效
- **WHEN** 所有容器均为healthy但十文件并发验收出现超过两个在途任务、重复Representation或消息丢失
- **THEN** 部署不得被验收为文档处理并发可用
- **AND** 运维必须保留队列、processing run、槽位和终态计数的非敏感证据

### Requirement: 钉钉权限不足必须形成精确降级事实
系统 SHALL 为 contacts、department、tasks、calendar、notable、robot 和 notice 的固定 Provider 操作维护所需权限说明，并把权限不足分类为对应 Tool/Profile 的稳定非重试错误。单个 Profile 权限不足 MUST NOT 使已满足依赖的其它 Tool 绕过授权或被误报为不可用。

#### Scenario: Calendar 权限缺失
- **WHEN** 钉钉应用缺少当前 calendar Tool 所需权限
- **THEN** 该调用返回稳定权限错误并记录安全 Provider attempt，其它已授权 Profile 保持独立

#### Scenario: mutation 写权限缺失
- **WHEN** 用户已确认但 Provider 明确拒绝对应写权限
- **THEN** Intent 进入 FAILED 而不是自动重试或改用其它 endpoint/Credential

### Requirement: 外部操作worker的分派与健康观测必须分开
外部操作worker SHALL 按代码固定的operation/Tool合同执行，并使用数据库条件claim保证同一Intent只有一个执行者；未知operation或合同不兼容的实际执行必须失败关闭。当前进程串行run_once，Compose health只检查heartbeat文件存在，没有全局并发槽位或严格心跳时效判断。系统 MUST NOT 把该health当作逐个Provider权限、所有handler可执行或发布链已验证的证明。

#### Scenario: 重复领取同一意图
- **WHEN** 两个worker尝试领取同一个APPROVED Intent
- **THEN** 数据库条件更新只允许一个取得执行权；此事实不限制所有不同Intent的全局并发。

#### Scenario: 观察到heartbeat文件
- **WHEN** Compose health检查到文件存在
- **THEN** 只能说明该检查条件满足，不能证明worker持续活跃、Provider就绪或端到端成功。

### Requirement: 批量机器人消息发布校验与执行前校验必须分层
`dingtalk_batch_send_message_to_users_by_robot` SHALL 使用固定schema/effect/policy、operation、endpoint、Provider字段投影与执行器。应用组合校验按代码检查Trigger、所需robotCode/工作通知Agent ID及确认模板；身份、企业、Credential和Provider权限由实际调用链复核。发布路径不调用外部worker health或向钉钉验证每项权限，MUST NOT把发布成功表述为这些依赖已经真实可用。userIds人数与payload边界以本地合同为准，不能把未证实的阈值宣称为官方上限。

#### Scenario: 缺少发布依赖
- **WHEN** 应用选择该Tool但当前Trigger或所需机器人标识/确认模板不合法
- **THEN** 组合校验拒绝；纯只读Tool不因缺确认模板而被同样拒绝。

#### Scenario: 运行时Provider拒绝
- **WHEN** 已发布应用执行确认后的批量请求但Provider拒绝权限
- **THEN** 执行保存安全失败事实，不回退工作通知、别的Connector或任意endpoint。

#### Scenario: 消息被受理
- **WHEN** Provider返回processQueryKey等受理结果
- **THEN** 结果只表示受理，不能冒充每位接收者已最终收到消息。

### Requirement: 上线证据必须覆盖真实人员解析和单人及多人发送链
上线证据 SHALL 使用当前代码、新 Agent/Application Publication、明确角色 grant 和全新钉钉 Job，验证真实命中联系人搜索、两个同名候选消歧、单人消息、多人整批消息、取消链、重复点击和旧 Job 不可见。证据 MUST 关联 Job、Tool Call、Action Intent、卡片、唯一 Provider attempt 和外部结果，且不得保存完整 userId 列表、用户完整目录、手机号、邮箱、Secret、Token、消息正文或原始 Provider 响应。

#### Scenario: 真实同名搜索成功
- **WHEN** 当前 App 可见范围内存在两个同名员工且执行联系人搜索
- **THEN** 有界证据显示两个非空 userId 候选以及后续详情消歧成功
- **AND** 不再出现因字符串列表投影导致的 `dingtalk_response_invalid`

#### Scenario: 当前 Job 的详情 Tool 被实际使用
- **WHEN** 新 Job Snapshot 已授权 `dingtalk_get_user` 且搜索结果需要消歧
- **THEN** 证据显示 Agent 在本轮实际调用详情 Tool
- **AND** 不因历史 Job 的拒绝结果跳过当前授权 Tool

#### Scenario: 单用户消息同意
- **WHEN** 原用户确认向一个明确 userId 发送
- **THEN** 证据显示唯一 Provider attempt 的接收人数为一且真实目标收到机器人消息

#### Scenario: 多用户消息整批同意
- **WHEN** 原用户明确选择多个目标并确认一次
- **THEN** 证据显示只创建一个 Intent、一张确认卡和一个 Provider batch attempt
- **AND** attempt 的有界结果表明冻结目标数量一致且真实目标均收到机器人消息

#### Scenario: 用户取消
- **WHEN** 原用户取消单人或多人确认卡
- **THEN** Intent 为拒绝终态、消息 Provider attempt 为零且卡片不可再次执行

#### Scenario: 旧 Job 验证隔离
- **WHEN** 新代码已部署但旧 Job 或旧 Publication 未包含新增 Tool
- **THEN** 新能力不可见且旧消息/工作通知语义不发生变化

### Requirement: 表重建 migration 必须恢复仍生效的约束与索引

系统使用前向 migration 重建已有表时，MUST 在同一 migration 结果中恢复所有仍由 canonical domain 要求的唯一约束、检查约束和索引，并 MUST 验证 SQLite 与 PostgreSQL 的最终业务不变量等价。后续发现已发布 migration 遗漏约束时，系统 MUST 通过新版本前向 migration 修复，不得原地修改已应用 migration。

#### Scenario: SQLite 重建外部身份表
- **WHEN** migration 为调整某一 provider 的身份生命周期而在 SQLite 重建共享外部身份表
- **THEN** 最终 schema 仍强制执行其它 provider 已接受的主体唯一性和当前用户绑定唯一性

#### Scenario: 已发布 migration 遗漏唯一索引
- **WHEN** 当前 migration head 已发布且后续验证发现一个 canonical 唯一索引缺失
- **THEN** 系统分配新的唯一 migration 版本幂等恢复索引，不修改旧 migration 文件或 checksum

#### Scenario: 恢复唯一索引时存在冲突数据
- **WHEN** 前向 migration 创建唯一索引时检测到不满足不变量的既有数据
- **THEN** migration 整体失败且不登记新 head，不得静默删除、合并或选择任一业务记录

### Requirement: 内置初始化 fixture 必须保持跨 Publication 引用自洽

版本控制下用于本地或测试初始化的内置 fixture SHALL 保持所有 Publication ID、revision、config hash 和 snapshot 派生引用自洽。更新被引用 Publication 的冻结事实时，维护者 MUST 同步重新生成同一 fixture 图中的依赖快照，或创建新的 Publication 并显式切换引用；运行时完整性校验不得为兼容坏 fixture 而放宽。

#### Scenario: Fresh bootstrap 初始化默认 Webhook
- **WHEN** 空数据库应用当前 migration 并载入默认 Agent 与 Webhook Trigger fixture
- **THEN** Trigger Publication 冻结的 Agent publication ID、revision 和 config hash 与被引用 Agent Publication 完全一致

#### Scenario: 默认 Agent fixture 的 hash 变化
- **WHEN** 维护者更新默认 Agent Publication snapshot 并导致 config hash 变化
- **THEN** 跨 Publication 完整性测试在所有依赖 fixture 同步前失败，并且 Dispatcher 继续拒绝不一致快照

### Requirement: 知识存储通过统一来源身份和独立收录关系管理
系统 SHALL 在同一平台 PostgreSQL 的 knowledge schema 中保存 source、document、document_revision、knowledge_base、knowledge_base_document、import_run 和 document_relation。来源工作项身份 MUST 独立于知识库和可变工作项类型，内容版本 MUST 可追溯，收录 MUST NOT 自动产生 Agent 或用户读取授权。

#### Scenario: 同一来源内容被多个知识库收录
- **WHEN** 相同来源工作项进入两个知识库
- **THEN** 系统复用稳定 document 和内容版本并建立不同收录关系，不复制来源文档

#### Scenario: 来源团队未确认
- **WHEN** 本地导出缺少可信团队或实例身份
- **THEN** 系统仅记录来源未确认的离线命名空间，不猜测或接续现有 ONES 身份

#### Scenario: 判断知识导入是否已提供检索能力
- **WHEN** 当前代码完成knowledge表和离线导入
- **THEN** 该事实不代表已有Agent知识查询、Embedding、OCR或Qdrant索引；不自动增加读取授权。

### Requirement: ONES 离线文本导入必须预检并可恢复且幂等
导入 CLI MUST 校验详情/list 完整关联、重复身份、数据形状及显式输入数量；MUST 分开 ID 和显示名称，保留受限安全快照、正文、业务属性、采集完整性及版本。批次 MUST 具有输入摘要、明确进度和安全失败事实；相同输入重放 MUST NOT 增加重复文档或版本，旧来源版本 MUST NOT 覆盖新版本。导入 MUST NOT 下载附件、调用 ONES/Embedding/OCR、写 Qdrant 或发布资源。

#### Scenario: 导入五千条已声明缺陷
- **WHEN** 用户指定预检通过的详情/list 导出且声明主记录都是缺陷
- **THEN** 系统保存五千条 defect 文档和收录，相关工单引用不得被生成为缺陷正文

#### Scenario: 中途停止后重放
- **WHEN** 导入在已提交部分文档后中断并使用同一输入再次运行
- **THEN** 系统从持久批次进度恢复，已完成记录不重复写入

#### Scenario: 安全边界
- **WHEN** 来源字段包含可访问 URL、Base64 或明显凭据
- **THEN** 系统在入库前移除敏感片段，命令结果与日志只提供安全统计和错误码，原始输入不修改

### Requirement: 工作项关联必须保留外部身份和来源证据
系统 MUST 保存原始关联类型/方向、来源快照及两端外部身份；关联目标尚未导入时 MUST 保持内部目标 ID 未解析，不创建虚假正文。目标后续导入时 SHALL 补齐引用。未确认完整的关联集合 MUST NOT 用于推断关系删除或推断因果语义。

#### Scenario: 目标正文尚未入库
- **WHEN** 缺陷引用一个未导入的工单
- **THEN** 系统保留工单外部身份和原始关联观察，并标识未解析状态

#### Scenario: 重复或过时关联观察
- **WHEN** 同一来源版本的关系再次被导入或旧文件被重放
- **THEN** 系统幂等保存，不把旧观察伪装成当前完整关系集合

### Requirement: 知识 schema 必须纳入现有迁移与事实源治理
knowledge DDL MUST 仅通过一次性 Migrator 的版本化事务执行。结构、约束、索引、注释和事实源清单 MUST 覆盖 public 与 knowledge；SQLite 测试 SHALL 保持等价领域对象且不得影响现有表。导入器 MUST 只检查 schema head，不执行迁移。

#### Scenario: 新 schema 建表后验收
- **WHEN** 新迁移执行完成
- **THEN** PostgreSQL 真实存在七张 knowledge 表且结构检查、中文注释覆盖和事实源清单能够识别全部对象

### Requirement: 管理端资源角色可创建并复用
数据库和 Redis 资源新建及编辑页面 SHALL 提供“资源角色”输入选择，初始为空，不预置角色；用户可保存新值并选择历史保存值，历史候选来自资源元数据，不读取连接凭据。角色 SHALL 与 RBAC 用户角色区分；Loki 不显示该输入且服务端拒绝非空值。

#### Scenario: 保存和复用新角色
- **WHEN** 管理员输入合法新角色并保存资源草稿
- **THEN** 后续新建或编辑可从历史值中选择该角色，同时仍可不填或新建其他角色

#### Scenario: 清空角色
- **WHEN** 管理员清空草稿角色并保存
- **THEN** 系统保存未指定状态；若发布后产生同目标多候选，仍按歧义规则拒绝，不隐式选择数据库

### Requirement: JavaScript构建入口必须区分实际依赖锁与执行命令
当前 Makefile 的 frontend-check SHALL 按其 pnpm frozen-lockfile 入口运行，GitHub CI 中的 npm ci SHALL 使用所在工作目录的 npm lockfile。维护者 MUST 核对具体包、锁文件与容器构建入口，不得声称仓库已经统一单一包管理器，也不得在文档整理时自动更新依赖或锁文件。

#### Scenario: 复现前端检查
- **WHEN** 维护者执行 make frontend-check
- **THEN** 按Makefile的pnpm流程安装与校验，和CI结果分别记录。

#### Scenario: 判断CI通过范围
- **WHEN** 维护者查看某个GitHub job结果
- **THEN** 以job实际工作目录、锁文件和命令为准，不把一次入口成功当成所有入口通过。

### Requirement: 当前Schema目录与已有数据库升级必须分开判断
活动 migration catalog SHALL 从 `100_baseline_v1.sql` 开始，并按当前代码目录解析 forward head；本次基线重建时目录为 `100..132`。空库可按当前 deployable catalog 建库，既有数据库 MUST 先通过版本、checksum、前置状态与 contract 门禁。精确 legacy 042 的 adoption 必须使用仅含100的独立artifact，当前包含101及以后版本的checkout不能直接完成adoption。业务服务与导入器只校验schema，不执行DDL。

#### Scenario: 创建空库
- **WHEN** 一次性Migrator连接没有业务结构与账本的新数据库
- **THEN** 依次执行当前目录，初始化用户/业务fixture仍是独立步骤。

#### Scenario: 现有数据库落后
- **WHEN** 只读服务发现ledger不是当前deployable head或checksum不符
- **THEN** 就绪失败且不自动迁移、不猜测兼容范围。

#### Scenario: 尝试直接采纳旧账本
- **WHEN** 包含101及以后迁移的当前artifact尝试adopt legacy 042
- **THEN** 服务拒绝，需单独准备baseline-only artifact与恢复证据。

### Requirement: 当前文件Schema与历史迁移必须保持边界
当前文件合同 SHALL 使用 `NONE|docling-layout-ocr-v2`、Manifest v5与代码声明的Runtime协议范围；旧attachment_content、可切换直接文本规则和冗余文件身份不得作为当前读写事实源。迁移119、120、124、125分别记录其引入时的约束，文档 MUST NOT 要求重复执行旧清库、把全部历史Job改成当前协议或原地修改已应用migration。

#### Scenario: 检查当前执行事实
- **WHEN** 服务校验新Job、Manifest或Profile
- **THEN** 使用当前代码合同，无法验证的事实失败关闭。

#### Scenario: 读取终态历史
- **WHEN** 存量终态Job保留旧协议和审计
- **THEN** 保留原版本与缺失观测，不补造当前工具合同或完整审计。

### Requirement: 钉钉业务 MCP Provider 配置必须固定且按工具就绪
平台 SHALL 继续以代码固定 `dingtalk-mcp` 与 Provider operation 注册表运行，不读取 `ACTIVE_PROFILES` 或动态 YAML。Connector Secret 只由基础设施解析；工作通知 Tool 还 MUST 要求 Connector 具有合法非敏感 `work_notification_agent_id`，机器人 Tool MUST 具有可解析 robot code 和当前来源路由。

#### Scenario: Connector 缺少工作通知 Agent ID
- **WHEN** Publication 选择工作通知发送或状态 Tool，但 Connector 没有合法正整数 Agent ID
- **THEN** 发布、激活或运行就绪检查失败关闭并给出稳定配置提示

#### Scenario: 环境变量包含官方 Profile
- **WHEN** Compose 或进程环境设置 `ACTIVE_PROFILES`
- **THEN** 固定服务忽略该变量且 readiness 展示的工具数不发生变化

#### Scenario: mutation 应用缺少确认卡模板
- **WHEN** 业务应用选择任一 `confirmation_policy=external_action_card_v1` 的 Tool，但其已启用钉钉来源 Connector 未配置 `external_action_confirmation` 或合同版本不兼容
- **THEN** 发布或激活失败关闭并指出缺少外部操作确认卡片模板；纯只读 Tool 不受该配置缺失影响

### Requirement: 钉钉业务 MCP 上线必须验证真实读写链路
上线证据 SHALL 使用全新 Job 和当前 Publication/角色快照，至少覆盖每个只读 Profile 的真实成功或明确权限拒绝，以及待办、日历、AI 表格记录、机器人消息和工作通知 mutation 的确认同意与拒绝。验收 MUST 关联 Job、Tool Call、Action Intent、卡片、Provider attempt 和终态，并不得保存 Secret 或无界业务正文。

#### Scenario: 只读 Profile 验收
- **WHEN** 运维执行联系人、部门、待办、日历、AI 表格和通知状态的代表性真实查询
- **THEN** 证据区分成功、外部无数据和明确权限不足，不以 health 代替 Tool 调用

#### Scenario: mutation 拒绝验收
- **WHEN** 原用户在任一新 mutation 确认卡选择拒绝
- **THEN** 证据显示 Intent 为 REJECTED、Provider 写入 attempt 为零且卡片进入不会执行终态

#### Scenario: mutation 同意验收
- **WHEN** 原用户确认代表性的待办、日历、AI 表格、机器人消息或工作通知操作
- **THEN** 证据可从 Tool Call 追溯到唯一 Provider attempt 与真实外部结果

### Requirement: 钉钉测试数据重建必须显式受保护
系统 SHALL 提供仅限非生产环境的一次性钉钉测试数据重建命令；常规数据库迁移、应用启动和管理页面 MUST NOT 自动执行该清理。

#### Scenario: 只读预检重建范围
- **WHEN** 操作者运行重建命令的默认预检模式
- **THEN** 系统只读取并报告环境、数据库指纹、目标连接、各类待清记录数、受影响应用渠道绑定、Secret 撤销范围、明确保留项和计划 Hash，不删除或修改记录

#### Scenario: 使用匹配计划执行重建
- **WHEN** 非生产环境已停止钉钉写入，操作者提交固定确认文字、显式执行参数和仍与当前数据匹配的计划 Hash
- **THEN** 系统在单一事务中清理约定钉钉身份与渠道测试数据、停用旧连接并撤销其专属 Secret，成功后输出实际数量和保留数据复核

#### Scenario: 生产环境请求重建
- **WHEN** 生产环境以任何参数调用重建命令
- **THEN** 系统永久拒绝执行且不得开始删除事务

#### Scenario: 预检后数据发生变化
- **WHEN** 执行时数据库指纹、目标集合或记录数量与计划 Hash 不一致
- **THEN** 系统拒绝执行并要求重新预检，不得使用旧确认继续

#### Scenario: 重建事务中途失败
- **WHEN** 任一删除、Secret 撤销或引用处理步骤失败
- **THEN** 系统整体回滚并报告安全错误，不留下部分清理状态

### Requirement: 重建保留跨域运行历史
钉钉测试数据重建 MUST 保留平台人员、角色、登录会话、ONES 身份与个人 Credential、Agent、业务应用与 MCP Tool 发布配置，以及全部 Agent Job、Tool Call 结果和 Delivery 记录；历史 Publication 中的旧 connector 引用 SHALL 只标记为不可运行历史来源，不得被静默改写到新 connector。

#### Scenario: 清理存在历史Job的旧连接
- **WHEN** 待清理钉钉 connector 已经产生 Agent Job、Tool Call 和 Delivery 记录
- **THEN** 系统保留这些运行记录，使其旧 connector 来源可审计但不可继续路由

#### Scenario: 清理后重新接入
- **WHEN** 重建成功后管理员创建企业和新应用 connector
- **THEN** 既有业务应用主体仍存在，但必须显式选择新 connector 并重新发布
- **AND** 不得自动把历史 Publication 改指新 connector

### Requirement: 核心就绪与领域观测不能替代工具或Provider验收
`/api/ready` SHALL 按当前代码计算数据库、schema、RabbitMQ和Master Key的core_ready，并把其他可观测运行态作为独立字段。管理Dashboard提供Job、Delivery和队列计数；文件运维按内部接口探测其领域依赖。上述结果 MUST NOT 被解释为所有业务MCP、外部worker、Provider权限或新Job链路已经可用。

#### Scenario: API核心就绪
- **WHEN** 数据库、schema、RabbitMQ和Master Key均通过API的当前检查
- **THEN** API可以报告core_ready，但仍需分别检查实际Tool准入、对应服务和真实Provider调用结果。

#### Scenario: Dashboard显示无积压
- **WHEN** 管理页面显示Job和队列计数正常
- **THEN** 该观测不产生Tool调用证据，也不改变发布或Provider权限事实。

### Requirement: 当前运行态只支持Python Runtime
当前源码、API、Agent bootstrap、Worker、Compose 与数据库约束 MUST 只支持新建、发布与执行 `python-v1` Agent。`agent_definition`、`agent_publication`、`agent_job` 与 `agent_runtime_invocation_claim` 的 runtime kind MUST 由数据库约束限定为 `python-v1`；任何非 `python-v1` 的 Agent、Publication、Application 激活、Job 执行或 Runtime 调用请求 MUST 失败关闭且不静默改写为 Python。系统不得保留其它 Runtime 实现的服务、配置或兼容分支，也不得声称当前存在源码中没有的退役预检 CLI、自动排空或跨 Runtime 迁移命令。

#### Scenario: 创建或发布非Python Agent
- **WHEN** 当前 API 收到非 `python-v1` 的 Agent 创建、草稿、发布、回滚或新应用激活请求
- **THEN** 系统失败关闭且不静默改写为 Python

#### Scenario: 执行非Python Job
- **WHEN** Worker 或 Runtime 收到非 `python-v1` 的新执行请求
- **THEN** 系统拒绝执行且不跨 Runtime fallback

#### Scenario: 升级时存在非Python调用占用
- **WHEN** 迁移前 `agent_runtime_invocation_claim` 存在非 `python-v1` 占用
- **THEN** 迁移删除这些无主占用并把约束收紧为只允许 `python-v1`
- **AND** 不改写或删除 Definition、Publication、Job 与审计事实

#### Scenario: 运维查找退役命令
- **WHEN** 操作者检查当前源码运维入口
- **THEN** 文档不得指示调用不存在的 Runtime 退役预检或迁移 CLI
