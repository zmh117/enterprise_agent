## Context

平台当前已经形成 `api-server → PostgreSQL/RabbitMQ → agent-worker → Internal API Platform → Delivery` 的运行链路，并具备业务应用发布、统一身份与 RBAC、Webhook/DingTalk 入口、只读 DB/Redis/Loki 工具以及 Web 管理雏形。但这些能力来自多个增量变更，运行时基础仍有以下结构性问题：

- Debug Job API 可由请求体指定用户；内部工具服务信任可伪造的身份 Header，服务 Token 不是强制信任根。
- 多个服务可在启动时运行 migration，迁移无稳定 checksum、全局互斥和逐版本完整事务；数据库基础设施复用全局连接与嵌套深度。
- Job 持久化与 RabbitMQ 发布、Job 成功与外部 Delivery 之间存在双写窗口。
- 管理端资源字段与运行时字段不一致，资源版本、Secret 引用、Provider 能力和实际生效状态缺少统一契约。
- 授权仍可运行在 `compatibility`，旧权限表与新应用角色模型并存。
- 会话可按整个应用或用户复用，且未绑定发布版本和 Execution Scope。

本变更是后续 API 工具能力管理界面的前置基础。目标部署为本地/单机 Docker Compose，可安全运行多个 API、Worker 或 Dispatcher 副本；本次不承诺 Kubernetes、跨主机 TLS 或公网生产安全。

## Goals / Non-Goals

**Goals:**

- 建立不可伪造的用户、服务和 Job 三层运行时授权边界。
- 让 schema migration、业务事务、Job dispatch 和 Delivery 在多副本环境下具备确定性。
- 使 PostgreSQL 中已发布的资源版本成为 DB、Redis、Loki 运行时唯一事实源。
- 建立可在 Web 中管理但不回显明文的 Secret 与工具资源流程。
- 对齐 MySQL、SQL Server 和 Oracle 11g 的连接契约与只读验证。
- 建立代码注册 Handler、资源槽、应用发布绑定、固化 Execution Scope 和安全会话隔离。
- 通过真实本地 Grafana、Agent、只读工具和 DingTalk 链路证明实现，而不只验证健康端点。

**Non-Goals:**

- 不执行或继续 `reset-identity-and-authorization-bootstrap`，不删除现有身份和新 RBAC 数据。
- 不建设 Capability Catalog/Handler 管理界面，不支持动态 Python、脚本、SQL Handler 或任意 URL Handler。
- 不实现生产 HTTPS、mTLS、Kubernetes、Network Zone、Egress Policy、HMAC、timestamp 或 nonce 防重放。
- 不实现 Vault/KMS Provider、在线 Master Key keyring、定期轮换或到期策略。
- 不重构 Debug Trace 保留期和历史数据模型。
- 不实现 Worker 执行租约、fencing token、运行中崩溃自动恢复、`CANCEL_REQUESTED` 或 `CANCELLED`。
- 不在本地启动 Oracle 容器，也不把缺少真实 Oracle 11.2.0.4 连接测试描述为已验证。

## Decisions

### 1. 信任链由登录身份、服务 Token 和服务端 Job 事实共同构成

浏览器与 Debug API 使用现有登录会话解析当前用户，并检查 `agent.debug.execute`。请求体不得覆盖用户身份，也不得直接指定 Agent、资源、Connector 或任意 reply route；允许值只能来自当前用户有权使用的已发布业务应用和 Execution Scope。

Agent Worker 调用 Internal API Platform 时必须读取仓库外的 `INTERNAL_API_AUTH_TOKEN_FILE`，Internal API Platform 在非测试模式缺少 Token 时启动失败。轮换允许 current/next Token 短暂重叠，比较采用常量时间；Token 不进入日志、审计或工具摘要。

