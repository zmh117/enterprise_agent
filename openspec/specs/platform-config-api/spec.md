# platform-config-api Specification

## Purpose
Defines backend APIs for the future web configuration console, including topology management, YAML import, snapshot export, validation, and secret-safe responses.

## Requirements

### Requirement: Platform configuration API exposes topology management
系统 SHALL 提供 Web 配置平台使用的 REST API，用于管理环境、基地、车间、资源绑定、密钥引用和访问授权。

#### Scenario: List topology
- **WHEN** 管理端请求平台 topology 列表
- **THEN** 系统返回启用和禁用的环境、基地、车间以及必要的分页或过滤信息

#### Scenario: Create resource binding
- **WHEN** 管理端提交合法的资源绑定配置
- **THEN** 系统保存资源绑定、写入配置审计，并返回创建后的实体

### Requirement: Platform configuration API validates domain invariants
系统 SHALL 在保存配置前校验领域约束，包括编码唯一性、父子关系存在、资源类型合法、secret ref 合法、只读工具边界和配置 JSON schema。

#### Scenario: Duplicate environment code rejected
- **WHEN** 管理端创建已存在编码的环境
- **THEN** 系统拒绝请求并返回冲突错误

#### Scenario: Invalid workshop parent rejected
- **WHEN** 管理端创建车间但指定不存在的基地
- **THEN** 系统拒绝请求并返回校验错误

#### Scenario: Mutation tool binding rejected
- **WHEN** 管理端试图为 MVP 诊断流程启用写库、删 Redis 或重启服务类工具
- **THEN** 系统拒绝保存配置，因为第一版只允许只读诊断工具

### Requirement: YAML topology import upserts database configuration
系统 SHALL 提供 YAML import/upsert 能力，把当前 topology YAML 转换为 PostgreSQL 配置记录。

#### Scenario: Import new yaml topology
- **WHEN** 系统导入包含新环境、基地、车间和资源绑定的 YAML
- **THEN** 系统创建对应配置记录，并返回 created、updated、skipped 的统计结果

#### Scenario: Import existing yaml topology
- **WHEN** 系统再次导入相同编码的 YAML topology
- **THEN** 系统按稳定编码 upsert 记录，不创建重复环境、基地或车间

### Requirement: API exposes runtime topology snapshot
系统 SHALL 提供只读 topology snapshot API，供 Internal API Platform 和调试工具查看当前生效配置。

#### Scenario: Snapshot from database
- **WHEN** PostgreSQL 中存在启用的 platform topology
- **THEN** snapshot API 返回 DB-backed topology，并标记来源为 database

#### Scenario: Snapshot validation error
- **WHEN** 启用的资源绑定缺少必要 secret ref 或 endpoint 配置
- **THEN** snapshot API 返回配置错误详情，不静默生成不完整快照

### Requirement: API responses do not leak secret values
系统 SHALL 确保所有平台配置 API 响应只返回 secret reference 元数据，MUST NOT 返回任何解析后的真实密钥值。

#### Scenario: Get resource binding with credential
- **WHEN** 管理端查询带数据库密码引用的资源绑定
- **THEN** 系统只返回 `secret_ref` 编码或引用，不返回真实密码

#### Scenario: Export topology snapshot
- **WHEN** 系统导出 topology snapshot
- **THEN** snapshot 中的 credential 字段仍然是 secret reference，不包含明文 token 或 password
