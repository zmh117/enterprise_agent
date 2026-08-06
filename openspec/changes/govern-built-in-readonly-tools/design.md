## Context

平台已有代码内置的 DB、Redis、Loki 与上下文只读工具，Agent 配置页目前只保存工具名称开关。数据库中仍存在 `legacy-v1` 名称级绑定，现有资源绑定模型通常假定“一个 slot 对应一个资源”，Topology 也默认 Environment/Base/Workshop 三层齐全。真实部署并不满足这些假设：有的环境没有基地或车间，有的基地下多个车间共用数据库和 Redis、依赖表名前缀或 key namespace 隔离，有的资源同时存在 cloud/edge 两份，有的完全没有 placement；Loki 当前由一个实例采集全部环境，未来又需要允许每环境独立实例。

本设计依赖 `stabilize-platform-runtime-foundation` 建立的 Resource Identity、Draft、Verification、不可变 Published Revision、Application Publication Binding、Job Execution Scope、Last Known Good 和 Secret 引用边界。该依赖变更归档前，本变更不得开始数据库迁移；若其最终模型发生变化，必须先同步本设计和 delta specs。

关键参与者包括平台管理员、Agent 配置管理员、业务应用发布者、Internal API Platform、Agent Worker，以及只读取审计和运行状态的运维人员。所有管理和运行路径都必须保留当前“代码实现、数据库治理、应用组成、身份权限、数据范围”相互独立的边界。

## Goals / Non-Goals

**Goals:**

- 使每次工具调用都能追溯到精确的代码实现、Tool Release、Agent/Application Publication、Resource Revision 和隔离策略 revision。
- 支持真实存在的可变深度业务目标，以及同一目标下可选的 cloud/edge 物理资源副本。
- 对共享数据库和 Redis 建立可版本化、可验证、运行时强制执行的车间隔离策略。
- 让全局或环境级 Loki 通过管理员发现并发布的精确标签 selector 强制收窄查询范围。
- 用两阶段迁移彻底淘汰 `legacy-v1` 活动运行路径，同时保留历史审计。
- 所有歧义、漂移和缺失依赖均在访问上游前失败关闭。

**Non-Goals:**

- 不允许管理员创建任意 HTTP、MCP、SQL、Shell、脚本、模板或通用执行器；外部业务接口继续属于 API Capability。
- 不给 DB 增加多前缀、正则或通配隔离；第一阶段每个车间恰好一个表名前缀。
- 不把 cloud/edge 变成组织结构、业务目标或用户权限维度，也不要求所有资源配置 placement。
- 不声称 Loki 能按 GL001/GL002 等车间隔离；`role`、`replica`、`app`、`logtype` 不承担授权语义。
- 不提供 Loki selector 的 OR、否定、正则、任意 LogQL 或用户自由编辑。
- 不增加双人审批或审批队列；一个具备相应权限的管理员即可执行治理操作，并完整审计。
- 不在本变更中引入 Customer/Organization 高于 Environment 的新业务层级。

## Decisions

### 1. 代码 Manifest 是实现事实，数据库 Release 是治理事实

每个内置只读工具在代码中提供规范化 Manifest：稳定 `tool_identifier`、语义版本、Handler Version、输入/输出 schema、模型可见 description、风险等级、必需运行权限、逻辑资源槽、固定 verifier plan 和 Implementation Digest。Digest 覆盖规范化 Manifest 与实现构建标识，发布后不可修改。

部署或管理员触发 reconcile 时，平台只比较代码 Registry 与数据库 Installation，得到 `INSTALLED`、`MISSING` 或 `DRIFTED`；reconcile 不自动验证或发布。机器 verifier 的证据绑定 Installation、Handler Version、Implementation Digest、Verifier Version 和执行时间。只有当前内容的成功证据可创建不可变 Built-in Tool Release。

数据库不得覆盖代码拥有字段，也不得保存执行代码。相比“数据库动态定义工具”，该模型牺牲无需部署即可扩展的灵活性，但保留代码审查、依赖固定、测试覆盖和可证明的只读边界。

### 2. Release 生命周期与运行健康分离

Tool Release 使用 `ACTIVE`、`DEPRECATED`、`DISABLED`、`ARCHIVED`：

- `ACTIVE` 可被新 Agent Publication 选择并执行。
- `DEPRECATED` 阻止新选择，既有 Publication 可继续执行并显示告警。
- `DISABLED` 阻止所有新调用，但允许通过重新安装、验证和审计后恢复 `ACTIVE`。
- `ARCHIVED` 为终态；仍被活动 Publication 或非终态 Job 引用时不得归档。

