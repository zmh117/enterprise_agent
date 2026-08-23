## MODIFIED Requirements

### Requirement: TypeScript Runtime退役必须经过显式运行态门禁
当前源码、API、Agent bootstrap、Worker 和 Compose MUST 只支持新建、发布与执行 `python-v1` Agent，并 MUST 拒绝新的 `typescript-v1` Agent、Publication、Application 激活或 Job 执行。数据库中退役前形成的 TypeScript Definition、Publication、终态 Job 和审计事实 MAY 保留并 MUST 只读展示原始 runtime kind；系统不得声称当前存在源码中没有的退役预检 CLI、自动排空或跨 Runtime 迁移命令。

#### Scenario: 创建或发布TypeScript Agent
- **WHEN** 当前 API 收到 `typescript-v1` Agent 创建、草稿、发布、回滚或新应用激活请求
- **THEN** 系统失败关闭且不静默改写为 Python

#### Scenario: 执行TypeScript Job
- **WHEN** Worker 或 Runtime 收到非 `python-v1` 的新执行请求
- **THEN** 系统拒绝执行且不跨 Runtime fallback

#### Scenario: 只剩历史TypeScript事实
- **WHEN** 管理查询读取退役前的 TypeScript Definition、Publication、终态 Job 或审计
- **THEN** 系统保留原始 `typescript-v1` 和只读状态
- **AND** 不允许这些事实恢复为当前可执行配置

#### Scenario: 运维查找退役命令
- **WHEN** 操作者检查当前源码运维入口
- **THEN** 文档不得指示调用不存在的 TypeScript 退役预检或迁移 CLI

### Requirement: Compose 管理 Web 必须随管理面失败关闭
当前普通 Compose 配置 SHALL 包含 `admin-web` 服务定义。`admin-web` 容器入口 MUST 要求 `FEATURE_WEB_ADMIN=true`；该值不为 `true` 时容器必须以非零状态退出且不得提供静态管理页面。启用时，管理 Web MUST 只代理已挂载且受现有 Session 与 RBAC 保护的管理 API；规范不得声称当前 Compose 使用已注释掉的 admin profile。

#### Scenario: 默认Compose配置
- **WHEN** Compose 使用默认 `FEATURE_WEB_ADMIN=false` 渲染并启动服务集合
- **THEN** `admin-web` 服务仍存在于 Compose manifest
- **AND** 其入口 guard 非零退出且不提供管理页面

#### Scenario: 直接点名关闭的Admin Web
- **WHEN** 操作者显式启动 `admin-web` 但 `FEATURE_WEB_ADMIN` 不为 `true`
- **THEN** 容器以非零状态退出且不提供静态管理页面

#### Scenario: 显式启用管理Web
- **WHEN** `FEATURE_WEB_ADMIN=true` 且依赖服务满足启动条件
- **THEN** `admin-web` 启动并只代理已挂载且受认证授权保护的管理 API

## RENAMED Requirements

- FROM: `TypeScript Runtime退役必须经过显式运行态门禁`
- TO: `当前运行态只支持Python并保留历史TypeScript事实`
