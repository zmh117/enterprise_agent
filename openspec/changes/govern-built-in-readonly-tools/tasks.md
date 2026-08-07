## 1. 前置 Gate 与现状清单

- [x] 1.1 确认 `stabilize-platform-runtime-foundation` 的最终 Resource Revision、Application Publication、Job fact 和 Secret 模型已归档或同步，并记录本变更采用的 schema head
- [x] 1.2 生成只读现状报告，列出代码 Registry 工具、`tool_definition`、`agent_tool_binding`、`legacy-v1`、活动 Agent/Application Publication、非终态与可恢复 Job 引用数量
- [x] 1.3 生成 topology/resource 现状报告，识别缺省虚节点、cloud/edge 伪基地、一个 slot 单绑定限制、全局/环境 Loki 和车间前缀数据
- [x] 1.4 为迁移报告、发布校验和运行拒绝定义稳定错误码、脱敏字段白名单与 correlation-id 契约

## 2. 数据模型与数据库迁移

- [x] 2.1 先添加迁移级测试，覆盖不可变 revision、唯一 Identifier/版本/digest、生命周期约束、外键保护和幂等发布约束
- [x] 2.2 新增 Built-in Tool Manifest projection、Installation、Verification Evidence、Tool Release 与 Lifecycle Audit 表及索引
- [x] 2.3 新增 Agent Tool Envelope、Application Tool Allowlist 和 1..N Application Resource Mapping 表，保存规范化 hash 和精确 revision 外键
- [x] 2.4 新增 Workshop Partition Policy Identity/Draft/Evidence/Published Revision 表，并约束 DB 单前缀、Redis 多精确前缀和内容不可变
- [x] 2.5 新增 Loki Scope Policy Identity/Draft/Evidence/Published Revision 表，约束唯一 exact key、Environment + 可选 Base 范围和 Resource Revision
- [x] 2.6 扩展 Job/Tool Call 存储以保存不可变 Tool Execution Snapshot、实际 placement、Resource/Policy revision 与安全范围 hash
- [x] 2.7 新增 legacy 迁移账本、隔离原因和零引用报告视图；迁移只增加结构，不改写或删除用户历史数据

## 3. 代码 Manifest、安装对账与 Tool Release

- [x] 3.1 先添加 Registry 契约测试，覆盖稳定 Identifier、保留命名空间、SemVer、Schema hash、Verifier Plan、资源槽和安全边界扩张检测
- [x] 3.2 为所有现有内置只读工具建立规范化代码 Manifest，并生成可重复的 Handler Version 与 Implementation Digest
- [x] 3.3 实现幂等 reconcile 服务和 CLI/API，正确计算 INSTALLED、MISSING、DRIFTED，且不自动验证或发布
- [x] 3.4 为各工具实现固定机器 Verifier，保存绑定 digest/verifier version 的脱敏有界证据并在内容变化时失效
- [x] 3.5 实现幂等 Tool Release Publish，冻结精确 Manifest/证据并拒绝未安装、漂移、未验证或过期证据
- [x] 3.6 实现 ACTIVE、DEPRECATED、DISABLED、ARCHIVED 状态机、恢复/依赖保护和生命周期健康分离测试

## 4. RBAC、管理 API 与审计

- [x] 4.1 注册并迁移 `builtin_tools.read/reconcile/verify/publish/lifecycle` 权限，验证它们不隐式授予资源、Agent/Application 发布或运行权限
- [x] 4.2 将运行 `tool:use` Grant 目标改为稳定 Built-in Tool Identifier，并补充 Tool Grant 与数据范围双重校验测试
- [x] 4.3 实现只读工具目录、详情、reconcile、verify、publish、lifecycle 和依赖摘要 API，所有写操作使用并发/幂等保护
- [x] 4.4 为允许和拒绝的管理动作记录 actor、对象、revision、digest、证据、原因和 correlation id，验证无 Secret 与无界响应泄露

## 5. 可变深度 Topology 与资源组合

