# Runtime 多副本池实施与验收

`add-runtime-replica-pool` 的实现、隔离故障测试和本地真实 SDK/Provider 有界验收已完成；三个 canonical 领域已同步，48/48 项任务完成，2026-10-25 归档。真实测量仅覆盖现有单一受管模型、单主机和合成负载，不代表生产容量或全业务链路验收。详见 [真实验收报告](real-acceptance.md)；没有提交或推送代码，现有凭据未修改，未对既有应用数据库执行迁移。

## 实施结果

- 默认 Compose 为两个固定 Runtime、两个 Worker；验收拓扑为三个 Runtime、三个 Worker、独立 PostgreSQL 18 和 RabbitMQ 4。
- Job 控制租约/版本与 Invocation 不可转移执行归属分开；先保存请求快照和 digest，再原子准入；已接受执行不会因网络错误或 Worker 接管自动重跑。
- 取消先保存意图，Runtime 通知或独立轮询收敛；逻辑终态和停止证明分开，未停止的前序执行继续阻塞同一 Session。独立 watchdog 对失租、截止和停止超时执行容器级退出。
- 同一完整 Session 串行；后续任务按前序 Job 归属读取晚到助手回复并排除未来输入。不同 Session 可并行。
- Runtime 与模型 probe 共用一个非等待执行槽；控制请求不占槽。Worker I/O 心跳独立运行；容量/恢复延期保存 Outbox 后才 ACK，不消耗业务重试。调度扫描补偿失联控制者和未送达任务的准入超时。
- Migration 147、实际 Runtime 角色最小权限、发布前只读门禁、状态投影和运维文档已补齐。事件/终态账本仅允许 Runtime SELECT/INSERT，不能修改或删除既有记录；请求快照不能由 Runtime 写入。

## 验证层级

| 层级 | 结果 | 边界 |
| --- | --- | --- |
| 定向回归 | PASS：370 项定向整组回归（58.31 秒） | 含 1.4/1.5 合同、Worker/调度、取消授权、Session、迁移、schema 事实源、Compose 安全配置；不是全仓库测试 |
| PostgreSQL | PASS：8 项 | 独立连接和同步屏障、完成/取消/失联竞争、旧 Worker 栅栏、会话顺序、快照保留及实际角色权限；不以 SQLite 代替 |
| Compose 确定性 Provider | PASS：19 份场景记录，24 个最终记录中的合成 Job | 包含多容器、真实 PostgreSQL/RabbitMQ、进程终止和暂停、HTTP/流中断；Provider 启动计数来自测试适配器，不是真实 SDK 调用次数 |
| 静态 | PASS | Ruff；31 个变更产品源码文件 mypy；编译检查；主 Compose、原验收 overlay、三节点独立拓扑配置；严格 OpenSpec；Markdown 链接；diff whitespace |
| 真实 SDK/Provider | PASS：RPOOL-19 | Claude Agent SDK 0.2.144 + 现有 deepseek-v4-flash；三节点执行重叠 6.15 秒，真实上下文/SDK cwd/沙盒及凭据环境检查通过 |
| 真实容量 | PASS：RPOOL-20 | 3/6 样本阶段的 P50/P95/P99、积压、资源、取消/接管已记录；不是生产 QPS 或长期 P99 保证 |

结构化记录：[逐项要求与任务映射](verification.json)、[Compose 生命周期与启动计数](compose-results.json)、[清理记录](cleanup.json)。实现源码、测试和合同的 SHA256、最终镜像 ID、构建身份和基础 Git revision 随 JSON 保存；工作区尚未提交。

故障场景在增量构建过程中执行。最终产品代码额外复核了三副本并行、A/B 竞争准入、跨节点终态重放和取消轮询；最后一次合同更新后的镜像又复核竞争准入、跨节点重放及正文清理后完整/最小 HTTP 恢复均返回 410，并在实际 PostgreSQL 上重新验证收紧后的 Runtime grants。中途新增的池身份与只追加账本权限不会被早期宽权限测试替代。

## 逐项验收

