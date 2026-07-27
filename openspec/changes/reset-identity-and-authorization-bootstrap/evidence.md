## 实施证据

### 2026-07-26 前置基线

- 工作区基线：`git status --short` 仅显示本 change 目录为未跟踪内容；未发现需要清理或覆盖的其它修改。
- 当前迁移 head：`017_role_authorization_control_center.sql`。项目迁移器按文件名顺序幂等执行 SQL，不维护独立 migration history 表。
- 角色授权相关脱敏回归测试：`78 passed, 1 skipped`。
- Compose 状态：`api-server`、`postgres`、`rabbitmq`、`dingtalk-runtime`、`channel-dispatch-worker` 等关键服务运行；带 healthcheck 的关键容器为 healthy。
- 真实私聊证据：已有 `conversationType=1` 的 `JOB_CREATED -> SUCCEEDED -> dingtalk_stream_session_webhook/SUCCEEDED` 链路，但这些 Job 的工具调用数为 0，尚不能满足完整 Tool 链验收。
- 真实群聊证据：已有 `conversationType=2` 的中文 `identity_not_bound` 拒绝，但尚无群聊成功 Job 和回复路由证据。
- 绑定证据：已发现“未绑定拒绝 -> 绑定后无应用权限拒绝 -> 分配角色后 Job 与投递成功”的状态序列；当前候选聚合显示绑定候选不再作为未绑定候选返回。

### 前置门槛

以下外部验收完成前，不执行本 change 的代码实现或真实身份授权清理：

- 使用真实钉钉私聊触发至少一次只读工具调用，并验证 Runtime → Inbox → Outbox → RabbitMQ → Job → Worker → Tool → Delivery。
- 使用真实钉钉群聊验证按原发送人授权、群聊回复路由和中文权限拒绝。
- 汇总角色授权控制中心最终测试数量、容器状态和上述真实链路证据。

### 2026-07-27 补发消息核验

- 收到一条新的真实私聊，脱敏链路为 `JOB_CREATED -> SUCCEEDED -> dingtalk_stream_session_webhook/SUCCEEDED`。
- 该 Job 固定的 Agent Publication 有 8 个工具，但本次实际工具调用数仍为 0。
- 数据库授权事实显示 `E2E 只读诊断` 角色已获得 `default-diagnostic-application` 使用权，但角色业务能力数为 0；当前应用发布快照也没有装配可授权业务能力。因此 `get_schema_directory` 未进入 Agent 可见工具集合。
- 最近 30 分钟没有新的群聊入站事件。
- `dingtalk-runtime` 在 API 容器启动期间曾因 `api-server` DNS 尚不可用而重试，之后已经 `connect success`；本次私聊 Inbox 返回 200。
- 正式管理页面需要重新登录；未绕过认证，也未直接修改数据库授权。

### 2026-07-27 能力目录前置修复与重新配置

- 发现业务应用服务和管理端将已经接线的只读工具目录硬编码为“未接入”，导致应用发布快照不能装配能力，角色也无法获得能力授权；未采用人工改库绕过。
- 后端现从 `tool_definition` 返回已启用的只读能力，并在校验/发布时额外确认能力属于所选 Agent Publication；管理端仅允许从目录勾选，不提供任意能力编码或地址输入。
- 自动化验证：后端全量 `397 passed, 12 skipped, 4 subtests passed`；管理端 `44 passed`，TypeScript typecheck、ESLint、Ruff 均通过；角色中心与重置 change 的 OpenSpec strict validation 均通过。
- 已重建并替换 `api-server`、`admin-web`，两者启动成功且 `api-server` healthy；`dingtalk-runtime`、`agent-worker`、`channel-dispatch-worker` 持续运行，Runtime 已恢复租约、期望配置和状态上报。
- 通过真实管理页面为默认诊断应用创建、校验、发布 r17；发布快照固定 8 个 Agent r29 已绑定的只读能力，并将 r17 激活为 local deployment revision r10。
- 通过真实角色页面为 `E2E 只读诊断` 角色原子保存相同 8 个应用能力；数据库独立核对 capability count 为 8。
- 能力配置前最后一条真实私聊已完成 `Runtime → Inbox → Outbox → RabbitMQ → Job → Worker → Delivery`，但工具调用数为 0；必须在 r17 激活和角色授权后发送新消息，才能完成 Tool 链门槛。
- r17 激活和角色授权后的第一条私聊已固定到 r17 并完成 Inbox、Outbox、Job、Worker 和 Delivery；发送人角色、应用访问与 8 个能力交集均有效。由于验收语句没有提供 `get_schema_directory` 必需的环境和基地，Agent 按“不猜测目标”边界未调用工具；此条仍不计入 Tool 链通过证据。

### 2026-07-27 Internal API Platform 统一授权闭环修复

