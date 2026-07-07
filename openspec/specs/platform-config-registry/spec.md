# platform-config-registry Specification

## Purpose
Defines PostgreSQL-backed platform configuration registry behavior for topology, resource bindings, secret references, access grants, and configuration audit.
## Requirements
### Requirement: Platform topology is persisted in PostgreSQL
系统 SHALL 在 PostgreSQL 中持久化平台 topology，包括 Environment、Base、Workshop 的层级关系、启停状态、别名和扩展元数据。

#### Scenario: Create environment base and workshop
- **WHEN** 管理端创建一个环境、该环境下的基地和该基地下的车间
- **THEN** 系统持久化三层 topology 关系，并能按环境编码返回完整层级

#### Scenario: Disable workshop
- **WHEN** 管理端禁用一个车间配置
- **THEN** 后续 topology snapshot MUST 不包含该车间的启用资源绑定

### Requirement: Resource bindings are persisted by scope
系统 SHALL 在 PostgreSQL 中持久化 DB、Redis、Loki、ER context、business-flow context 等资源绑定，并 MUST 支持按环境、基地或车间作用域绑定资源。

#### Scenario: Bind database to base
- **WHEN** 管理端为一个基地配置数据库资源绑定
- **THEN** 系统保存资源类型、作用域、连接配置、密钥引用和启停状态

#### Scenario: Bind Loki to workshop
- **WHEN** 管理端为一个车间配置 Loki selector 或 label 约束
- **THEN** 系统保存车间级资源绑定，并在 topology snapshot 中只暴露该车间允许的 Loki 查询范围

### Requirement: Secret references never store secret payloads
系统 SHALL 只保存密钥引用元数据，并 MUST NOT 在 PostgreSQL 配置表中保存真实 token、password、api key、Redis 密码或数据库密码。

#### Scenario: Store env secret reference
- **WHEN** 管理端配置数据库密码来源为 `env:ORDER_DB_PASSWORD`
- **THEN** 系统只保存该引用字符串和用途，不保存环境变量解析后的真实值

#### Scenario: Reject raw secret in config json
- **WHEN** 管理端提交的资源配置 JSON 中包含疑似真实密钥字段和值
- **THEN** 系统拒绝保存配置并返回校验错误

### Requirement: Platform access grants are persisted
系统 SHALL 在 PostgreSQL 中持久化平台访问授权，授权对象 MUST 支持用户、用户组、角色和服务账号。

#### Scenario: Grant user access to workshop
- **WHEN** 管理端授权某用户访问指定环境、基地和车间的只读诊断工具
- **THEN** 系统保存授权主体、资源范围、工具范围、授权效果和优先级

#### Scenario: Deny overrides broad allow by priority
- **WHEN** 同一用户同时命中宽泛 allow 和更高优先级 deny
- **THEN** 系统 MUST 按优先级和 effect 计算最终访问结果

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
系统 SHALL 为平台配置 registry 暴露稳定 revision 或 hash，用于判断 runtime snapshot 是否来自预期配置版本。

#### Scenario: Configuration changes revision
- **WHEN** environment、base、workshop、resource binding、secret reference 或 access grant 发生新增、修改、启停
- **THEN** registry 生成的 topology revision 或 hash MUST 发生变化

#### Scenario: Runtime reports revision
- **WHEN** Internal API Platform 从 registry 加载 DB-backed snapshot
- **THEN** 运行时状态输出包含该 revision 或 hash，便于与配置 API snapshot 对比

### Requirement: Registry projects access grants into runtime access policy
系统 SHALL 将 PostgreSQL 中启用的 platform access grants 投影成 Internal API Platform 运行时访问策略。

#### Scenario: User grant allows target
- **WHEN** 用户拥有目标 environment/base/workshop 的启用 allow grant
- **THEN** DB-backed runtime access policy 允许该用户解析并调用该目标下的只读工具

#### Scenario: Disabled or deny grant blocks target
- **WHEN** grant 被禁用或更高优先级 deny grant 命中目标
- **THEN** DB-backed runtime access policy 拒绝该用户访问目标，并记录授权拒绝

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

