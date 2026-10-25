本清单区分实现与运行验收。已勾选实现项已具备代码及相应局部回归；第 8 至 12 节仍以实际验证结果逐项记录，不能以局部通过代替整体验收。proposal/design/specs 的生成及文档校验不构成实现或运行验收的完成。依赖见 [设计](design.md)；规范见 [执行与投递](specs/execution-delivery/spec.md)、[渠道与会话](specs/channel-conversation/spec.md)、[平台运维](specs/platform-operations/spec.md)。

## 1. 持久化模型与合同

- [x] 1.1 增加 Job 控制租约、领取版本、取消意图及 attempt 准入截止字段；补齐状态转换条件和迁移约束，禁止无条件 RUNNING → PENDING。（D2/D3/D8）
- [x] 1.2 建立 Invocation PREPARED/RUNNING/TERMINAL 元数据、唯一 job/attempt、不可变 owner 实例、执行期限和停止证据；替换旧 claim 的运行用途，消除双重归属事实。（D2/D4）
- [x] 1.3 建立不可变受保护请求快照及 digest 校验；实现身份标识与大块正文分开保留，活动执行/未提交结果不得提前清理。（D2/D5，RPOOL-16）
- [x] 1.4 定义池节点状态、实例 Header、最小 recover/cancel 请求及结构化控制错误；更新合同 schema/fixtures，保留现有执行版本与安全绑定且不新增旧服务 fallback。（D4/D5）
- [x] 1.5 更新 PostgreSQL Runtime grants、相关 schema 事实源和索引；Runtime 无 Job/Session/Delivery/RBAC 写权限，普通读取不开放 snapshot 正文。（D2，RPOOL-15）

## 2. Worker控制权和可靠调度

- [x] 2.1 以 Job lease/claim version 实现原子领取、续租和交接；删除 redelivery 直接抢占 RUNNING 的路径，添加旧 owner 条件写入保护。（D3，RPOOL-07）
- [x] 2.2 在首次执行前原子冻结请求并创建 PREPARED；接管和容量延期复用原 snapshot/digest，新业务 attempt 才重新准备。（D4/D5，RPOOL-04、RPOOL-16、RPOOL-18）
- [x] 2.3 将 Job 结果、助手消息、重试和逻辑 Delivery 意图的写入绑定当前控制版本，保持跨表事务及唯一键；失租 Worker 停止业务错误处理和取消。（D3，RPOOL-07、RPOOL-09）
- [x] 2.4 保留 prefetch=1 和每 Worker 一个 Job，执行线程与 RabbitMQ I/O/续租分离，ACK/NACK 回到原连接线程。（D8，RPOOL-17）
- [x] 2.5 在 Outbox 中实现容量/会话/恢复延期、独立准入预算及有界退避；保存后才 ACK，不增加业务 retry_count，验证迟到准入竞争。（D8，RPOOL-02、RPOOL-17）
- [x] 2.6 扩展现有 job-dispatch-worker 的有界扫描，恢复丢失控制者/唤醒的任务；扫描与多 Worker 重投幂等，不新建第二次模型执行。（D3/D9，RPOOL-07、RPOOL-17）

## 3. Runtime准入与执行生命周期

- [x] 3.1 建立每进程一个真实执行槽，将 Job 与模型 probe 纳入同一准入控制；控制接口无需取得执行槽，busy 不创建等待执行线程。（D1/D8，RPOOL-02、RPOOL-13）
- [x] 3.2 在有效 Grant、实例身份和冻结请求校验后原子领取 PREPARED；只允许提交成功者启动 SDK；竞争失败读取 owner，不生成孤儿错误。（D4，RPOOL-01、RPOOL-05）
- [x] 3.3 实现 Invocation 独立续租、不可续活的过期 lease、绝对执行 deadline 和失租 watchdog，事件/终态写入验证 owner/state/lease。（D6，RPOOL-08、RPOOL-12）
- [x] 3.4 将事件先落库后发送；将唯一终态、账本和停止证据一致提交，处理保存失败与完成/失联扫描竞争。（D4/D6，RPOOL-06、RPOOL-09、RPOOL-12）
- [x] 3.5 实现 SDK/子进程停止确认、槽位延迟释放和超清理宽限的容器级退出；节点重启产生新 instance，不仅清理 Python 线程。（D6，RPOOL-08、RPOOL-11、RPOOL-14）
- [x] 3.6 为有界恢复扫描提供安全中断终结路径，不伪造模型输出或完整审计；缺少停止证明的 Invocation 保持可观测阻塞。（D6，RPOOL-05、RPOOL-08、RPOOL-12）

