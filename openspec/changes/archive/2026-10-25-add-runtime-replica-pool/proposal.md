## Why

当前 Agent 执行链使用固定 Python Runtime 地址，执行中的归属、取消和重连依赖进程内状态，直接增加副本会把正常的跨节点请求误判为孤儿执行。真实 Claude SDK 调用还持有进程级环境变量锁，因此需要通过多个隔离 Runtime 副本提供并行处理，同时保证断线、重投和取消不会启动重复执行。

## What Changes

- 在同一台主机的 Docker Compose 中部署固定成员的 Python Runtime 池；每个副本一个进程、一个真实执行槽，多个 Agent Worker 共享现有 RabbitMQ 任务队列。
- 业务入口保持统一，池选路在 Worker 的 Runtime Client 内完成；成员地址来自部署配置，不新增调度服务、服务发现系统或任意 URL 注册入口。
- **BREAKING**：将 Worker 的 Job 控制权与 Runtime 的 Invocation 执行归属分离。Job 控制权通过租约和领取版本接管；已经开始的 Invocation 固定到节点及本次启动实例，不能自动迁移执行。
- 执行前保存不可变请求与摘要，建立 `PREPARED → RUNNING → TERMINAL` 状态机；恢复沿用同一 Invocation，事件与终态通过 PostgreSQL 条件写入仲裁。
- **BREAKING**：取消改为持久化意图；Worker 退出默认排空或交接，不因消费者退出或 HTTP 断线取消业务执行。取消、超时、完成竞争时只产生一个终态。
- 增加容量等待、单节点执行槽、模型探测共用槽、故障节点隔离、排空，以及有界的失联恢复；容量等待不消耗业务重试次数。
- **BREAKING**：同一 Session 的 Job 按输入顺序串行，不同 Session 并行；后续任务在前一任务结果持久化后才冻结上下文。
- 明确 PostgreSQL 竞争测试、真实多容器故障注入、真实 SDK/Provider 并行验收、数据隔离和容量证据标准。文档完成不代表实现或真实验收完成。

## Capabilities

### New Capabilities

无新的 canonical 领域；本次新增能力归入下面三个已有领域。

### Modified Capabilities

- `execution-delivery`：Job 租约与接管、Invocation 冻结和归属、跨节点寻址、重连与终态恢复、持久化取消、容量延期、执行槽和故障收敛。
- `channel-conversation`：同 Session 有序执行、不同 Session 并行、上下文冻结时机及排队期间的消息可见性。
- `platform-operations`：单机 Compose 固定节点池、就绪聚合、最小数据库权限、排空和升级边界、可观测性及分层验收。

## Impact

- 提案创建时的源码基线（实施前静态核对）：`backend/app/python_runtime/claude_client.py` 的 `_CLAUDE_ENV_LOCK` 包围真实 SDK 消费；`python_runtime/invocations.py` 把不同 owner 的未完成调用判为 `ORPHANED`；`python_runtime/service.py` 的取消只查本进程 Registry；RabbitMQ consumer 使用 `prefetch=1`；`AgentRepository.claim_job` 的 RUNNING 恢复依赖 redelivery 标记。均需按本提案收敛，不能只改 Compose 副本数。
- 预期实现范围（Documented-intent）：Job/Session/Outbox 仓储与 Worker、Runtime Client/HTTP 控制接口、Runtime Registry/账本、模型 probe 路由、数据库 migration/grants、Compose 配置和运维就绪投影、相关合同及测试。
- 沿用当前执行请求/事件协议版本和既有 Runtime Grant、Principal JWT、Publication、文件 Manifest、审计及业务授权边界；新增池控制响应和实例身份校验，所有节点必须来自同一发布。旧部署不能绕过池准入继续接单。
- 复用现有 `jobs.manage` 权限提供目标 Job 的幂等取消入口，仍需业务范围校验与 CSRF；不新增权限体系或可配置调度插件。
- 首期采用两个固定 Runtime 节点及两个 Worker 的默认拓扑；验收扩至三个节点/Worker验证并行和满载。节点数量是执行槽数量，不是 QPS 承诺。
- 不包含跨主机、自动扩缩容、运行中 SDK/沙盒迁移、多进程共享同一节点地址、同进程多模型执行，以及生产数据自动清理。
- 本 change 的实施进度见 [任务清单](tasks.md) 和 [验收记录](evidence/acceptance.md)。用户随后调用 apply 并授权本地 Compose 真实模型验收、同步及归档；实现、分层证据和测量限制均已记录。