`X-Agent-Job-Id` 只是定位键，不是授权事实。Internal API Platform 必须从 PostgreSQL重新读取 Job，确认 Job 处于允许工具调用的执行状态，并从 Job 固化快照验证用户、业务应用发布、Handler、资源版本、Execution Scope 和工具调用范围。调用方提交的用户、项目或范围 Header 仅作一致性校验，不能扩大权限。

替代方案是仅校验 Bearer Token，或引入 mTLS。前者仍允许任一受信服务伪造 Job 上下文；后者超出本地 Compose 阶段，因此本次采用 Token 加 Job 事实。

### 2. 全局严格应用角色授权，不保留 compatibility

系统仅运行 `strict_application_role`。部署前备份旧权限数据，切换时删除 compatibility 配置、代码分支和 fallback，并清理 `permission_policy`、`platform_access_grant`；旧权限不自动转换为新角色授权。缺少新 RBAC 记录一律拒绝。

`platform-admin` 必须始终至少有两个已完成登录验证的启用人类成员。任何禁用、移除角色或删除用户操作若会使数量低于二，必须在同一事务内拒绝。系统账号不计入该不变量。

替代方案是旧数据继续 compatibility、新资源才 strict。该方案会永久保留两套授权解释，已被明确拒绝。

### 3. 独立一次性 Migrator 是唯一 schema writer

新增 one-shot Migrator 进程。它获取 PostgreSQL advisory lock，按唯一且严格排序的 migration version 执行；`schema_migration` 账本至少记录 version、checksum、applied_at、duration 和执行版本。每个 migration 在完整数据库事务内执行，checksum 变化、重复版本或失败事务均阻止后续启动。

API、Worker、Dispatcher 和 Internal API Platform 不再自动迁移，只在启动时只读校验 schema head。Compose 依赖 Migrator 成功退出，再启动业务服务。

替代方案是保留应用启动 migration 并增加进程锁。该方式仍混合部署职责与服务启动，难以安全回滚，因此不采用。

### 4. 数据库采用同步连接池和操作级 Unit of Work

保持现有同步技术栈，不做 ORM 或全异步重写。每个请求、消息处理或 CLI 操作获得独立连接和显式 Unit of Work；Repository 只能在当前 UoW 中访问数据库。事务完成后连接归还池，不共享全局 connection 或 transaction depth。

事务边界只包围本地持久化变更。模型调用、数据库工具查询、HTTP 调用、RabbitMQ 发布和 DingTalk 投递不得发生在业务数据库事务中。

### 5. Job dispatch 和 Delivery 使用两个事务 Outbox

创建 Job 时，在同一 UoW 中写入 Job 及 `job_dispatch_outbox`。独立 Dispatcher 使用 `FOR UPDATE SKIP LOCKED` 批量领取到期事件，发布只包含事件 ID、Job ID 和 correlation ID 的消息。发布确认后更新 Outbox；进程在发布后、确认前崩溃可能重复发布，因此消费者必须用持久化幂等键去重。

Agent 执行成功仅表示 Job 状态为 `SUCCEEDED`。同一事务内写入 assistant 结果和 `delivery_outbox`，由 Delivery Dispatcher 独立完成投递。Delivery 拥有自己的 `PENDING / RUNNING / RETRY_WAIT / SUCCEEDED / FAILED / DEAD / SKIPPED` 状态、attempt、chunk 和幂等键；投递失败不得重新执行 Agent。

Outbox 使用有限指数退避和最大次数，终态进入持久化 DEAD 并可映射到 RabbitMQ DLQ。运维只提供只读状态/指标及显式 CLI replay，replay 必须按 event、job 或 delivery 精确定位，不接受任意 payload，也不得无限重试。

替代方案是分布式事务或“数据库提交后直接 publish”。前者复杂度与基础设施不匹配；后者无法消除双写窗口。

### 6. 不把本次 Outbox 描述为 Worker 运行中崩溃恢复

Outbox 能恢复尚未发布或需要重试的 dispatch/delivery，但本次不增加 Worker 执行租约和 fencing。已经进入 `RUNNING` 后 Worker 崩溃仍是已知限制，不能由 Outbox 验收掩盖，也不能自动重新领取，以免旧 Worker 迟到提交造成并发结果。

