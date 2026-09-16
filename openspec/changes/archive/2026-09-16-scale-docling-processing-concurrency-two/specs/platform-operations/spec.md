## ADDED Requirements

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