Installation 的 `MISSING/DRIFTED`、Resource 的 degraded、Loki 的 EMPTY 等属于健康状态，不自动改变 Release 生命周期。运行时仍按生命周期与当前安装/digest 一起校验；不存在匹配实现时失败关闭。

### 3. 发布链使用两个不可变工具 Envelope

Agent Draft 对同一稳定 Tool Identifier 至多选择一个 `ACTIVE` Release。Agent Publish 冻结 `tool_release_id + handler_version + implementation_digest + public_schema_hash`，形成 Agent Tool Envelope。

Application Draft 引用精确 Agent Publication，只能显式勾选 Envelope 子集。Application Publish 冻结 Application Tool Allowlist 和每个工具资源槽的全部资源映射。应用不能独立换版本，也不会自动继承 Agent 后续新增工具。新 Release、新 Resource Revision 或新策略 revision 都必须显式创建新的 Agent/Application Publication 才能生效。

这与受治理 API Capability 的“Agent 上限、Application 子集”结构一致，但内置工具与 `cap__*` Capability 保持独立命名空间、权限和发布表，避免把代码内置诊断工具伪装成可配置外部接口。

### 4. 业务目标与物理 placement 正交建模

`BusinessTargetPath` 只保存真实存在的层级：

- Environment
- Environment/Base
- Environment/Base/Workshop

父节点不存在时不能创建子节点，未部署的层级不使用 `default`、`none` 或虚拟节点补齐。`ResourcePlacement` 是资源映射的可选字段，第一阶段枚举为 `cloud`、`edge`；没有云边差异的资源该字段必须缺省，提交占位值会被拒绝。同一逻辑基地和车间在 cloud/edge 下仍是同一个业务目标。

用户/角色授权只对 `BusinessTargetPath` 计算。Job 默认取得 Application Publication 为目标配置的全部 placement；每次 Tool Call 必须解析到其中一个明确 placement。若调用语义或系统路由未能在多个候选中确定一个，则失败关闭，不以数组顺序或“优先云端”猜测。选中的 placement 进入 Tool Call 审计，但不扩大用户范围。

### 5. 一个资源槽保存 1..N 条确定性映射

Application Publication 中的逻辑资源槽由多条不可变 Mapping 组成：

`slot + target_scope + optional placement -> resource_revision + optional partition_policy_revision + optional loki_scope_policy_revision`

发布校验先把应用允许的叶子目标展开，再为每个工具、槽、叶子目标和 placement 计算有效候选。环境级或基地级 DB/Redis 资源可由后代目标继承；Loki 只允许 global 或 environment scope。任一必需组合为零候选或多候选都拒绝发布。相同 slot、placement 下环境/基地映射若会覆盖同一叶子目标，也视为歧义；不定义优先级、最长路径或最近父级胜出规则。

运行时只读取 Application Publication 的已验证解析表，不重新搜索“当前资源”。因此 Resource Identity 发布新 revision 不会改变既有应用或 Job。

### 6. Workshop Partition Policy 独立于连接资源版本

Workshop Resource Partition Policy 具有稳定身份、Draft、机器验证证据和不可变 Published Revision，并绑定一个逻辑 Workshop。连接 Resource 与隔离策略分别版本化，以便更换密码或 endpoint 时复用未变化的策略，也能在策略改变时明确触发应用重新发布。

数据库策略第一阶段恰好保存一个非空表名前缀，例如 `GL001_`。Schema Directory 只暴露符合数据库方言规范化比较后的表；SQL 在执行前解析所有物理表引用并逐一校验前缀。不能可靠解析、多语句、动态表名或越界引用均拒绝。

Redis 策略保存一个或多个精确完整 namespace 前缀，例如 `cr999.crmes.CRMES_TEST_GL#GL001@$`。GET 的完整 key 必须以其中一个前缀开始；SCAN pattern 必须先以完整前缀开头，通配符只能出现在前缀之后。禁止 `*GL001*`、正则和跨 namespace 扫描。

Redis 连接测试只验证受治理的地址、认证、TLS、database 和 PING，不枚举 key。策略验证由系统生成每个 `prefix*` 的有界 SCAN，保存匹配数量、是否截断、摘要 hash 和时间，不保存完整业务 key。零匹配是可发布告警，不得放宽前缀。同一 Workshop 在 cloud/edge placement 使用同一 Policy Revision，不允许 side-specific 覆盖。

### 7. Loki 连接、标签发现和强制 Scope Policy 分层

Loki Resource Draft 保存 `base_url`、可选 `tenant_id`、Secret 引用、超时和查询上限。管理员点击“测试连接”后，后端在当前 Draft 和测试会话下执行受限调用：先返回有界 label key 列表；管理员选择 key 后，再按已选精确条件查询该 key 的有界 value 列表。每一步都有超时、数量、字节和时间范围上限，响应不持久化完整 label 目录。

