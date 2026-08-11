# platform-schema-migration-runtime Specification

## Purpose
TBD - created by archiving change stabilize-platform-runtime-foundation. Update Purpose after archive.
## Requirements
### Requirement: 只有一次性 Migrator 可以修改平台 schema
系统 MUST 由独立 one-shot Migrator 应用 schema migration；API、Worker、Dispatcher 和 Internal API Platform MUST NOT 在自身启动或请求处理中执行 migration。

#### Scenario: Compose 启动平台
- **WHEN** Docker Compose 启动新版本平台
- **THEN** Migrator 必须先成功退出，业务服务随后才可启动

#### Scenario: 业务服务直接启动
- **WHEN** 任一业务服务启动且数据库 schema 未达到代码要求的 head
- **THEN** 服务必须启动失败并返回不含敏感信息的版本差异

### Requirement: Migration 必须具有唯一版本、稳定 checksum 和全局互斥
Migrator MUST 拒绝重复版本，并在执行前校验已应用 migration 的 checksum；同一 PostgreSQL 数据库同时最多只能有一个持有 advisory lock 的 Migrator。

#### Scenario: 两个 Migrator 并发启动
- **WHEN** 两个实例同时尝试迁移同一数据库
- **THEN** 只有一个实例获得全局锁并执行，另一个等待或安全退出

#### Scenario: 已应用 migration 内容被修改
- **WHEN** 账本中的 checksum 与磁盘 migration checksum 不一致
- **THEN** Migrator 必须停止且不得应用任何后续版本

### Requirement: 每个 migration 必须在完整事务中执行
系统 MUST 将单个 migration 的全部语句及其账本记录置于同一数据库事务中；任一步失败时该版本不得部分生效。

#### Scenario: Migration 中间语句失败
- **WHEN** 某个 migration 的任一语句执行失败
- **THEN** 该版本的 schema 变更和账本写入必须全部回滚

### Requirement: 数据库访问必须使用操作级 Unit of Work
系统 SHALL 使用同步连接池，并为每个请求、消息处理或 CLI 操作创建独立 Unit of Work；MUST NOT 共享全局连接或全局事务深度。

#### Scenario: 两个请求并发修改数据
- **WHEN** 两个 API 请求同时执行各自业务操作
- **THEN** 两个请求必须使用独立连接和事务，任一回滚不得影响另一请求

#### Scenario: 业务操作需要外部调用
- **WHEN** 操作需要调用模型、HTTP、RabbitMQ 或 DingTalk
- **THEN** 本地数据库事务必须在外部调用前完成，外部副作用通过 Outbox 或独立步骤驱动
