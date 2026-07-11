## ADDED Requirements

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