- [x] 5.1 先添加 topology 契约测试，覆盖 Environment leaf、Base leaf、Workshop leaf、无虚节点和非法父子关系
- [x] 5.2 重构 PostgreSQL topology 与 API projection，使 Base/Workshop 可选且禁止 `default`、`none` 等占位节点
- [x] 5.3 增加可选 Resource Placement 枚举与校验，只允许实际资源使用 `cloud`/`edge`，不写入业务 topology 或访问 Grant
- [x] 5.4 实现 Application 1..N Resource Mapping Draft/Publish API，并冻结 target scope、placement、Resource Revision 和适用策略 revision
- [x] 5.5 实现发布期有限目标矩阵展开，拒绝必需槽零命中、多命中、环境/基地重叠、global/environment Loki 重叠和非 Published 依赖
- [x] 5.6 持久化不可变解析表与 hash，验证 Resource/Policy 新 revision 不改变既有 Application Publication

## 6. Workshop 数据库与 Redis 隔离策略

- [x] 6.1 先添加 Policy 校验测试，覆盖 DB 恰好一个非空精确前缀、Redis 一个或多个完整 namespace 前缀及模糊输入拒绝
- [x] 6.2 实现 Workshop Partition Policy Draft、验证、发布和复制新 Draft 服务，Published Revision 禁止原地修改
- [x] 6.3 为 MySQL、SQL Server、Oracle Schema Directory 增加方言感知的冻结表前缀过滤与响应边界测试
- [x] 6.4 在数据库执行前解析并校验全部物理表引用，覆盖 JOIN、CTE、别名、跨前缀、多语句、动态表名和无法可靠解析的失败关闭
- [x] 6.5 在 Redis GET/SCAN 网关强制完整 namespace 前缀，覆盖给定真实 key 示例、跨车间、前置通配符、正则、迭代与结果上限
- [x] 6.6 分离 Redis Resource PING 测试与 Policy 有界 `prefix*` SCAN 验证，只保存 count/truncated/hash/time 并允许 zero-match warning
- [x] 6.7 在 Application Publish 校验同一 Workshop 的 cloud/edge Mapping 使用相同 Partition Policy Revision

## 7. Loki 资源、标签发现与 Scope Policy

- [x] 7.1 先添加 Loki 管理契约测试，覆盖 global/environment scope、Draft 测试会话、级联 key/value 发现、上限和内容变化失效
- [x] 7.2 扩展 Loki Resource Draft/Revision 校验，只允许 global 或精确 Environment scope，并拒绝 Base/Workshop/placement 连接范围
- [x] 7.3 实现测试后有界 label key 与级联 value 发现 API，强制 exact 先决条件、超时、时间窗、数量、字节和脱敏规则
- [x] 7.4 实现 Loki Scope Policy Draft 校验，拒绝重复 key、OR、否定、正则、通配、任意 LogQL 和一个 Policy 多 Base
- [x] 7.5 实现 Scope Policy verifier/publisher，绑定 Resource Revision 与条件 hash，并保存 zero-match warning 而不自动放宽
- [x] 7.6 在运行时强制注入 Published Scope Policy，并只允许 Manifest 白名单诊断过滤进行 AND 合并；覆盖 tenant/强制 key 覆盖拒绝
- [x] 7.7 删除新路径中的 Workshop label 自动注入，把 `role/replica/app/logtype` 限定为诊断过滤，并添加不得作为权限/placement 的回归测试
- [x] 7.8 实现 EMPTY/DEGRADED 健康投影，区分零结果与上游失败且不自动改变 Release/Policy 生命周期

## 8. Agent/Application Publication、Job Snapshot 与运行时交集