## 4. 池选路和恢复客户端

- [x] 4.1 扩展 Runtime Client 的受控成员映射与候选轮转；验证 node ID/URL/构建身份/池能力，拒绝任意响应 URL 和重定向。（D1，RPOOL-14、RPOOL-15）
- [x] 4.2 按结构化码处理 busy、unavailable、owner/instance mismatch、digest conflict 和 recovery expired；传输异常先查持久化事实，不直接增加 attempt。（D5，RPOOL-04、RPOOL-05、RPOOL-16）
- [x] 4.3 实现原启动实例重连、最小 recover、跨节点已完成终态重放；复用原 sequence 去重与有界审计校验，不重新加载模型执行。（D5，RPOOL-06、RPOOL-09、RPOOL-13）
- [x] 4.4 实现当前授权下的恢复 Grant 刷新与原持久化绑定校验；不重建上下文、不延长原执行截止、不因缺少旧认证重新跑模型。（D5，RPOOL-15、RPOOL-16）

## 5. 持久化取消与排空

- [x] 5.1 提供 `/api/agent/jobs/{job_id}/cancel`，复用 jobs.manage、目标业务范围、CSRF、防枚举和安全审计；不接受任意节点或 Invocation 覆盖。（D7，RPOOL-15）
- [x] 5.2 事务化保存 Job/Invocation 取消意图，处理准备/领取竞争、重复取消及 terminal-first/cancel-first 两种顺序。（D7，RPOOL-10、RPOOL-11）
- [x] 5.3 实现按 owner 通知与续租/控制轮询补偿；准确区分 cancel_requested、cancelled、already_terminal、outcome_unknown，保持现有 Job 状态枚举。（D7，RPOOL-11）
- [x] 5.4 调整 Worker shutdown/HTTP disconnect 行为为排空或可靠交接；Runtime 排空停止新任务但继续原执行控制，强制退出保留停止/未知结果证据。（D7/D10，RPOOL-07、RPOOL-14）

## 6. 会话串行与上下文

- [x] 6.1 基于完整 Session key、输入 sequence 和 Job ID 建立头部资格与短事务锁；Dispatcher 预筛选、Worker 原子复核，不建立全局锁。（D9，RPOOL-03）
- [x] 6.2 处理 WAITING_INPUT、RETRY_WAIT、排队取消和未确认停止的前序执行；结果提交并停止后经 Outbox 唤醒下一条，扫描补偿。（D9，RPOOL-03、RPOOL-08、RPOOL-18）
- [x] 6.3 将上下文首次构建移到取得头部资格之后；按前序 Job 归属包含晚到的助手回复、排除后续输入，保留摘要预算/身份边界和冻结恢复。（D9，RPOOL-03、RPOOL-16）

## 7. 部署配置与运行可观测性

- [x] 7.1 用 Compose 共享模板配置两个固定命名 Runtime 和两个 Worker，提供三节点验收拓扑；校验每节点单容器/单进程、独立 tmpfs 和网络/凭据边界。（D1，RPOOL-02、RPOOL-14）
- [x] 7.2 接入节点和池就绪聚合，区分 READY/DEGRADED/UNAVAILABLE 与容量占满；模型 probe 及所有旧单地址调用方使用统一池配置。（D10，RPOOL-13、RPOOL-14、RPOOL-17）
- [x] 7.3 在现有运行记录/状态接口增加必要归属、控制版本、等待原因、取消与停止状态，补充占用/延迟/恢复指标，不输出正文或凭据。（D10，RPOOL-15、RPOOL-20）
- [x] 7.4 编写排空、节点替换、旧执行收敛、整套发布切换及失败回退流程；阻止旧 Worker 与新池数据混跑，验证固定实例替换证明。（迁移计划，RPOOL-14）

