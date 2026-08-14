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
Compose、Secret usage和运行配置 MUST 只向`file-service`提供MinIO endpoint与`secret://platform/`凭据引用所需能力。`agent-worker`、Python/TypeScript Runtime、`file-worker`、Delivery Dispatcher和前端 MUST NOT挂载或解析MinIO Access Key、Secret Key或Session Token。File Service健康、错误和配置快照只能显示configured状态与脱敏endpoint摘要。

#### Scenario: File Worker环境被检查
- **WHEN** 运维查看`file-worker`有效配置和容器挂载
- **THEN** 不存在MinIO Secret值或可解析Secret usage

#### Scenario: MinIO Secret不可用
- **WHEN** File Service引用的Secret缺失、禁用或无法解密
- **THEN** File Service readiness失败且不回退到空值、旧env Secret或临时凭据

### Requirement: File Service与File Worker具有真实就绪和积压观测
File Service readiness MUST 验证PostgreSQL schema、MinIO私有bucket访问、Principal JWKS、Manifest和内部流式接口依赖；File Worker readiness MUST 验证RabbitMQ队列契约、File Service内部API和清理调度可用性。平台运维视图 SHALL 展示附件、提交暂存、工作区过期和保留清理的安全积压计数与最近结果，不得仅以容器running声明可用。

#### Scenario: MinIO进程可达但bucket无权限
- **WHEN** File Service能连接MinIO endpoint但无法读取或写入受控bucket
- **THEN** readiness返回失败并阻止文件能力被宣称为已接线

#### Scenario: File Worker存在清理积压
- **WHEN** 到期内容因瞬时错误等待重试
- **THEN** 运维状态显示有界积压、最早到期时间和安全错误分类
- **AND** 不显示文件名、正文、对象键或凭据

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