- 两条新的真实私聊均进入 `Runtime → Inbox → Outbox → RabbitMQ → Job → Worker → Delivery`，并实际发起只读工具调用；其中正确的 `agent_test/mysql` 结构目录请求在 Worker 业务授权通过后，被 Internal API Platform 的旧 `platform_access_grant` 二次校验返回 403。
- 根因是 Internal API Platform 仍仅按旧 grant 和 `X-Agent-User-Id` 授权，没有消费 Job 已固定的内部用户、业务应用、能力和明确数据范围；这与角色授权中心统一决策模型不一致。未通过新增通配 grant 绕过。
- 修复后，业务应用 Job 的每个 Internal API 请求携带 `X-Agent-Job-Id`，平台重新读取持久化 Job，校验 Job 为 RUNNING、调用用户与 Job 内部用户一致，再使用同一 `BusinessAuthorizationService` 校验应用、能力和环境/基地/车间；拒绝不会回退旧 grant。无业务应用的旧调试调用继续使用兼容 grant。
- 增加服务、路由、适配器、真实 SQLite 角色/应用/范围/Job 和执行中撤权回归测试；定向测试 `70 passed`。
- 全量自动化验证：后端 `405 passed, 12 skipped, 4 subtests passed`；管理端 `44 passed`；Ruff、TypeScript typecheck、ESLint，以及角色中心和重置 change 的 OpenSpec strict validation 均通过。
- 已重建并替换 `internal-api-platform` 与 `agent-worker`；平台进程启动完成，Worker 已重新连接 RabbitMQ 并消费 `agent.job.queue`。Internal API 健康端点可访问，但因既有 `sanjiu/mmk` 旧资源缺少配置字段显示 `degraded`；本次目标 `agent_test/mysql` 仍保留在数据库拓扑中，需由真实调用继续验收。
- 上述两条私聊均属于修复前证据，不能计入 13.8；必须在新镜像启动后重新发送带明确 `environment=agent_test`、`base=mysql` 的私聊。

### 2026-07-27 修复后真实钉钉私聊通过

- 新私聊事件的安全摘要为 `conversationType=1`、`hasText=true`；Inbox 状态 `JOB_CREATED`，Outbox 状态 `published` 且仅发布 1 次。
- Job `job_f11df1c3cbf946a699ee22325727048d` 固定到当前业务应用，Worker 启动和工具调用阶段的统一业务授权均为 `SUCCEEDED`。
- `get_schema_directory` 使用明确参数 `environment=agent_test`、`base=mysql`，Tool 状态 `SUCCEEDED`；Internal API Platform 返回 200，并返回 MySQL 表结构目录，证明新 Job 绑定授权替代了错误的旧 grant 二次拒绝。
- Job 状态 `SUCCEEDED`，`dingtalk_stream_session_webhook` Delivery 状态 `SUCCEEDED`，`delivery.chunk_sent` 与 `delivery.completed` 均成功。
- 13.8 的 `Runtime → Inbox → Outbox → RabbitMQ → Job → Worker → Tool → Delivery` 真实私聊门槛已满足。

### 2026-07-27 真实钉钉群聊通过

- 新群聊事件安全摘要为 `conversationType=2`；Inbox 状态 `JOB_CREATED`，Outbox 状态 `published` 且仅发布 1 次。
- Job `job_8d50a6742ad540a58df0a61cf4d7e1d5` 固定的内部用户与入站钉钉外部身份绑定一致，证明授权主体是原发送人而非群或机器人。
- 数据库布尔核对证明回复目标群与入站群一致，并且 `at_user_ids` 中的目标等于原发送人的钉钉身份；未记录会话回调地址。
- Worker 启动和工具调用授权均为 `SUCCEEDED`，`get_schema_directory` 使用 `environment=agent_test`、`base=mysql` 并成功，Internal API Platform 返回 200。
- Job 与 `dingtalk_stream_session_webhook` Delivery 均为 `SUCCEEDED`，`delivery.chunk_sent` 和 `delivery.completed` 成功。
- 既有未绑定群聊事件为 `conversationType=2`、`REJECTED/identity_not_bound`，中文安全提示为“你的钉钉账号尚未获得授权，请联系管理员”；结合本次授权成功链，13.9 门槛已满足。

### 2026-07-27 角色授权中心最终门槛

- 后端全量：`405 passed, 12 skipped, 4 subtests passed`；Ruff 通过。
- 管理端：`44 passed`；TypeScript typecheck、ESLint 通过。此前 production build 与真实浏览器管理链路均已通过。
- OpenSpec：`add-role-and-authorization-control-center` 与 `reset-identity-and-authorization-bootstrap` strict validation 均通过；Compose 配置校验通过。
- 本次授权闭环镜像：`agent-worker` image `579486429250`，`internal-api-platform` image `8d3d22b6d018`；`api-server`、`admin-web` 保持本轮已验证镜像。
- Compose 中 API、Runtime、Worker、Internal API、PostgreSQL、RabbitMQ、管理端及 Agent 测试数据服务全部运行；配置健康检查覆盖的关键依赖均为 healthy。
- Internal API `/health` 对既有 `sanjiu/mmk` 不完整旧资源仍报告 `degraded`，但本 change 验收目标 `agent_test/mysql` 已通过真实授权 Tool 调用；未掩盖或修改旧资源配置告警。
- 真实私聊与群聊均完成 `Runtime → Inbox → Outbox → RabbitMQ → Job → Worker → Tool → Delivery`；群聊额外证明原发送人身份授权、原群回复和 @ 原发送人，未绑定群聊中文拒绝也已证明。
- 13.8、13.9、13.14 全部完成，独立重置 change 的前置门槛已满足。
