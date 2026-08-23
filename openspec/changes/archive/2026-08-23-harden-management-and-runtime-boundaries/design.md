## Context

当前 API 应用把平台配置、Workflow 和调试 Job Router 放在管理面条件分支之外；平台与 Workflow 写路径在管理开关关闭时可从客户端 Header 取得 actor。`admin-web` 在普通 Compose 中也始终启动并映射宿主端口。另一方面，Agent Job consumer 的 JSON 解码位于 handler 边界外，handler 任意异常均 `requeue=True`；运行中心 Job API 只在 SQL 中处理时间、用户名和应用名，最多取 500 条后再在 Python 过滤。

系统已经具备可复用的可信 Session principal、测试 Header 显式闸门、细粒度管理能力目录、数据库 Job retry/Outbox、Agent Job dead queue 名称、结构化 `ApiError` 和本地 File Storage Secret bootstrap。本设计复用这些边界，不增加第二套认证、业务重试或 Secret 分发模型。

## Goals / Non-Goals

**Goals:**

- `FEATURE_WEB_ADMIN=false` 时管理 Router、调试入口和管理 Web 均不可达。
- 管理 actor 只来自可信 Session principal；测试 Header 只在显式 test/local adapter 下生效。
- 平台配置和 Workflow 形成可测试的 read/edit/publish/manage 权限矩阵。
- 将 malformed envelope 与持续失败 delivery 有界隔离，同时保持数据库 Job retry/Outbox 为业务权威。
- Job 查询在数据库中完成范围、筛选、游标和 `limit + 1`，返回完整稳定页面。
- 前端明确区分认证、授权、服务故障和渲染故障。
- 非 local/test 部署拒绝缺失或默认 MinIO/S3 凭据。

**Non-Goals:**

- 不改变 DingTalk、Webhook、Runtime Control、Service Principal 等非管理数据面路由。
- 不为 RabbitMQ 建立第二套 Job retry count，不改变 `RETRY_WAIT`、Job Dispatch Outbox 或 Delivery Outbox 状态机。
- 不拆分 Job 神模块，不改变 Job API 响应字段或前端信息架构。
- 不改变 File Service 的 Principal JWT、平台 Secret 引用和对象存储 owner/tenant 边界。

## Decisions

### 1. 单一管理面装配条件

后端只使用 `feature_configuration.web_admin_enabled` 决定是否挂载全部管理 Router；派生的 unified identity/control-plane 状态不再单独让管理端点出现。公开/内部数据面 Router 保持常驻。管理关闭时不注册路由，因此返回 404 而不是在 handler 内返回 401。

Compose 为 `admin-web` 恢复 `admin` profile，并向容器传入 `FEATURE_WEB_ADMIN`；镜像入口在变量不为 `true` 时直接失败，防止显式点名服务绕过 profile。选择 profile 加启动守卫，而不是仅依靠后端 404，因为静态管理页面本身也属于管理面。

### 2. 可信 principal 和统一 action 矩阵

删除 `optional_legacy_actor` 生产兼容语义。平台配置 Router 的 actor 总由 `current_principal` 取得并执行 CSRF；服务层继续按 `platform_config/manage` 或 `secret/manage|rotate` 防御性授权。所有平台读取显式使用 `platform_config/read` 或 `secret/read`。

Workflow Router 和 Service 统一使用 `agent/read`、`agent/edit`、`agent/publish`；发布不再复用平台配置 manage。调试 Job 继续使用 `agent_job/debug_execute` 和现有 owner/application 运维读取边界，但仅在管理面开启时挂载。

测试身份 Header 不删除，而是只经现有 `FEATURE_TEST_IDENTITY_HEADERS=true` 且环境为 local/test/testing 的 `current_principal` adapter 解析；生产即使提交 Header 也得到 401。

### 3. Poison message 采用显式 quarantine 后确认

不为现有 `agent.job.queue` 增加 DLX 参数，避免对已经存在的 durable queue 进行不兼容重声明。Consumer 声明现有 `dead_queue`，并在同一 channel 将原始消息以持久化模式发布到 dead queue，附加有界失败分类后才 ack 原 delivery。

