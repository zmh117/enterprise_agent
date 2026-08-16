## ADDED Requirements

### Requirement: Compose 管理 Web 必须随管理面失败关闭
普通 Compose 启动 SHALL 在默认状态不启动或映射 `admin-web`。管理 Web MUST 同时要求显式 admin profile 和 `FEATURE_WEB_ADMIN=true`；即使操作者直接点名容器，关闭的 feature flag 也必须使入口拒绝启动。

#### Scenario: 默认 Compose 启动
- **WHEN** 未启用 admin profile 且 `FEATURE_WEB_ADMIN=false`
- **THEN** `admin-web` 不启动且宿主机管理端口不监听

#### Scenario: 直接点名关闭的 Admin Web
- **WHEN** 操作者显式启动 `admin-web` 但 `FEATURE_WEB_ADMIN` 不为 `true`
- **THEN** 容器以非零状态退出且不提供静态管理页面

#### Scenario: 显式启用管理 Web
- **WHEN** admin profile 与 `FEATURE_WEB_ADMIN=true` 同时启用
- **THEN** `admin-web` 启动并只代理已挂载且受认证授权保护的管理 API

### Requirement: 管理前端必须区分权限错误与系统错误
管理前端 SHALL 使用全局渲染错误边界，并在 capability 查询中区分 401、403、网络/5xx 和客户端解析错误。系统错误 MUST 提供安全重试或刷新入口，不得显示为“无权访问”，也不得展示堆栈、原始响应或敏感配置。

#### Scenario: Capability API 返回 403
- **WHEN** 已登录用户的 capability 查询成功但目标 capability 缺失或 API 明确返回 403
- **THEN** 页面显示无权限状态且不退出有效登录

#### Scenario: Capability API 不可用
- **WHEN** capability 查询发生网络、5xx 或响应解析错误
- **THEN** 页面显示管理服务不可用和重试入口，不显示无权限文案

#### Scenario: 页面渲染抛出异常
- **WHEN** 任一管理路由组件在渲染生命周期抛出异常
- **THEN** 全局错误边界显示安全恢复页面且不暴露错误详情

### Requirement: 非本地对象存储凭据必须失败关闭
非 local/test/testing/development 环境 MUST 显式提供对象存储访问凭据，且 access key 与 secret key 均不得为空或等于仓库内置本地默认值。配置校验 MUST 在依赖对象存储的服务执行外部 I/O 前失败，不得静默使用 Compose 或代码 fallback。

#### Scenario: 生产环境缺少对象存储凭据
- **WHEN** `APP_ENV=production` 且对象存储 access key 或 secret key 缺失
- **THEN** 设置加载或服务启动以安全配置错误失败

#### Scenario: 生产环境使用仓库默认凭据
- **WHEN** 非本地环境仍使用内置 MinIO access key 或 secret 占位值
- **THEN** 设置加载或服务启动失败且错误信息不包含凭据内容

#### Scenario: 本地开发显式使用本地 MinIO
- **WHEN** local/test 环境使用 Compose 本地 MinIO bootstrap
- **THEN** 系统允许本地占位流程，但凭据仍只进入 MinIO/bootstrap Secret 边界
