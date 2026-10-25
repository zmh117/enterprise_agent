## ADDED Requirements

### Requirement: Compose必须部署固定成员的Runtime副本池
首期 Compose SHALL 在同一主机默认启动两个独立 Python Runtime 节点及两个 Agent Worker，节点共享不可变发布镜像和配置模板，每个 Runtime 命名服务 MUST 固定一个容器、一个 Uvicorn 进程和一个真实执行槽。节点 ID 与地址映射 SHALL 来自受控部署配置且唯一，所有调用方使用同一池定义；每次启动产生新的 instance_id。系统 MUST 保留 Runtime 只读容器、非 root、私有控制网络、独立 tmpfs/沙盒和最小凭据挂载边界，不挂 Docker socket、不动态创建容器、不开放任意 URL 注册。

#### Scenario: 默认启动
- **WHEN** 正常构建并启动 Compose
- **THEN** 两个固定节点及两个 Worker 按同一发布工作，业务只需现有统一 API，无需选择物理 Runtime

#### Scenario: 增加第三节点验收
- **WHEN** 部署映射新增第三个唯一节点并增加第三个 Worker
- **THEN** 三个不同 Session 可并行占用三个节点，不需要修改 Agent/Application Publication 或业务请求

#### Scenario: 节点映射或进程拓扑非法
- **WHEN** 节点 ID 重复、地址不在部署允许范围、单节点服务被扩成多个容器或配置多个 Uvicorn 进程
- **THEN** 部署/启动验证失败，不能将不稳定地址视为可恢复的唯一执行节点

### Requirement: Runtime池就绪必须区分可用性容量与发布一致性
系统 SHALL 聚合各节点的构建/协议/池能力、依赖就绪、instance、排空和占用状态。全部成员合规为 READY，部分成员缺失但仍有合规节点为 DEGRADED，无合规节点为 UNAVAILABLE；全池满载 MUST 单独报告容量占满，不能误报配置或授权不可用。池状态 SHALL 接入现有组件就绪评估与模型 probe 选路，不使管理面因临时满载整体失效，不改写业务应用原有接线状态含义。

#### Scenario: 一个节点不可用
- **WHEN** 两节点池中的一个失联而另一个仍合规
- **THEN** 池报告 DEGRADED 与安全原因，新任务可使用剩余节点，原失联执行按其归属处理

#### Scenario: 全部节点忙
- **WHEN** 所有合规节点均占用执行槽
- **THEN** 报告容量等待，保留准入排队、恢复与取消能力，不因满载失败管理读写

#### Scenario: 节点发布不一致
- **WHEN** 某节点缺少池能力或其构建/协议不符合本次发布
- **THEN** 该节点不参与新执行，报告明确差异，不能回退为旧单地址服务

#### Scenario: 全部节点不可用
- **WHEN** 没有可用的合规节点
- **THEN** 池报告 UNAVAILABLE，已持久化任务保留至准入截止或显式取消，不在内存静默丢弃

### Requirement: Runtime池必须保持最小数据库权限和正文隔离
数据库 migration SHALL 明确 Job 控制字段、Invocation 生命周期、不可变请求快照和账本约束，并相应更新最小 grants。Runtime MUST 只能读取必要绑定/受控快照、更新所属 Invocation 的指定执行字段及事件/终态账本；不得写 Job、Session、Delivery、RBAC 或平台审计。普通管理读、日志、指标与队列 MUST 不暴露请求快照正文、认证材料或内部凭据。迁移及 PostgreSQL 实际角色权限 MUST 有独立验证，SQLite 行为不得替代生产数据库竞争和权限证据。

#### Scenario: Runtime尝试越界写Job
- **WHEN** 使用实际 Runtime 数据库角色修改 Job、Session 或 Delivery
- **THEN** PostgreSQL 权限拒绝，角色仍能完成必要的 Invocation 领取/续租/事件/终态操作

#### Scenario: 普通观测读取池状态
- **WHEN** 管理端或日志展示节点、等待、归属和取消信息
- **THEN** 仅展示受权安全元数据，不读取完整请求正文或认证材料

### Requirement: Runtime池必须支持有证据的排空与协调切换
节点排空 SHALL 停止新执行和新 probe，同时继续原 Invocation 的重连、取消与终态服务；仅在本地执行停止和终态持久化后正常移除。Worker 排空 SHALL 停止新消费并完成当前任务或持久化交接观察责任。池合同升级 MUST 遵守单一发布和无旧消费者的部署门禁；没有新归属事实的旧非终态执行不得凭当前配置补写归属。失败回退不得让旧单地址程序继续推进新池的非终态数据。

