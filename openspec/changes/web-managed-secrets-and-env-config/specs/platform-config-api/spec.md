## ADDED Requirements

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