Envelope 解码/结构错误直接 quarantine。合法 envelope 的 handler 首次异常允许一次 broker requeue，用于覆盖短暂数据库/连接异常；若 `redelivered=true` 后仍失败则 quarantine。这个一次 broker redelivery 不更新 Job retry count；正常执行失败仍由 Worker 捕获并交给数据库 Job retry service。

相较“所有异常立即 dead”，该方案保留一次基础设施瞬时恢复机会；相较基于自定义 Header 反复 republish，它不引入新的 broker retry ledger。

### 4. Job 查询使用 SQL keyset 页面

新增单一 Job 查询参数对象，将时间窗、AdminScope、状态集合、用户、Agent、Channel、Project、Session、Correlation、execution/delivery/failure/model 和解码后的 `(created_at, id)` cursor 传入 read repository。Repository 在 SQL 中生成参数化条件，按 `created_at desc, id desc` 取 `limit + 1`。

受限 AdminScope 通过 owner 条件与 routing context 的 environment/base/workshop 条件下推；SQLite 使用 JSON 提取函数，PostgreSQL 由现有 Database 占位符/SQL 兼容层执行等价表达。模型过滤针对 execution summary 的 JSON 文档做存在性判断；若数据库方言不支持的表达无法保持一致，则在 repository 中提供方言专用片段，而不是回退到截断后的 Python 过滤。

### 5. 前端区分 Query failure 与 capability deny

`CapabilityGate` 仅在 capability 查询成功且缺少能力时显示 403 页面。401 交由既有 AuthenticationGate 恢复登录；网络、5xx 或 schema parse 错误显示“管理服务不可用”并提供重试。应用根节点增加 React Error Boundary，捕获渲染异常并提供安全刷新/返回入口，不显示堆栈或原始响应。

### 6. 非本地对象存储失败关闭

`load_settings` 在构造配置后统一验证对象存储凭据。local/test/testing/development 允许本地占位；其它环境要求显式非空且不得等于仓库默认 access/secret。Compose 仍可为 local profile 提供默认值，但 `admin-web` 之外的服务不新增 S3 明文环境变量，File Service 继续使用平台 Secret 引用。

## Risks / Trade-offs

- [大量旧测试依赖关闭管理面时的 Header 兼容调用] → 将这些测试改成显式启用管理面与 test Header adapter，另加生产 Header 拒绝契约。
- [Compose profile 增加启动命令要求] → 同步受支持的管理端运行文档，并用镜像入口守卫防止误启。
- [handler 异常可能发生在部分数据库提交之后] → 依赖既有 claim/Outbox 幂等，最多一次 broker redelivery；持续失败消息隔离并保留 Job 数据事实供恢复。
- [复杂 SQL 过滤可能出现 SQLite/PostgreSQL 差异] → 通过 repository 公共契约分别跑 SQLite 聚焦测试和 PostgreSQL integration；所有值参数化，集合大小受 API 限制。
- [前端 Error Boundary 不能捕获事件 handler 的异步错误] → Query/Mutation 错误继续由状态组件处理；Error Boundary 专注渲染生命周期故障。

## Migration Plan

1. 先发布后端管理面路由和 actor 收口；验证四层 HTTP 契约。
2. 使用 `FEATURE_WEB_ADMIN=true docker compose --profile admin ...` 启动管理 Web；关闭 flag 时容器入口必须拒绝启动。
3. 发布 consumer 前确认 dead queue 可声明；观察 poison quarantine 和主队列 drain，不删除或重建现有主队列。
4. 发布 Job SQL 查询和前端错误边界，比较相同过滤条件下的页面结果与游标。
5. 在 staging/production 提供显式对象存储凭据后再升级；配置失败可通过恢复非默认 Secret 回滚，不得用默认值绕过。

## Open Questions

无。当前实现按“一次 broker redelivery、随后 quarantine”作为基础设施异常上限；业务 Job retry 次数继续完全由数据库配置决定。