### 7. 平台 Secret 使用固定外部 Master Key 和单一可创建 Provider

新增“平台治理 → 凭据中心”。明文只通过 Secret 写入/轮换命令进入应用内存，写入前使用由仓库外只读文件提供的固定 Master Key 加密；API 永不回显明文。Compose 不提供硬编码默认 Key，非测试环境缺失时启动失败。

新建和发布只允许 `secret://platform/<code>`。现有资源中的 `env:` 可通过显式导入操作读取一次，创建加密的平台 Secret，再改写资源引用；新界面不得创建或发布 `env:` 绑定。`vault:` 和 `kms:` 只显示为“尚未实现”，Resolver、验证和发布均拒绝。

固定 Master Key 不设有效期和定期轮换。只文档化紧急离线维护轮换：停机、备份、批量重加密、校验、替换 Key、再启动；不实现运行时多 Key。

### 8. 已发布 Resource Revision 是运行时唯一事实源

资源模型分为稳定 Resource Identity、可编辑 Draft、技术验证结果、不可变 Published Revision 和 Application Publication Binding。状态主线为 `DRAFT → VERIFIED → PUBLISHED`，无需审核审批。只有通过权限、字段、Secret、连接与只读能力检查的 VERIFIED draft 才能由单个授权发布者发布。

Draft 可删除；Published revision 不修改、不物理删除，只能 disable/archive。物理清理由特殊维护操作完成。业务应用发布绑定具体 Resource Revision，而不是浮动 Resource ID。

运行时轮询发布 revision，构建完整不可变快照并原子替换。进行中的请求继续使用旧快照，新请求使用新快照；装载失败保留 Last Known Good，并将相关资源/应用标为 degraded 或 blocked。单个资源失败不得使无关应用失效；没有 LKG 的必需绑定阻止相关应用创建新 Job。

YAML/env 只允许 bootstrap 或显式 import，不能在已存在 PostgreSQL 发布数据时成为回退源。

### 9. 资源维护重置是显式、可核验、需再次确认的操作

提供 `resource-reset report/prepare/apply/verify`：

1. `report` 只读列出精确资源、revision、绑定和受影响应用。
2. `prepare` 要求维护窗口，阻止新的资源依赖 Job，等待运行任务排空；超时则中止，不强杀。
3. `prepare` 生成数据库备份引用、operation ID、对象清单 digest 和预期影响。
4. `apply` 必须再次展示精确影响并获得用户确认；若 digest 或数据库状态变化则拒绝。删除 DB、Redis、Loki 当前资源、revision、binding 与有效快照，并将依赖应用标为 blocked。
5. `verify` 确认资源为空、保留对象完整、无悬空绑定且审计齐全。

Provider 定义、平台 Secret、身份、新 RBAC、业务应用、Job、Delivery、审计及历史快照不删除。

### 10. DB、Redis、Loki 契约按实际运行时统一

数据库第一阶段只发布 MySQL、SQL Server、Oracle：

- MySQL/SQL Server 使用 `host`、`port`、`database`、`username`、`password_ref` 及可选 schema 参数。
- Oracle 11.2.0.4 单实例使用 `host`、`port`，并在 `service_name` 与 `sid` 中二选一；不接受任意 TNS descriptor、RAC 或 SCAN。
- Oracle 强制 python-oracledb Thick 与 64-bit Instant Client 19c，禁止自动回退 Thin；使用兼容 11g 的 `ROWNUM` 限制方式。镜像中的客户端架构必须与容器架构一致。
- Redis 对齐 `host`、`port`、`database`、可选 `username`、`password_ref`、TLS 配置；Loki 对齐 `base_url`、`tenant_id`、认证 Secret 引用和查询上限。