管理员把选择结果保存为 Loki Scope Selector Policy Draft。每条策略恰好表达一个 Environment 和可选 Base，内部条件为唯一 key 的精确 `key=value` AND 集合；禁止重复 key、OR、否定、正则和任意 LogQL。发现结果只是填写辅助证据，不是运行时配置；发布必须重新验证 Draft 内容、Resource Revision、请求边界和可接受响应。

Scope 验证不要求当前存在日志流。零匹配可以带 warning 发布，因为新环境可能尚未产生日志；运行时仍使用原 selector，绝不自动移除条件。长期无结果只将 policy/resource health 标为 `EMPTY` 或 `DEGRADED`，不自动 disable Release 或切换生命周期。

运行时把 Published Scope Policy 作为不可覆盖的强制 selector。Agent 只能添加 Tool Manifest 白名单中的诊断过滤键和值，且最终 selector 为强制条件与附加条件的 AND；冲突或试图改写强制 key 时拒绝。第一阶段 `customer` 之类的环境标签建立一对一平台 Environment 映射，可选基地标签表达逻辑基地；`role=cloud|edge|standalone` 仅描述采集侧，不能代替 placement 或权限。

### 8. Loki 支持全局或每环境资源，但禁止同环境重叠

Loki Resource Revision 的可用 scope 只有 global 或 environment。Application Publication 可以把一个 global Loki 的不同 Scope Policy 映射给多个环境，也可以给每个环境绑定独立 Loki；但同一有效环境不能同时命中 global 和 environment Loki，多个 policy 也不能对同一 slot/环境形成歧义。Loki 不绑定 Workshop，不要求 placement，也不因为 Job 目标含 Workshop 而注入车间标签。

选择该模型是因为现有日志标签中物理 `workshop` 可能表示基地，`replica` 只在部分应用里与车间相关，无法形成可靠授权映射。等未来有稳定的车间标签契约时，再通过独立 change 增加更细范围。

### 9. Job Execution Snapshot 是重试和恢复的唯一依据

创建 Job 时，从活动 Application Publication 复制：Agent Publication ID、Tool Release ID、Handler Version、Implementation Digest、Resource Mapping、目标路径、可用 placements、Workshop Partition Policy ID/revision/hash、Loki Scope Policy ID/revision/hash和授权事实摘要。每次 Tool Call 再记录实际选择的 placement、资源 revision 与有效 selector/hash。

重试、Outbox replay 和显式恢复必须读取原 Snapshot；后续发布、资源轮换或策略变化不得改变原 Job。若冻结的 Release 已 DISABLED/ARCHIVED、实现不匹配或资源不可装载，则按当前安全生命周期失败关闭，但不得浮动升级到替代版本。

### 10. 运行时解析使用显式全交集

候选工具集合为：

`installed_exact ∩ release_callable ∩ agent_envelope ∩ application_allowlist ∩ stable_tool_use_grant ∩ target_scope_allowed ∩ resource_mapping_exact ∩ policy_valid`

模型只看到该交集产生的 Tool 定义。Internal API Platform 在每次调用前使用服务信任根和 Job 事实重新验证相同的精确 ID/digest/snapshot，不能信任 Agent 自报的环境、资源、tenant、prefix 或 selector。任一条件缺失都返回安全的非敏感拒绝原因并审计。

管理权限分为 `builtin_tools.read/reconcile/verify/publish/lifecycle`，不隐式授予 `tool_resources.*`、Agent/Application 发布权限或运行 `tool:use`。运行 Grant 绑定稳定 Tool Identifier；若 schema、风险、所需权限或安全边界发生扩张，必须发布新的稳定 Identifier，而不是依赖旧 Grant 自动授权。

### 11. `legacy-v1` 采用可证明的两阶段迁移

`legacy-v1` 仅表示旧的名称级绑定格式，不是工具版本。迁移不在原记录上伪造版本：

1. **Additive/Cutover 阶段**：部署新表与双读兼容，代码 Registry reconcile 并发布精确 Release；禁止任何新 `legacy-v1` 写入；为 Agent/Application 创建显式新 Publication；对所有非终态、待重试、可 replay 的旧 Job 在受控事务中物化精确 Tool/Resource/Policy Snapshot，无法确定唯一映射的记录进入隔离报告而不自动选择。
2. **Removal 阶段**：迁移报告证明新写入为零、活动 Publication legacy 引用为零、非终态/可恢复 Job legacy 引用为零，并完成真实 `Runtime → Job → Worker → Internal API Platform → Tool Call → Delivery` 验收后，删除兼容读取、旧写 API 和旧 Publication 恢复入口。历史终态记录及其原始 `legacy-v1` 标记保留只读审计。

