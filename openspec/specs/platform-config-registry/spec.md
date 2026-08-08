# platform-config-registry Specification

## Purpose
Defines PostgreSQL-backed platform configuration registry behavior for topology, resource bindings, secret references, access grants, and configuration audit.
## Requirements
### Requirement: Platform topology is persisted in PostgreSQL
系统 SHALL 在 PostgreSQL 中持久化 Environment、可选 Base 和可选 Workshop 的真实层级关系、启停状态、别名和扩展元数据；平台 MUST NOT 要求每个 Environment 都有 Base 或每个 Base 都有 Workshop，也不得保存用于补层级的虚节点。

#### Scenario: Create environment base and workshop
- **WHEN** 管理端创建一个环境、该环境下的真实基地和该基地下的真实车间
- **THEN** 系统持久化三层 topology 关系，并能按环境编码返回完整层级

#### Scenario: Create environment leaf
- **WHEN** 管理端创建一个本身就是有效业务目标且没有基地的环境
- **THEN** 系统持久化 Environment leaf，不自动创建默认 Base 或 Workshop

#### Scenario: Create base leaf
- **WHEN** 管理端创建一个没有车间划分的基地
- **THEN** 系统把该 Base 作为有效叶子目标，不要求占位 Workshop

#### Scenario: Disable workshop
- **WHEN** 管理端禁用一个车间配置
- **THEN** 后续 topology snapshot MUST 不包含该车间的启用资源映射

### Requirement: Resource bindings are persisted by scope
系统 SHALL 通过 Application Publication 的不可变 Mapping 在 PostgreSQL 中持久化 DB、Redis、Loki 等逻辑资源槽绑定；一个 slot MUST 支持 1..N 条 `业务目标范围 + 可选 placement → 精确 Resource Revision + 适用策略 Revision` 映射，并 MUST 在发布时拒绝缺失、重叠或歧义组合。

#### Scenario: Bind database to base
- **WHEN** 管理端为一个 Base 的数据库 slot 选择 Published Resource Revision
- **THEN** 系统在新 Application Publication 中保存精确 revision，并允许其 Workshop 后代通过各自 Published Partition Policy 继承

#### Scenario: Bind cloud and edge resources
- **WHEN** 同一逻辑目标的一个 slot 配置 cloud 和 edge 两个 Published Resource Revision
- **THEN** 系统保存两条 placement 不同的不可变 Mapping

#### Scenario: Bind global Loki to environment policy
- **WHEN** 应用使用 global Loki 查询一个 Environment
- **THEN** 系统保存精确 Loki Resource Revision 和该 Environment 的 Published Loki Scope Policy Revision

#### Scenario: Binding resolves ambiguously
- **WHEN** 环境级和基地级 Mapping 在同一 slot、placement 下同时覆盖一个有效叶子目标
- **THEN** Application Publish 拒绝且不保存部分 Publication

### Requirement: Secret references never store secret payloads
系统 SHALL 在新建资源、Revision 和 binding 中只保存 `secret://platform/<code>`，MUST NOT 在 PostgreSQL 普通配置表中保存真实 token、password、API key、Redis 密码或数据库密码。旧 `env:` 只可作为显式导入输入。

#### Scenario: Store platform secret reference
- **WHEN** 管理端为数据库 Draft 选择凭据中心 Secret
- **THEN** 系统只保存 `password_ref=secret://platform/<code>` 和用途

#### Scenario: Reject raw secret in config json
- **WHEN** 管理端提交的资源配置 JSON 中包含疑似真实密钥字段和值
- **THEN** 系统拒绝保存并返回校验错误

#### Scenario: Reject new env provider binding
- **WHEN** 新建或发布的资源包含 `env:`、`vault:` 或 `kms:` 引用
- **THEN** registry 必须拒绝；旧 env 数据只能进入显式导入流程

### Requirement: Platform configuration changes are audited
系统 SHALL 为平台配置新增、修改、启停、导入和发布动作写入配置审计记录。

#### Scenario: Update resource binding
- **WHEN** 管理端修改一个资源绑定
- **THEN** 系统记录实体类型、实体 ID、动作、操作者、修改前摘要、修改后摘要和时间

#### Scenario: Import yaml topology
- **WHEN** 系统从 YAML import/upsert topology 到 PostgreSQL
- **THEN** 系统为被创建或更新的配置实体写入审计记录

