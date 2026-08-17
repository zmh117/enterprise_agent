## ADDED Requirements

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
Compose、Secret usage和运行配置 MUST 只向`file-service`提供MinIO endpoint与`secret://platform/`凭据引用所需能力。`agent-worker`、Python/TypeScript Runtime、`file-worker`、Delivery Dispatcher和前端 MUST NOT挂载或解析MinIO Access Key、Secret Key或Session Token。File Service健康、错误和配置快照只能显示configured状态与脱敏endpoint摘要。本地Compose首次启动 MAY 让一次性Migrator通过角色隔离的Docker Secret把MinIO凭据写入平台`encrypted_db` Secret，但该进程 MUST 不获得MinIO endpoint、Bucket或对象访问路径，已有Secret不同则失败并要求显式轮换；生产部署 MUST 可关闭此本地bootstrap。

#### Scenario: File Worker环境被检查
- **WHEN** 运维查看`file-worker`有效配置和容器挂载
- **THEN** 不存在MinIO Secret值或可解析Secret usage

#### Scenario: MinIO Secret不可用
- **WHEN** File Service引用的Secret缺失、禁用或无法解密
- **THEN** File Service readiness失败且不回退到空值、旧env Secret或临时凭据

#### Scenario: 本地首次启动初始化受治理Secret
- **WHEN** 本地Compose显式启用文件存储Secret bootstrap且目标平台Secret尚不存在
- **THEN** 一次性Migrator从只读Docker Secret创建加密版本后销毁自身运行态
- **AND** 不向长期运行服务暴露bootstrap值，重复启动保留相同值，值不同则失败而不自动轮换

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
Python与TypeScript Runtime的临时文件系统配置 MUST 支持第一阶段15 MiB单文件与受控多文件物化，并对每个Job实施独立沙盒容量、文件数量、路径和生命周期限制。Compose MUST 不再使用无法容纳一个合法输入及安全处理开销的32 MiB无差别配置；实际容量必须由受控部署配置决定、在启动时校验并在健康状态中只显示非敏感上限。

#### Scenario: 沙盒容量小于合法最小处理需求
- **WHEN** Runtime配置无法容纳一个15 MiB输入、对应输出和必要临时开销
- **THEN** Runtime readiness失败而不是在Agent执行中无界磁盘失败

#### Scenario: 单Job达到沙盒上限
- **WHEN** 继续物化或生成文件会超过当前Job沙盒容量
- **THEN** Runtime在写入前拒绝并返回安全、有界错误

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