- [x] 8.1 先添加 Agent Tool Envelope 测试，覆盖同 Identifier 单一 ACTIVE Release、发布时重验和 exact version/digest 冻结
- [x] 8.2 实现 Application Tool Allowlist 子集校验，禁止应用独立选版、自动继承或越过 Agent Envelope
- [x] 8.3 在 Job 创建事务中复制完整 Tool Execution Snapshot，并在队列分发前验证内容 hash 和唯一资源解析
- [x] 8.4 修改 Agent Tool Catalog 构建为 installed exact、lifecycle、Agent、Application、tool-use、target scope、resource mapping、policy 的完整交集
- [x] 8.5 修改 Internal API Platform 信任校验，使用服务 Token 与 Job facts 校验精确 Release/digest/resource/policy，拒绝请求覆盖事实
- [x] 8.6 实现每次 Tool Call 的确定性 placement 选择；多候选未明确时失败关闭，并记录实际 placement 与精确资源事实
- [x] 8.7 修改 retry、Outbox replay 和显式恢复只读取原 Snapshot，并覆盖发布升级、资源轮换、Release DISABLED 和实现 MISSING/DRIFTED 测试

## 9. 管理界面

- [x] 9.1 新增“平台治理 → 只读工具”列表和详情，分开展示 Manifest、Installation、Evidence、Release、Lifecycle、依赖和 Effective 状态
- [x] 9.2 按细粒度 RBAC 实现 reconcile、verify、publish、deprecate/disable/restore/archive 操作及安全确认反馈
- [x] 9.3 扩展“工具资源”详情以管理 Resource Draft、连接测试、Workshop Policy、Loki 级联标签发现、验证和发布，不回显 Secret
- [x] 9.4 更新 Agent 配置页为精确 ACTIVE Tool Release 选择，并显示版本、digest 摘要和 deprecated/drift 健康警告
- [x] 9.5 更新 Application 配置页为 Agent Envelope 显式子集与 1..N Resource/Policy Mapping，提供目标矩阵缺失/重叠校验提示
- [x] 9.6 添加前端权限、并发冲突、不可变历史、zero-match warning、无 placement 和多 placement 交互测试

## 10. legacy-v1 Cutover 与移除

- [x] 10.1 实现 `legacy-tool-migration report`，输出新写入、活动 Publication、非终态/待重试/replay Job 的精确计数和零/单/多候选分类
- [x] 10.2 在写入边界拒绝新的 `legacy-v1` Agent/Application/Job 绑定，并保留受监控的只读兼容路径
- [x] 10.3 为可唯一解析的旧 Agent/Application 创建显式精确新 Publication，不原地修改或重新激活旧 Publication
- [x] 10.4 在维护窗口幂等物化旧可恢复 Job Snapshot，将歧义记录隔离并验证重复执行不产生不同结果
- [x] 10.5 增加移除 Gate，要求连续报告证明活动 legacy 引用为零且真实运行/投递验收通过
- [x] 10.6 删除 legacy 兼容读取、旧写 API 和旧 Publication 激活/回滚入口，保留终态历史字段、审计查询和迁移证据

## 11. 验证、上线与回滚证据

- [x] 11.1 运行 OpenSpec 严格校验、数据库迁移 up/down 或备份恢复演练、后端单元/集成测试和前端测试
- [x] 11.2 在 Compose 中覆盖 Environment/Base/Workshop 三种叶子深度，以及无 placement、cloud-only、edge-only、cloud+edge 资源组合
- [x] 11.3 使用真实示例验证 GL001/GL002/CZ002 数据库表前缀和 Redis key namespace 的允许、跨范围拒绝与 zero-match 行为
- [x] 11.4 验证当前 global Loki 与至少一个 environment Loki 配置，覆盖级联发现、环境 + 可选基地强制 selector、空结果和越界拒绝
- [x] 11.5 验证 `Runtime → Job → Worker → Internal API Platform → DB/Redis/Loki Tool Call → Delivery` 完整链，并保存 Publication、Snapshot、审计和回执证据
- [x] 11.6 执行 MISSING、DRIFTED、DISABLED、资源加载失败、策略歧义和重试故障注入，证明全部失败关闭且无跨范围访问
- [x] 11.7 在移除前后各执行一次备份与回滚演练，证明不会恢复 legacy 新写入或让精确 Job 浮动到新版本