每个数据库资源必须使用专用且可验证为只读的账号。发布前检查数据库权限；禁止权限、无法判定权限或连接失败均阻止发布。SQL 解析只允许单条 `SELECT` 或只读 `WITH`，拒绝 DML、DDL、PL/SQL、存储过程和多语句，并同时施加 session/statement timeout、最大行数与最大字节数。

真实 Oracle 连接测试为后续受保护验收；本次仅允许代码、镜像、静态契约和测试替身通过，不得发布未经真实连接验证的 Oracle revision。

### 11. Handler 由代码实现，数据库只治理发布

Handler Registry 从代码加载稳定 Handler ID、不可变版本、输入/输出 schema、风险级别、所需权限和逻辑资源槽。数据库保存 installed 状态、发布状态和治理元数据，但不保存或执行动态 Python、脚本、SQL 模板或任意 URL。

可执行 Handler 集合为：

`installed ∩ published ∩ resource-bound ∩ agent-allowed ∩ application-allowed ∩ role-allowed ∩ scope-allowed`

业务应用发布时把每个逻辑资源槽绑定到具体 Resource Revision。Job 创建时复制应用发布 ID、Handler 版本、绑定 revision 和环境/基地/车间形成不可变 Execution Scope；Agent 与 Handler 均不能在运行时改选任意资源。通用 `query_database` 进入业务 API 能力目录，但仍使用代码内置的只读 Handler，并继续受资源绑定、Agent、应用、角色和 Execution Scope 约束；本阶段不新增公共查询端点。

### 12. 会话按发布版本和 Execution Scope 隔离

新 Job 不允许 `application` 或 `actor` 连续会话模式：

- 群聊：应用发布 ID + Connector + 外部 conversation ID + Execution Scope hash。
- 私聊：上述字段再加入 requester ID。
- Webhook/Grafana：默认每个外部事件建立独立 session。
- Debug：默认每次新建隔离 session；显式继续时必须确认当前用户拥有访问权，且应用发布和 Execution Scope 完全未变。

发布版本或 Execution Scope 改变时必须新建 session。旧 `application`/`actor` session 保留为只读历史，不再附着新 Job。

### 13. Webhook 本地阶段统一强 Bearer Token

每个外部 Webhook binding 使用唯一高熵 Bearer Token 的 `secret://platform/` 引用；缺少或解析失败时 binding 为 MISCONFIGURED，不接收入站。身份、业务应用和 Execution Scope 从已发布 binding 推导，payload 不能覆盖。

Grafana 改用标准 `Authorization: Bearer`，删除 `X-Grafana-Token` 翻译和旧入口。幂等性使用来源稳定事件 ID 或受约束业务键。本次允许仅绑定本机/Compose 网络的 HTTP，不实现 HMAC 与 HTTPS，因此验收结论只能是本地功能完成。

### 14. 健康状态区分进程、平台依赖和业务资源

`/health` 只表示进程存活，不执行外部模型调用。`/ready` 校验 schema head、数据库、RabbitMQ、必需 Token/Master Key 和核心运行时装配；缺少核心依赖返回 503。

单个业务资源装载失败通过资源/应用 readiness 展示。存在 LKG 时服务保持可接流量但返回 `degraded`；不存在 LKG 的必需资源只阻止相关应用。所有状态输出必须脱敏。

### 15. 六阶段实施并设置不可跨越的 Gate

1. **严格授权与信任边界**：安全 Debug、Internal API Token/Job fact、strict RBAC、Webhook Bearer。
2. **Migrator、UoW 与 Outbox**：先消除迁移和事务隐患，再切换 Job/Delivery。
3. **Secret 与资源版本**：凭据中心后端、统一资源契约、发布快照和 LKG。
4. **资源重置、Oracle 与热加载**：在维护窗口显式清空旧资源，从空配置建立有效资源。
5. **管理界面**：凭据中心、工具资源、运行中心调试；不包含 Handler Catalog UI。
6. **完整验收**：CI、Compose、故障注入与真实本地端到端链路。

