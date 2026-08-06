## Why

当前只读工具仍以名称级开关和可变资源配置参与运行时，无法证明一个 Job 实际执行了哪一版代码、哪一版资源及哪一版数据隔离策略；`legacy-v1`、固定三层 topology 和 Loki 车间标签假设也与现网的多种部署形态不一致。现在需要先建立可发布、可冻结、可审计且失败关闭的治理模型，再扩展管理界面和迁移运行流量。

## What Changes

- 建立代码 Manifest 驱动的内置只读 Tool Catalog、安装对账、机器验证、不可变 Tool Release 和 `ACTIVE` / `DEPRECATED` / `DISABLED` / `ARCHIVED` 生命周期；管理端不得写入或执行动态 HTTP、MCP、SQL、脚本或模板实现。
- Agent Publication 冻结精确 Built-in Tool Release、Handler Version 和 Implementation Digest；Application Publication 只能显式选择其子集，并冻结完整资源映射，禁止 `latest`、名称级或默认版本解析。
- 引入应用级 Tool Resource Composition：同一逻辑资源槽可按业务目标范围和可选 `cloud` / `edge` placement 绑定一个或多个精确 Resource Revision，发布时拒绝缺失、重叠或歧义映射。
- 将业务目标改为实际存在的可变深度 `Environment[/Base[/Workshop]]`；placement 只描述物理资源位置，不进入用户数据权限，也不得通过伪造基地或占位值表达。
- 为车间引入不可变 Workshop Resource Partition Policy Revision：数据库第一阶段使用一个精确表名前缀；Redis 使用一个或多个精确完整 key namespace 前缀，并对 GET、SCAN 和 schema 目录强制执行。
- 为 Loki 引入 Resource Draft 测试后的有界标签 Key/Value 发现，以及不可变 Loki Scope Selector Policy Revision；每条策略使用 AND 连接的精确 `key=value`，表达一个环境和可选基地，作为运行时不可覆盖的强制 selector。
- **BREAKING** Loki 不再按 Workshop 或 placement 授权和路由；第一阶段支持一个全局 Loki 或每环境一个 Loki，`role`、`replica`、`app`、`logtype` 仅可作为受控诊断过滤条件。
- **BREAKING** 资源解析不再使用“第一个、默认、最新、模糊匹配”回退；同一有效目标命中零个或多个绑定时均失败关闭。
- **BREAKING** 分两阶段淘汰 `legacy-v1` 名称级工具绑定：先禁止新增旧写入并物化非终态/可重试 Job 的精确快照，达到零活动引用且通过真实运行链验收后再删除兼容读取和恢复入口；历史记录保留审计。
- 增加细粒度管理权限 `builtin_tools.read/reconcile/verify/publish/lifecycle`，资源治理权限继续独立；运行授权绑定稳定 Tool Identifier，安全边界扩大时必须使用新的 Identifier。

## Capabilities

### New Capabilities

- `built-in-readonly-tool-governance`: 代码 Manifest、安装对账、验证证据、不可变 Release、生命周期、RBAC 与 `legacy-v1` 迁移。
- `application-tool-resource-composition`: Agent/Application 精确工具子集、1..N 资源映射、发布校验及不可变 Job Execution Snapshot。
- `workshop-resource-partition-policy`: 数据库表前缀和 Redis key namespace 的版本化车间隔离策略与验证规则。
- `loki-scope-selector-policy`: Loki 标签发现、精确强制 selector、发布版本、健康状态和运行时合并规则。

### Modified Capabilities

- `internal-platform-topology`: 三层固定 topology 改为无虚节点的可变深度业务目标，并增加独立可选 placement 维度。
- `platform-config-registry`: 资源绑定改为精确不可变 revision 与策略 revision 的多映射快照，并区分 Draft、Published 和 Effective 状态。
- `readonly-tool-platform`: 工具目录和执行从名称级启用改为精确 Release 与完整治理交集，DB、Redis、Loki 继续执行只读和边界约束。
- `base-scoped-redis-loki`: Redis 保留基地共享与车间 namespace 隔离；Loki 改为全局/环境资源和环境 + 可选基地 selector 范围。
- `agent-job-lifecycle`: Job、重试和恢复固化精确工具、资源、partition policy、Loki scope policy 与 placement 事实。
- `platform-access-control`: 数据权限按实际存在的环境/基地/车间层级计算，明确不把 cloud/edge placement 作为授权维度。

## Impact

- 后端：Tool Registry、工具定义与发布模型、Agent/Application Publication、资源 Draft/Revision/Binding、Job Execution Scope、Internal API Platform 解析器、DB/Redis/Loki 网关、验证器、RBAC 与审计。
- 前端：“平台治理 → 只读工具”“平台治理 → 工具资源”、Agent 配置和业务应用发布页面；Loki 资源详情增加测试、级联标签发现、scope policy 验证与发布。
- 数据：新增 Built-in Tool Release、安装/验证证据、资源组合映射、Workshop Partition Policy、Loki Scope Selector Policy 及迁移账本；既有不可变发布和历史 Job 不做原地改写。
- 迁移：依赖 `stabilize-platform-runtime-foundation` 建立的 Resource Revision 与 Job 授权事实；若该变更尚未归档，本变更实施前必须先同步其最终规格和数据库迁移 head。
- 安全：Secret 仍只通过引用解析且不得回显；任何解析歧义、版本漂移、越界 key/table/selector 或缺失证据都在访问上游前失败关闭。