### Requirement: Runtime and configuration data share one database with logical isolation
系统 SHALL 在第一版使用同一个 PostgreSQL database 保存 Web 配置、Agent job、聊天记录、工具调用和审计数据，并 MUST 通过表前缀、模块 repository 和迁移边界进行逻辑隔离。

#### Scenario: Query platform configuration without reading chat tables
- **WHEN** Web 配置 API 查询 platform topology
- **THEN** 系统只通过 `platform_config` repository 读取 `platform_*` 配置表，不直接访问 `agent_message` 或 Agent job 运行表

#### Scenario: Future runtime split remains possible
- **WHEN** 后续需要把聊天和审计运行数据迁移到独立库
- **THEN** 系统可以通过 repository 配置切换运行数据存储，而不改变 platform configuration 的领域 API

### Requirement: Registry exposes stable runtime revision
系统 SHALL 为 topology、Resource Revision、Application Resource Mapping、Workshop Partition Policy 和 Loki Scope Policy 暴露规范化 revision 或 hash，用于证明 runtime snapshot 与 Application Publication 及 Job Snapshot 一致。

#### Scenario: Configuration changes revision
- **WHEN** Environment/Base/Workshop、资源映射或任一策略发布新的不可变 revision
- **THEN** 对应 Draft 或新 Publication 的 revision/hash 发生变化，既有 Publication hash 保持不变

#### Scenario: Runtime reports revision
- **WHEN** Internal API Platform 从 Job Snapshot 解析一次工具调用
- **THEN** 运行状态和审计包含 Publication、Resource 与 Policy 的 ID/revision/hash 摘要

#### Scenario: Resource draft changes only
- **WHEN** 管理员修改尚未发布的 Resource 或 Policy Draft
- **THEN** 既有 Published 和 Effective revision/hash 不发生变化

### Requirement: Registry keeps secret references unresolved outside infrastructure
系统 SHALL 在 registry、public snapshot、配置审计和运行时状态中只保留 secret reference，不得保存或返回解析后的真实密钥值。

#### Scenario: Secret reference is loaded for runtime
- **WHEN** DB-backed resource binding 使用 secret reference 配置数据库、Redis 或 Loki credential
- **THEN** registry snapshot 只包含引用，真实值仅能在 infrastructure gateway 建立外部连接时解析

#### Scenario: Public snapshot is exported
- **WHEN** 管理端或调试工具导出 topology snapshot
- **THEN** 响应不得包含任何真实 password、token、api key 或解析后的 secret payload

### Requirement: Registry stores encrypted secret metadata and versions
系统 SHALL 在平台配置 registry 中保存 secret metadata、active version、provider、状态和审计信息，并将密文版本与普通配置表隔离。

#### Scenario: Persist encrypted secret version
- **WHEN** 管理端创建 Web-managed secret
- **THEN** registry 保存 secret metadata 和密文版本，普通 resource binding 只保存 secret ref

#### Scenario: Secret metadata is listed
- **WHEN** 系统列出 platform secret references
- **THEN** registry 返回 provider、ref、active version 和 configured 状态，不返回密文或明文

### Requirement: Registry stores runtime config definitions and values
系统 SHALL 保存 runtime config key 的定义、类型、默认值、敏感性、适用服务和作用域规则，并保存每个作用域下的配置值。

#### Scenario: Register runtime config key
- **WHEN** 系统启动或迁移时注册 `ANTHROPIC_MODEL`
- **THEN** registry 保存该 key 的类型、默认值、说明和适用服务

#### Scenario: Persist scoped runtime config value
- **WHEN** 管理端为 `agent-worker` 保存 `AGENT_MAX_TURNS=12`
- **THEN** registry 保存 service-scoped 配置值并生成新的 revision/hash

### Requirement: Registry prevents secret payloads in non-secret config
系统 SHALL 阻止疑似密码、token、api key 等明文值保存到普通 config_json、runtime value_json 或审计 after_json。

#### Scenario: Raw password submitted as runtime config
- **WHEN** 管理端把 `ANTHROPIC_API_KEY` 明文作为普通 value_json 提交
- **THEN** registry 拒绝保存并要求使用 secret management

#### Scenario: Raw password submitted in resource binding config
- **WHEN** 管理端把 database password 放入 resource binding config
- **THEN** registry 拒绝保存并要求使用 secret_refs