## 8. 本地合同与静态验证

- [x] 8.1 完成状态机、结构化错误、授权、取消竞争、Snapshot 摘要、事件重放及现有 1.4/1.5 合同回归；用明确可控的 SDK 启动计数断言重复执行。（RPOOL-01、RPOOL-04、RPOOL-06、RPOOL-10、RPOOL-11、RPOOL-15、RPOOL-16）
- [x] 8.2 完成会话头部、输入等待、重试、后来输入与前序晚到回复的回归；验证不同完整 Session key 不被错误串行。（RPOOL-03、RPOOL-18）
- [x] 8.3 完成 migration/schema/grants 定义校验及适用 Ruff、类型、编译检查；若修改现有状态展示，运行对应前端检查，不把 SQLite 结果作为 PostgreSQL 并发证据。
- [x] 8.4 运行 Compose 配置校验、Markdown 链接、当前 change 严格 OpenSpec 校验及 `git diff --check`；记录通过、失败和未运行范围。

## 9. 真实PostgreSQL竞争与权限验证

- [x] 9.1 使用隔离 PostgreSQL 的独立连接/进程和同步屏障验证 A/B 领取、取消/领取、完成/取消/失联扫描竞争，证明唯一 owner 和终态。（RPOOL-01、RPOOL-10、RPOOL-11、RPOOL-12）
- [x] 9.2 验证 Worker 接管后旧版本的结果/重试/Delivery 写入被拒绝，结果事务回滚可从原终态恢复，逻辑投递意图唯一。（RPOOL-07、RPOOL-09）
- [x] 9.3 验证 Session 头部与业务重试顺序、正文清理和身份保留、当前实际数据库角色的最小权限与越权拒绝。（RPOOL-03、RPOOL-15、RPOOL-16、RPOOL-18）

## 10. 真实Compose与确定性Provider故障验收

- [x] 10.1 使用三个真实 Runtime 容器、三个 Worker、PostgreSQL/RabbitMQ 和可阻塞确定性 Provider，验证执行区间重叠、每节点最大1、第四任务持久化等待及同会话顺序。（RPOOL-02、RPOOL-03）
- [x] 10.2 注入接受后响应丢失、领取提交后崩溃、流中断、Worker 杀进程、Runtime 杀进程与终态后事务失败；记录 SDK 启动计数和全部最终状态。（RPOOL-04、RPOOL-05、RPOOL-06、RPOOL-07、RPOOL-08、RPOOL-09）
- [x] 10.3 注入取消通知丢失、SDK 停止延迟、数据库中断/旧进程恢复及原节点满载；证明不提前释放槽/会话、控制操作不占槽和 probe 共用槽。（RPOOL-10、RPOOL-11、RPOOL-12、RPOOL-13）
- [x] 10.4 验证排空/实例变化、长任务心跳、Broker 重连、全部节点不可用、延期事务失败和准入超时；无热循环或无法恢复的 ACK。（RPOOL-14、RPOOL-17）
- [x] 10.5 汇总 RPOOL-01 至 RPOOL-18 的逐项 JSON/报告证据及清理结果，所有 case 具有需求和任务映射；停止仅本次创建的测试容器，不影响其他环境。

## 11. 真实SDK和Provider验收

- [x] 11.1 在受权目标环境使用真实 SDK/Provider 执行三个不同会话的任务，证明真实执行重叠、每节点最大1、上下文/凭据/沙盒隔离；记录模型限流和实际结果，不能用确定性测试替代。（RPOOL-19）
- [x] 11.2 在明确硬件、节点数、模型和合成负载下完成有界容量测试，记录排队/执行 P50/P95/P99、积压、错误率、取消/接管时延及资源占用；提出基于实测的节点数和预算建议。（RPOOL-20）

## 12. 交付与规范收敛

- [x] 12.1 发布最终验收清单，区分本地静态/合同、PostgreSQL、Compose 确定性 Provider、真实 Provider 和容量结果；未运行项目保持未勾选，并列出限制及运维处理路径。
- [x] 12.2 在实际实现和相应验收完成后，再按同步/归档工作流处理三个 canonical 领域；不得因提案完备或文档校验通过补勾运行任务。
