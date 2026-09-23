## ADDED Requirements

### Requirement: 当前运行态只支持Python Runtime
当前源码、API、Agent bootstrap、Worker、Compose 与数据库约束 MUST 只支持新建、发布与执行 `python-v1` Agent。`agent_definition`、`agent_publication`、`agent_job` 与 `agent_runtime_invocation_claim` 的 runtime kind MUST 由数据库约束限定为 `python-v1`；任何非 `python-v1` 的 Agent、Publication、Application 激活、Job 执行或 Runtime 调用请求 MUST 失败关闭且不静默改写为 Python。系统不得保留其它 Runtime 实现的服务、配置或兼容分支，也不得声称当前存在源码中没有的退役预检 CLI、自动排空或跨 Runtime 迁移命令。

#### Scenario: 创建或发布非Python Agent
- **WHEN** 当前 API 收到非 `python-v1` 的 Agent 创建、草稿、发布、回滚或新应用激活请求
- **THEN** 系统失败关闭且不静默改写为 Python

#### Scenario: 执行非Python Job
- **WHEN** Worker 或 Runtime 收到非 `python-v1` 的新执行请求
- **THEN** 系统拒绝执行且不跨 Runtime fallback

#### Scenario: 升级时存在非Python调用占用
- **WHEN** 迁移前 `agent_runtime_invocation_claim` 存在非 `python-v1` 占用
- **THEN** 迁移删除这些无主占用并把约束收紧为只允许 `python-v1`
- **AND** 不改写或删除 Definition、Publication、Job 与审计事实

#### Scenario: 运维查找退役命令
- **WHEN** 操作者检查当前源码运维入口
- **THEN** 文档不得指示调用不存在的 Runtime 退役预检或迁移 CLI

## REMOVED Requirements

### Requirement: 当前运行态只支持Python并保留历史TypeScript事实
**Reason**: 迁移 119 已通过失败关闭守卫禁止数据库出现非 `python-v1` 的 Definition/Publication/Job，“保留历史 TypeScript 事实”不再对应任何可能存在的数据；调用占用表的遗留约束由迁移 145 收紧。
**Migration**: 由 ADDED 的“当前运行态只支持Python Runtime”替代；非 `python-v1` 请求失败关闭、不跨 Runtime fallback、不声称存在退役 CLI 的约束保持不变。