每阶段必须完成其自动化测试、数据核验和运行证据后才能进入下一阶段。

## Risks / Trade-offs

- [一次 change 规模较大] → 通过六阶段 Gate、独立提交和阶段验收控制，不允许跨阶段并行切换核心数据路径。
- [全局 strict 切换导致现有用户被拒绝] → 切换前生成授权清单并验证两个平台管理员；缺失权限通过新 RBAC 修复，不重新启用 compatibility。
- [Outbox 发布可能重复] → 使用事件唯一键、消费者持久化幂等和原子状态转换；不承诺 exactly-once。
- [Worker 在 RUNNING 中崩溃仍可能留下卡住任务] → 作为明确延期风险监控和人工处置，不自动重领；后续单独实现租约/fencing。
- [资源热加载失败] → 原子快照和 LKG；只阻止受影响应用，禁止失败配置覆盖有效快照。
- [固定 Master Key 丢失会导致 Secret 无法恢复] → Key 存放于仓库外受控文件并纳入安全备份；提供离线恢复演练，不在 Web 暴露。
- [删除旧资源和授权数据不可直接撤销] → 所有 apply 前备份、digest 校验和再次确认；变更后用整库备份恢复，而不是保留运行时 compatibility。
- [仅 Bearer + HTTP 不能满足公网安全] → 限定本机/Compose 测试，不声明生产就绪；公网 HTTPS 与更强请求认证进入后续变更。
- [Oracle 无真实环境] → 发布真实 Oracle revision 必须保持 blocked，直到后续在 11.2.0.4 上完成受保护连接验收。
- [不实现 Egress Policy] → 本次不开放任意 URL Handler，资源地址仅限授权管理员配置；不声明已解决生产 SSRF 风险。

## Migration Plan

1. 冻结新配置写入，备份 PostgreSQL、现有 Master Key、RabbitMQ 定义和运行配置；生成当前身份/RBAC、旧权限、资源和消息拓扑报告。
2. 完成 Phase 1 的新 RBAC 数据预检、双管理员登录验证和 Token/Secret 文件部署；维护窗口内一次切换 strict，并清理旧授权回退。
3. 部署 Migrator 和 schema head 验证，确认所有业务服务不再启动时迁移；随后切换连接池/UoW。
4. 停止 Worker/Dispatcher，排空可安全完成的 Job；创建 Outbox schema，按幂等规则回填尚未发布、待重试的 Job/Delivery，隔离无法转换的记录，再一次性切换消费者。确认旧队列无消息、无消费者后按精确名称删除旧 exchange、queue、binding、配置和代码，不使用通配删除。
5. 部署 Secret/Resource 新模型和导入工具，将仍需使用的 `env:` 引用显式导入为平台 Secret；此时不自动清空资源。
6. 执行 `resource-reset report/prepare`，等待资源依赖任务排空并再次获得用户对精确清单的确认后执行 `apply/verify`。
7. 从空配置通过凭据中心和工具资源界面重建 MySQL、SQL Server、Redis、Loki；Oracle 配置只有真实连接测试通过后才能发布。
8. 完成 UI 和 Phase 6 验收，保存日志、审计、Job、tool-call、Outbox、Delivery 和 DingTalk 回执证据。

回滚只能发生在阶段 Gate 内：停止相关服务并恢复该阶段开始前的代码、数据库备份和精确 RabbitMQ 定义。strict 授权失败时优先修复新 RBAC；不得用 compatibility 作为快速回退。资源 reset 后的恢复必须使用备份整体恢复，不允许把历史 revision 当作可编辑当前配置。

## Open Questions

当前没有阻止开始实现的问题。以下内容已经明确延期，后续必须建立独立 change 后才能实现：Worker 执行租约与取消、生产 HTTPS/HMAC、Network Zone/Egress Policy、Vault/KMS、Debug Trace 保留期、Capability Catalog/Handler 管理界面和真实 Oracle 11.2.0.4 验收。
