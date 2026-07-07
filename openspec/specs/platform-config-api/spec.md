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

### Requirement: Imported topology can be verified as runtime-ready
系统 SHALL 让通过 YAML import 或平台配置 API 写入的 topology 能被验证为 Internal API Platform 可消费的 runtime snapshot。

#### Scenario: YAML import produces database snapshot
- **WHEN** 管理端导入合法 topology YAML 到 PostgreSQL
- **THEN** `/api/platform/topology-snapshot` 返回 source 为 database 或可被运行时加载的 DB-backed snapshot，并包含启用资源数量和访问授权摘要

#### Scenario: Imported topology has validation errors
- **WHEN** 导入后的启用资源绑定缺少运行时必须字段
- **THEN** snapshot API 返回配置错误详情，并且不得把该配置标记为 runtime valid

### Requirement: Platform configuration API supports runtime verification workflow
系统 SHALL 提供足够的只读 API 输出，让开发者或后续 Web 平台确认当前 DB 配置能驱动只读诊断工具。

#### Scenario: Verify effective topology
- **WHEN** 开发者查询平台 topology snapshot
- **THEN** 响应包含启用 environment/base/workshop、resource binding 作用域、resource kind、secret reference 摘要和配置 revision/hash

#### Scenario: Verify disabled resource exclusion
- **WHEN** 管理端禁用某个 resource binding 后查询 topology snapshot
- **THEN** snapshot 不包含该禁用资源，且 revision/hash 发生可观测变化

### Requirement: Platform configuration API documents restart or reload semantics
系统 SHALL 明确说明 DB-backed 配置对 Internal API Platform 的生效时机。

#### Scenario: Runtime uses startup snapshot
- **WHEN** Internal API Platform 采用启动时 snapshot 模型
- **THEN** 文档和验证流程明确要求修改配置后重启服务或执行未来的 reload 动作才能让运行时读取新配置

### Requirement: Platform API accepts secret values through write-only fields
系统 SHALL 提供平台密钥管理 API，允许管理端通过 write-only 字段提交 secret 明文值，并只返回 secret ref、状态和脱敏摘要。

#### Scenario: Create secret through API
- **WHEN** 管理端调用 secret 创建接口并提交明文 value
- **THEN** API 返回 secret metadata 和 `secret_ref`，响应中不包含明文 value

#### Scenario: Read secret through API
- **WHEN** 管理端查询 secret 详情
- **THEN** API 返回 configured/version/updated_at/masked_summary，不返回明文 value

### Requirement: Platform API manages DB-backed runtime config
系统 SHALL 提供 runtime config 的 CRUD、启停、snapshot 和校验 API，供后续 Web 配置页面使用。

#### Scenario: Save runtime setting
- **WHEN** 管理端提交合法 runtime setting key、类型、作用域和值
- **THEN** 系统保存配置、更新 revision，并写入配置审计

#### Scenario: Save secret-backed runtime setting
- **WHEN** 管理端把 `ANTHROPIC_API_KEY` 配置为 `secret://platform/deepseek_api_key`
- **THEN** 系统保存 secret ref，并在 snapshot 中仅返回该 ref 的脱敏状态

### Requirement: Platform API exposes env migration guidance
系统 SHALL 提供或文档化当前 env key 到 DB runtime config / secret management 的映射关系。

#### Scenario: List migratable env keys
- **WHEN** 管理端请求可迁移配置项列表
- **THEN** 系统返回 key、类型、默认值、是否敏感、建议作用域、适用服务和是否 bootstrap-only

#### Scenario: Bootstrap-only key is edited
- **WHEN** 管理端尝试把 `DATABASE_DSN` 或主加密密钥保存为普通 runtime config
- **THEN** 系统拒绝该配置并提示必须通过部署环境管理