旧 Publication 不得重新激活或作为回滚目标。回滚只能在 Removal 前停止新流量、恢复上一版代码并继续读取已物化的精确 Snapshot；Removal 后若需回滚，必须恢复阶段前数据库备份与匹配代码，不能重新开启名称级写入。

### 12. 管理界面按“定义、证据、发布、生效”分栏

“平台治理 → 只读工具”展示 Code Manifest、Installation、Verification Evidence、Release 历史、生命周期、依赖 Publication 和 Effective 状态。按钮按 RBAC 独立控制，并在发布前显示精确 digest 与 verifier 证据。

“平台治理 → 工具资源”负责连接 Draft、Secret 引用、测试、标签发现、Workshop/Loki Policy Draft、验证和发布。Agent 页面只选 Tool Release；Application 页面只选 Agent Envelope 子集和已发布的 Resource/Policy Revision，不允许编辑 URL、tenant、Secret、prefix 或 label 条件。

## Risks / Trade-offs

- [本变更与运行时基础变更存在规格重叠] → 实施 Gate 0 要求先归档或同步 `stabilize-platform-runtime-foundation`，再生成最终迁移和模型代码。
- [一个 slot 的 1..N 映射增加发布校验复杂度] → 发布时展开有限目标矩阵并持久化确定性解析表；运行时不做模糊继承搜索。
- [代码部署后 Installation 可能 DRIFTED] → reconcile 只标状态不自动发布，既有调用在 digest 不匹配时失败关闭并保留 LKG/运维证据。
- [Redis 前缀配置错误会导致读不到数据] → 采用手工精确输入、系统生成的有界验证和零匹配 warning；不通过自动扩大范围修复。
- [Loki 标签数量很大或查询代价高] → 发现接口强制级联条件、超时、时间窗、数量和字节上限，并只保存摘要证据。
- [Loki 零匹配可能掩盖配置错误] → 允许发布但明确 warning、持续健康状态和实际查询审计；不牺牲 fail-closed 范围。
- [DISABLED 恢复可能重新暴露旧缺陷] → 恢复前必须确认精确实现仍安装、重新验证且无不兼容替代；全过程审计。
- [旧 Job 无法唯一物化] → 隔离并阻止重试/恢复，提供逐项报告；禁止用当前 latest 或第一个候选猜测。
- [全局 Loki 与环境 Loki 并存造成重复查询] → Application Publish 对每个有效环境做唯一性校验，重叠即拒绝。

## Migration Plan

1. Gate 0：确认依赖变更的 Resource Revision、Secret、Application Publication 和 Job fact 模型已落地；冻结相关 schema 设计并备份 PostgreSQL。
2. 新增 Tool Manifest/Installation/Verification/Release、Publication Envelope、1..N Resource Mapping、Partition Policy、Loki Scope Policy 和迁移账本表；先保持旧读取路径。
3. 注册细粒度 RBAC 权限，部署 reconcile 与只读报告；对当前代码工具生成 Installation 差异，不自动发布。
4. 管理员逐个执行机器验证并发布 Tool Release；建立 Resource/Partition/Loki Policy Draft、验证与 Published Revision。
5. 生成迁移预检：列出每个 Agent/Application/非终态或可恢复 Job 的旧名称绑定、候选精确 Release、资源与策略；存在零候选或多候选时停止切换。
6. 发布新的 Agent Publication 和 Application Publication，验证全部目标矩阵唯一；开启新 Job 精确写入并拒绝新 `legacy-v1` 写入。
7. 在维护窗口排空 Worker，对旧 Job 执行幂等物化；无法确定的 Job 隔离且不得恢复。重启后验证重试仍读取原 Snapshot。
8. 进行数据库、Redis、全局 Loki 和环境 Loki 的真实读链验收，覆盖有/无基地、有/无车间、有/无 placement、零结果和越界拒绝；同时验证 Delivery。
9. 连续迁移报告满足零活动 legacy 引用后，禁用旧 Publication 激活/回滚，删除兼容读取和写入代码；保留历史字段和审计查询。
10. 运行严格 schema/spec/单元/集成/Compose 校验，保存 Publication、Job、Tool Call、资源解析、审计和回执证据。

回滚按阶段进行：Removal 前回滚应用代码时必须保持新表和精确 Snapshot 可读，禁止恢复旧写入；Removal 后只能恢复匹配的代码与数据库备份。任何回滚都不得让既有精确 Job 浮动到新的 Release 或 Resource Revision。

## Open Questions

当前没有阻止进入实现的问题。Customer/Organization 上层、Loki 车间隔离、cloud/edge 用户权限、DB 多前缀、审批流及通用动态工具均明确延期，后续必须通过独立 OpenSpec change 讨论。
