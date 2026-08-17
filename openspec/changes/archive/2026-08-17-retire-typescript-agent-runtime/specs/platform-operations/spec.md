## MODIFIED Requirements

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

### Requirement: Job Sandbox容量和隔离配置必须可验证
Python Runtime 的临时文件系统配置 MUST 支持第一阶段 15 MiB 单文件与受控多文件物化，并对每个 Job 实施独立沙盒容量、文件数量、路径和生命周期限制。Compose MUST 不再使用无法容纳一个合法输入及安全处理开销的 32 MiB 无差别配置；实际容量必须由受控部署配置决定、在启动时校验并在健康状态中只显示非敏感上限。

#### Scenario: 沙盒容量小于合法最小处理需求
- **WHEN** Runtime 配置无法容纳一个 15 MiB 输入、对应输出和必要临时开销
- **THEN** Runtime readiness 失败而不是在 Agent 执行中无界磁盘失败

#### Scenario: 单Job达到沙盒上限
- **WHEN** 继续物化或生成文件会超过当前 Job 沙盒容量
- **THEN** Runtime 在写入前拒绝并返回安全、有界错误

## ADDED Requirements

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
