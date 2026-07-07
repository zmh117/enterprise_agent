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
