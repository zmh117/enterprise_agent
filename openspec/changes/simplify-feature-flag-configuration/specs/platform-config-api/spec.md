## ADDED Requirements

### Requirement: Platform API exposes effective feature diagnostics
系统 SHALL 向具有配置读取权限的管理员提供只读有效功能配置诊断，返回四个顶层开关、派生管理能力、受治理策略、来源、弃用状态和冲突信息。

#### Scenario: Authorized administrator reads diagnostics
- **WHEN** 具有配置读取权限的管理员请求有效功能配置
- **THEN** 系统返回每项配置的最终值、来源、分类、revision、弃用输入和阻断原因
- **AND** 响应不包含 Secret 明文、完整连接串或未经脱敏的环境变量值

#### Scenario: Unauthorized caller reads diagnostics
- **WHEN** 未认证或不具有配置读取权限的调用方请求详细诊断
- **THEN** 系统拒绝请求并记录审计事件

#### Scenario: Legacy conflict is present
- **WHEN** 启动前检查或草稿发布校验发现新旧配置冲突
- **THEN** API 返回稳定的冲突代码、冲突键和迁移目标

## MODIFIED Requirements

### Requirement: Platform API exposes env migration guidance
系统 SHALL 提供当前 env key 到 bootstrap-only、deployment safety gate、governed runtime policy、test-only 或 Secret management 的分类与迁移关系。

#### Scenario: List migratable env keys
- **WHEN** 管理端请求可迁移配置项列表
- **THEN** 系统返回 key、类型、安全默认值、是否敏感、分类、建议作用域、适用服务、迁移目标、弃用版本和是否需要重启

#### Scenario: Bootstrap-only key is edited
- **WHEN** 管理端尝试把 `DATABASE_DSN`、`RABBITMQ_URL` 或主加密密钥保存为普通 runtime config
- **THEN** 系统拒绝该配置并提示必须通过部署环境或受控 Secret 管理

#### Scenario: Deployment safety gate is enabled through API
- **WHEN** 管理端尝试通过数据库配置开启被部署环境关闭的已发布 Runtime、真实模型或真实内部工具
- **THEN** 系统拒绝越权开启或保存为被 deployment gate 阻断的请求状态
- **AND** 响应明确说明必须由部署环境开启

#### Scenario: Test-only key is edited in production
- **WHEN** 管理端在生产环境尝试启用测试身份请求头
- **THEN** 系统拒绝修改并记录安全审计事件