| Case | 证据与结果 |
| --- | --- |
| RPOOL-01 | PostgreSQL 双连接及两个真实 Runtime 同时 HTTP 准入：一方 200、一方 owner mismatch；只有一个 Provider 启动 |
| RPOOL-02 | 三个不同节点的执行区间重叠约 **6.08 秒**；第四任务等待，retry_count 为 0，释放后成功；每节点一个槽 |
| RPOOL-03 | 三条同 Session 消息按序启动；第二条冻结历史包含第一条晚到回复，不包含第三条输入 |
| RPOOL-04 | 接受后首次响应丢失，恢复同一 Invocation，Provider 启动数 1 |
| RPOOL-05 | 归属提交后、SDK 前退出，启动数 0，结果为 outcome unknown，无新 attempt |
| RPOOL-06 | 已发送事件后断流，重放原序列并成功；启动数 1 |
| RPOOL-07 | Worker SIGKILL 后版本从 1 到 2，Invocation/digest/owner/deadline 不变；旧版本的结果和重试写入被拒绝 |
| RPOOL-08 | Runtime SIGKILL 后唯一 unknown 终态，未自动重跑；新实例证明旧固定容器已停止 |
| RPOOL-09 | Runtime 成功后杀死尚未提交结果事务的 Worker；接管后仅一条助手消息、一个 Delivery 意图；另验证由不同节点最小 recover 重放，无 Principal 重建 |
| RPOOL-10 | PostgreSQL 取消/准入竞争具有唯一事务顺序；取消先提交无法启动执行；HTTP 排队取消幂等 |
| RPOOL-11 | 完全不发送取消通知，Runtime 约 **4.65 秒**自行轮询停止；不响应取消的适配器被容器级终止，后续 Session 任务未提前放行 |
| RPOOL-12 | PostgreSQL 暂停 **39 秒**，独立 watchdog 仍终止不响应取消的执行；恢复后 unknown、停止证明、无重跑；过期租约不可续活 |
| RPOOL-13 | 原节点占满时 probe 被拒绝，池内空闲节点可 probe；执行期间的恢复/取消可用，不争抢执行槽 |
| RPOOL-14 | 排空节点不再接新任务，原执行完成，池显示 DEGRADED；实例 Header 不匹配被拒；发布门禁拒绝仍有消费者，停止 Worker 后变为 ready |
| RPOOL-15 | Grant/协议/摘要/节点/实例/URL 边界及取消登录/管理权限/目标不存在回归；真实数据库角色不能写 Job、RBAC、快照、身份绑定，也不能改删事件/账本 |
| RPOOL-16 | PostgreSQL 验证活动或未提交结果不能清正文；终态停止后清正文保留身份；真实容器的完整请求重放及最小 HTTP 恢复均返回 410，启动数不增加；接管快照保持不变 |
| RPOOL-17 | 5 秒心跳下 RabbitMQ 暂停 **16 秒**后恢复无重复执行；全池不可用按有界间隔延期，准入过期唯一 TIMEOUT、启动数 0；延期事务失败回滚，不遗留假交接 |
| RPOOL-18 | 确定性暂时失败产生一个业务重试，上一 attempt 已停止后才启动；同 Session 后续消息不越过 RETRY_WAIT |
| RPOOL-19 | PASS：三个独立节点真实 SDK 执行重叠 6.15 秒；每节点最多 1；上下文、SDK cwd、透明沙盒标记和凭据环境检查通过 |
| RPOOL-20 | PASS：三 Worker 六任务 17.29 秒排空，排队 P95 8.48 秒、SDK P95 8.44 秒；取消停止 8.31 秒、Worker 接管并提交 34.07 秒；测量范围见真实报告 |

## 复现与运维

用 [隔离执行脚本](../../../../../backend/tests/support/runtime_pool/run.py)、[证据收集脚本](../../../../../backend/tests/support/runtime_pool/collect.py) 和 [三节点 Compose](../../../../../backend/tests/support/runtime_pool/compose.yml) 复现容器场景；本地和 PostgreSQL 回归分别见 [池状态测试](../../../../../backend/tests/test_runtime_replica_pool.py) 与 [独立连接测试](../../../../../backend/tests/test_runtime_replica_pool_postgres.py)。PostgreSQL 测试必须显式设置隔离的 `RUNTIME_POOL_TEST_DSN`。

升级、排空、unknown 处理、正文保留和整套回退边界见 [运维流程](../../../../../docs/operations/runtime-replica-pool.md)。本次没有前端变更，未运行浏览器或前端构建；真实 Provider 证据单独列出；本次未执行生产发布。