#### Scenario: 节点正常排空
- **WHEN** 节点进入排空但仍有活跃 Invocation
- **THEN** 新任务选其他节点，原任务仍可重连/取消，直到停止及终态落库后才退出

#### Scenario: 强制退出未完成节点
- **WHEN** 节点无法在有界宽限内停止 SDK
- **THEN** 隔离并退出整个容器，保留中断/未知结果及停止证据，不宣称执行已无损转移

#### Scenario: 切换前仍有旧执行
- **WHEN** 部署预检发现旧 Runtime/Worker 仍在执行或消费，或旧非终态事实尚未收敛
- **THEN** 阻止恢复入口，先排空或显式终止，不启动双写和旧服务 fallback

#### Scenario: 固定节点重启后确认旧实例停止
- **WHEN** 已验证单节点单容器不变量，同一固定服务返回新的启动实例身份
- **THEN** 恢复路径可记录旧容器替换的停止证据
- **AND** 地址不明、实例冲突或不可达不能替代这一证据

### Requirement: Runtime池必须提供分层并发与故障验收证据
交付 SHALL 分别记录静态/合同、真实 PostgreSQL 多连接竞争、真实 Compose 故障注入及真实 SDK/Provider 验收；每条证据 MUST 关联 case_id、拓扑、构建身份、操作时间、预期/实际和最终持久化事实。并行证据 MUST 来自不同节点真实执行区间重叠及每节点最大占用，不能仅依据线程数、容器 healthy、请求接受或消息 ACK。SDK 启动次数 MUST 按 Invocation 统计，不把一次多轮模型交互误计为重复执行。

#### Scenario: 三节点并行与满载
- **WHEN** 三个不同 Session 的长任务在三节点执行并提交第四个任务
- **THEN** 证明前三个执行区间重叠、每节点占用不超过1、第四个持久化等待且业务 retry_count 不变

#### Scenario: 归属恢复取消故障矩阵
- **WHEN** 执行重复请求、响应丢失、Worker/Runtime 崩溃、失租迟到写入、取消完成竞争、数据库中断和终态后事务失败测试
- **THEN** 逐项证明唯一执行归属、唯一终态、可恢复观察、取消不丢失、停止前不释放槽及业务结果/投递意图幂等

#### Scenario: 仅确定性Provider通过
- **WHEN** 合同或 Compose 测试使用确定性 Provider 而未执行真实模型
- **THEN** 只能报告相应受控测试通过，真实 SDK/Provider 并行验收必须保持 NOT_RUN

#### Scenario: 真实运行与容量报告
- **WHEN** 使用实际 SDK/Provider 完成多节点执行和有界负载测试
- **THEN** 报告执行重叠、上下文/凭据/沙盒隔离、模型限流、排队/执行 P50/P95/P99、积压、错误率和取消/接管延迟
- **AND** 标明硬件/负载/模型边界，不将节点数或一次测试吞吐转化为生产容量保证

#### Scenario: 提案阶段完成
- **WHEN** proposal、design、delta specs、tasks 通过文档校验但实现和运行尚未执行
- **THEN** 只报告提案完备，所有实施与真实验收任务保持未勾选

## MODIFIED Requirements

### Requirement: 延期能力不得被误报为已验证
验收报告 MUST 按本次实际运行证据分别列明已验证、失败及未验证范围。真实 Oracle 11.2.0.4、生产 HTTPS/HMAC、Worker 运行中崩溃恢复和任务取消，只有在对应目标环境与链路实际执行并具有证据后，才可报告该范围已验证；单个 Runtime 池的通过不得替代其他组件、渠道端到端链路或历史延期项目的验收。

#### Scenario: 本地没有 Oracle
- **WHEN** 本次验收仅完成 Oracle 静态、单元或测试替身检查
- **THEN** 报告必须把真实 Oracle 连接标为 deferred，Oracle Resource Revision 不得进入 PUBLISHED

#### Scenario: 本地 HTTP 链路通过
- **WHEN** Compose 内 HTTP Webhook 功能验证成功
- **THEN** 报告只能声明本地功能通过，不得声明公网生产安全

#### Scenario: Runtime池故障验收已有证据
- **WHEN** 当前 Runtime 池已实际完成 Worker 崩溃接管和任务取消并保存构建、拓扑、归属及停止证据
- **THEN** 报告可以声明该 Runtime 池范围通过，并继续列出未运行的 Oracle、生产 HTTPS/HMAC、Grafana 或渠道端到端范围
- **AND** 不修改历史报告和未运行任务的原有状态