### Requirement: Provider 字段契约必须与运行时实现一致
Registry MUST 以单一 schema 定义管理 API、前端表单、验证器和运行时适配器字段；数据库第一阶段只允许 MySQL、SQL Server、Oracle，Redis 和 Loki 使用各自统一字段。

#### Scenario: 数据库字段名称不一致
- **WHEN** 请求同时使用旧 `user` 和新 `username` 或其他歧义字段
- **THEN** 系统必须按导入规则显式转换或拒绝，不得让管理端保存后运行时无法读取

#### Scenario: Provider 没有运行时 Handler
- **WHEN** Provider 被元数据声明但当前代码没有对应运行时实现
- **THEN** Registry 必须将其标记 unavailable 并阻止发布

### Requirement: Registry must separate resource, policy and publication lifecycle state
Registry MUST 分别持久化 Resource/Policy Draft、Verification Evidence、不可变 Published Revision、Application Publication Binding 和 Runtime Effective 状态；任何一个状态不得被另一个状态覆盖或合并成单一 `enabled` 字段。

#### Scenario: Published resource is not effective
- **WHEN** Resource Revision 已发布但运行时装载失败
- **THEN** Registry 查询同时返回 Published Revision 与不同的 Effective/health 状态，不误报为已生效

#### Scenario: Policy draft changes after verification
- **WHEN** Workshop 或 Loki Policy Draft 的规范化内容变化
- **THEN** 旧 Verification Evidence 失效，但上一 Published Revision 和依赖 Job 保持不变

### Requirement: Resource Identity 与 Resource Revision 生命周期必须独立管理
系统 SHALL 分别管理稳定 Resource Identity 的 `enabled`、`disabled`、`archived` 状态和不可变 Resource Revision 的 `PUBLISHED`、`DISABLED`、`ARCHIVED` 状态；Revision 生命周期动作 MUST NOT 隐式改写 Identity，管理 API 和界面 MUST 分开展示并筛选两层状态。

#### Scenario: 归档最新 Resource Revision
- **WHEN** 管理员把一个 Loki Resource 的最新 Revision 从 DISABLED 归档
- **THEN** 该 Revision 变为 ARCHIVED，Resource Identity 保持 enabled，并仍可显式从该历史 Revision 复制新 Draft

#### Scenario: 停用 Resource Identity
- **WHEN** 管理员使用当前 Identity revision 显式停用一个 enabled Resource Identity
- **THEN** Identity 变为 disabled，后续创建、保存、验证和发布 Draft 均被阻止，但既有 Resource Revision、Application Publication 和 Job Snapshot 不被改写

#### Scenario: 恢复 Resource Identity
- **WHEN** 管理员使用当前 Identity revision 显式恢复一个 disabled Resource Identity
- **THEN** Identity 变为 enabled 并允许后续 Draft 管理，历史 Revision 状态保持不变

#### Scenario: 安全归档 Resource Identity
- **WHEN** disabled Identity 没有活动 Draft、没有 PUBLISHED Revision 且没有活动 Application Publication 引用
- **THEN** 管理员可以用当前 Identity revision 把它归档为不可恢复终态并记录审计

#### Scenario: Identity 仍有治理依赖
- **WHEN** 管理员尝试归档仍有活动 Draft、PUBLISHED Revision 或活动 Application Publication 引用的 Identity
- **THEN** 系统失败关闭并返回不含 Secret 的依赖摘要，不改变 Identity 或任何 Revision

#### Scenario: Identity 并发状态已变化
- **WHEN** 生命周期请求携带的 expected Identity revision 已过期
- **THEN** 系统以并发冲突拒绝请求，要求刷新后重试

### Requirement: Registry must enforce optional placement representation
Registry SHALL 只在资源实际存在物理位置差异时保存 `cloud` 或 `edge` placement；无 placement 的 Mapping MUST 保存为缺省值而非字符串占位，并且同一 Mapping 不得同时包含多个 placement。

#### Scenario: Save non-placement resource
- **WHEN** 管理端保存一个没有云边差异的 Redis Mapping
- **THEN** Registry 持久化缺省 placement 并拒绝 `none`、`standalone` 或 `default`

#### Scenario: Save one placement value
- **WHEN** 管理端保存 edge Resource Mapping
- **THEN** Registry 只保存枚举值 `edge`，不把它写入 Environment/Base/Workshop code

