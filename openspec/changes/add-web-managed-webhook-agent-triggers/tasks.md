## 1. 依赖与现有链路预检

- [x] 1.1 核对 `add-unified-user-identity-and-rbac` 已提供 app_user、统一 RBAC、管理 session、默认 Agent definition/revision/publication 和 job publication 固定能力，记录本 change 可以复用的 API 与表
- [x] 1.2 追踪当前 `/webhooks/grafana/alert`、`/webhooks/channel/agent`、ChannelIngressService、CreateAgentJobService、RabbitMQ worker 和 ResultDeliveryService 的实际调用边界，形成实施前兼容清单
- [x] 1.3 核对现有 Grafana、Debug、钉钉 ingress/delivery connector 和 secret reference seed，明确默认 Trigger 迁移输入且确认仓库与数据库中没有明文生产凭证
- [x] 1.4 为新模块确定包边界、错误码、状态枚举、队列名、runtime config key 和管理 action 名称，并用架构测试防止 Webhook 模块绕过 Channel/Agent/Delivery 应用服务

## 2. 加法迁移与持久化模型

- [x] 2.1 新增加法 migration，为 `app_user` 增加有约束的 `account_type=human|service`，历史用户安全回填为 human
- [x] 2.2 创建 `webhook_trigger_definition`，包含稳定 code、不可预测 public_id、connector、专用服务账号、状态、当前 publication、revision 和审计时间字段
- [x] 2.3 创建 `webhook_trigger_revision` 与 `webhook_trigger_publication`，保存 schema version、规范化 snapshot/config hash、校验结果、actor 和不可变历史
- [x] 2.4 创建 `webhook_event`，保存固定 Trigger/Agent publication、服务账号、外部事件/幂等身份、payload hash、安全摘要、标准化事件、correlation/job 关联和状态时间
- [x] 2.5 创建 `webhook_replay_nonce`，以 Trigger + nonce hash 唯一约束和 expires_at 支持 HMAC 防重放及到期清理
- [x] 2.6 创建 `webhook_outbox` 或复用等价通用 outbox，保存 event ID、correlation ID、发布状态、attempt、next retry 和错误安全摘要
- [x] 2.7 为 Agent job 增加可空的 webhook_event/Trigger publication 来源引用并添加外键和查询索引，不修改或伪造历史非 Webhook job
- [x] 2.8 为 Trigger code/public_id、revision、publication、event dedup、状态/时间、nonce 到期和 outbox 待发布查询建立唯一约束与有界索引
- [x] 2.9 为所有新增表和安全敏感列补充中文 COMMENT，并验证 migration 可重复执行、旧版本应用可忽略新增可空字段且回滚不需要删表

## 3. 服务账号与统一授权

- [x] 3.1 扩展 IdentityRepository/domain DTO 读取和写入 account_type，并保持现有人类用户 API 的兼容响应
- [x] 3.2 在认证服务中禁止 service 账号创建密码凭证、登录 session 或刷新现有 session，并为拒绝结果增加安全审计
- [x] 3.3 在外部身份管理中禁止 service 账号绑定钉钉或其他人类外部身份，覆盖新增和更新路径
- [x] 3.4 实现 Trigger 专用服务账号创建/绑定服务，默认一 Trigger 一账号、默认无业务权限且与 Trigger 事务一致
- [x] 3.5 让 Webhook event、job、tool call 和 permission trace 使用服务账号 ID 作为 actor/requester，并保留 Trigger/publication/correlation 证据
- [x] 3.6 在事件分发前校验 Trigger、Connector、服务账号、Agent use、project 和 routing 平台范围，运行时工具集合继续取 Agent publication、registry、RBAC 和数据范围交集
- [x] 3.7 增加服务账号启停和权限管理 action/管理 API 安全摘要，确保 service 账号不出现在可登录用户候选中

## 4. Trigger 配置、版本和发布服务

- [x] 4.1 建立 Trigger definition/revision/publication domain model、状态机和 typed config DTO，覆盖 Grafana、通用 JSON、认证、mapping、routing、Agent、Delivery、幂等和限流
- [x] 4.2 实现 TriggerRepository 的列表、详情、创建、expected revision 草稿保存、校验状态、发布、历史、回滚和 public ID 轮换操作
- [x] 4.3 实现规范化 JSON 与稳定 config hash，发布 snapshot 不包含 secret value、原始测试 payload 或运行时可变对象
- [x] 4.4 实现 TriggerValidator，校验 schema version、adapter、ingress/delivery 方向、secret reference、服务账号、固定 Agent publication、routing allowlist 和限流范围
- [x] 4.5 发布 Trigger 时解析并固定 Agent code/publication ID/revision/hash和有效只读工具摘要，Agent 未发布、hash 不匹配或包含无效工具时 fail closed
- [x] 4.6 实现 Trigger 草稿 preview service，返回过滤、提取变量、routing、bounded message、dedup key、Agent 和 Delivery 安全预览且没有持久化/执行副作用
- [x] 4.7 实现 Trigger 启停、回滚和 public ID 轮换的事务语义，旧 public ID 在轮换提交后立即不可用
- [x] 4.8 为 Trigger 创建、草稿保存、校验、发布、回滚、启停、服务账号绑定和 public ID 轮换记录 before/after hash 与 actor 审计
- [x] 4.9 创建默认 Grafana Trigger/service account/revision/publication seed，复用现有 connector secret reference、`ea_*` 范围和固定钉钉 Delivery，不保存明文凭证

## 5. 安全认证、映射和过滤

- [x] 5.1 实现公共入口有界 raw body 读取、JSON Content-Type、请求大小、JSON 深度/集合数量和 public ID 格式校验
- [x] 5.2 实现 `bearer_v1` 认证，从受控 secret resolver 获取值并使用常量时间比较；secret 缺失或解析失败必须拒绝
- [x] 5.3 实现 `hmac_sha256_v1` canonical body、timestamp/nonce/signature header、常量时间签名校验和可配置时间窗
- [x] 5.4 实现 nonce hash 原子登记、重复拒绝和到期清理，确保 HMAC 重放不会创建第二条 event/job
- [x] 5.5 实现数据库支持的每 Trigger 请求速率、在途并发和 dedup cooldown 校验，不引入 Redis 且不同 Trigger 相互隔离
- [x] 5.6 实现受限 JSON Pointer 读取器、`exists/equals/in/not_equals` AND 条件和禁止脚本/任意函数的配置校验
- [x] 5.7 实现只引用已声明变量的 bounded message 模板，并把输出作为不可信外部证据而不是系统指令
- [x] 5.8 实现 routing `fixed`/`extract+allowed_values` 策略，对 project/environment/base/workshop 强制 allowlist并约束 service code
- [x] 5.9 实现 `grafana_alertmanager_v1` adapter：firing-only、groupKey/fingerprint 稳定身份、bounded labels/annotations/alerts 和 resolved ignored
- [x] 5.10 实现 `generic_json_v1` adapter：必填 event ID/message、声明式 filter、受控 routing 和稳定 dedup key
- [x] 5.11 统一 payload hash、安全摘要和敏感 key/value 脱敏，认证失败只记录 hash/大小/远端安全摘要，原始 body 不进入日志或数据库

## 6. Inbox、Outbox、队列和 Dispatcher

- [x] 6.1 实现 WebhookEventRepository 的幂等接收、ignored/rejected/accepted、dispatch claim、job 关联、失败和分页查询状态变更
- [x] 6.2 在同一 PostgreSQL 事务内写入 firing Webhook event 与 outbox，使用 Trigger + dedup identity 唯一约束返回已有事件 acknowledgement
- [x] 6.3 实现 outbox publisher，将最小 `webhook_event_id/correlation_id` 持久消息发布到专用 RabbitMQ 队列并记录 publisher confirm
- [x] 6.4 实现 outbox 恢复扫描、指数退避、最大 attempt、死信/人工可见错误和多实例安全 claim，RabbitMQ 临时失败不丢事件
- [x] 6.5 扩展消息总线协议、RabbitMQ declaration 和内存测试总线，Webhook dispatch 与 Agent job 队列均只携带 ID/correlation ID
- [x] 6.6 实现 Webhook dispatcher consumer，从 event 固定 snapshot 重建 ChannelEvent并调用现有 ChannelIngressService，不复制 job/权限/Delivery 逻辑
- [x] 6.7 扩展 CreateAgentJobCommand/Service 接受并校验固定 Agent publication 与 Webhook 来源引用，禁止 dispatcher 重新解析当前 Agent publication
- [x] 6.8 对 dispatcher 重投递、event 已关联 job、job 已终态和不可重试配置错误实现幂等 ack/失败状态，避免重复 Agent 和 Delivery
- [x] 6.9 实现 Webhook event 过期摘要/nonce/outbox 清理任务，删除策略不得级联删除关联 Agent job、audit 或 delivery 事实

## 7. 公共 Webhook API 与 Grafana 兼容

- [x] 7.1 新增 `POST /webhooks/v1/{public_id}`，按认证、映射、过滤和 Inbox 结果返回有界 event/correlation acknowledgement
- [x] 7.2 对成功持久化并等待异步分发的事件返回 `202 Accepted`，对 Grafana resolved 返回兼容 ignored 响应，对认证/限流/映射错误返回稳定安全错误码
- [x] 7.3 将旧 `/webhooks/grafana/alert` 改为解析兼容 header 后委托同一 WebhookIngressService，移除独立业务映射但保留当前响应字段和弃用提示
- [x] 7.4 保持受控 `/webhooks/channel/agent` 标准化入口兼容，同时明确它不作为任意外部系统绕过受管 Trigger 的匿名入口
- [x] 7.5 为未知/禁用/轮换 public ID、secret 解析失败、HMAC 重放、请求超限和 Trigger 未发布增加一致的审计、结构化安全日志和指标

## 8. 固定 Delivery 与事件证据

- [x] 8.1 从 Trigger publication 构造固定 ReplyRoute，忽略或拒绝 payload 中的 Agent、工具、connector、endpoint、token 和 delivery target 控制字段
- [x] 8.2 在 Trigger 校验和 dispatcher 中同时验证 ingress/delivery connector 方向、启用状态、Agent publication assignment 和目标安全摘要
- [x] 8.3 复用 ResultDeliveryService 的分片、attempt/chunk、重试和失败隔离，确保 Delivery 失败不会把 Webhook event重新分发或重跑 Agent
- [x] 8.4 为事件详情查询关联 job、tool call、audit、delivery attempt/chunk 的安全摘要，不复制完整报告或敏感目标

## 9. 管理 API 与权限

- [x] 9.1 增加 Webhook `read/edit/publish/rotate/manage_service_account` 等独立 action和默认管理员策略，所有写 API 使用可信 session actor、CSRF 和 deny 优先
- [x] 9.2 实现 Trigger 列表、创建、详情、更新、启停和服务账号摘要 API，使用 typed DTO、分页和 expected revision
- [x] 9.3 实现 revision 保存、校验、preview、publish、publication history 和 rollback API，返回字段级错误与 config hash
- [x] 9.4 实现 public ID 轮换 API，要求显式确认、并发 revision 和审计，响应只在必要时显示新的完整接入 URL
- [x] 9.5 实现 Trigger events 与 event detail API，支持状态/时间/job 过滤和关联执行/投递证据的脱敏分页响应
- [x] 9.6 对所有 Trigger/事件 API 做 secret、签名、原始 payload、密码/session 和完整 endpoint 泄漏检查

## 10. Web 管理界面

- [x] 10.1 扩展前端 Principal capability、API client、query keys、typed DTO、错误模型和导航，新增 `/admin/webhooks` 路由及权限守卫
- [x] 10.2 实现 Webhook 列表页，展示名称、类型、启停、当前 revision、固定 Agent/Delivery、服务账号、最近事件和安全状态
- [x] 10.3 实现创建/编辑页的基本信息、Grafana/通用 JSON adapter、Bearer/HMAC、secret reference、mapping/filter、routing 和限流表单
- [x] 10.4 实现默认诊断 Agent publication 与有效工具只读摘要、固定钉钉 Delivery/目标选择，页面不允许 payload override 或动态创建工具
- [x] 10.5 实现测试 JSON preview 面板，展示提取字段、ignored/firing、routing、message、dedup、Agent/Delivery，明确预览不会触发执行
- [x] 10.6 实现草稿 revision、字段级校验、发布确认、Agent 新版本提示、历史 publication 回滚和 public ID 轮换确认交互
- [x] 10.7 实现事件列表和详情页，展示认证/过滤/dispatch/job/tool/delivery 状态链及安全错误，不展示原始 payload 或 secret
- [x] 10.8 实现只读/编辑/发布/轮换不同权限下的按钮隐藏与后端拒绝反馈，保证前端限制不代替服务端授权

## 11. 后端与前端自动化测试

- [x] 11.1 增加 migration/repository 测试，覆盖历史 human 回填、Trigger revision/publication 不可变、public ID/dedup/nonce/outbox 唯一约束和普通 job 兼容
- [x] 11.2 增加服务账号测试，覆盖禁止登录/密码/session/外部身份绑定、Trigger 专用绑定、启停和统一 RBAC/数据范围
- [x] 11.3 增加 Trigger validator/version 测试，覆盖 secret、connector 方向、Agent publication/hash、routing allowlist、schema version、发布/回滚和 revision 冲突
- [x] 11.4 增加 Bearer/HMAC 测试，覆盖正确签名、错误 secret、secret 缺失、过期时间戳、nonce 重放、常量时间路径和认证失败不落正文
- [x] 11.5 增加 bounded JSON/JSON Pointer/template 测试，覆盖超大/超深 payload、缺失字段、未知表达式、脚本拒绝、输出截断和敏感字段脱敏
- [x] 11.6 增加 Grafana adapter 测试，覆盖 firing group、resolved ignored、groupKey/fingerprint、重复投递、多 alerts bounded summary 和缺失 routing
- [x] 11.7 增加 generic JSON adapter/preview 测试，覆盖声明式 filter、fixed/extract routing、allowlist 拒绝、控制字段覆盖无效和 preview 无副作用
- [x] 11.8 增加 Inbox/Outbox/RabbitMQ 测试，覆盖事务原子性、publisher confirm 失败、恢复扫描、重复消息、并发 claim、死信和最小队列载荷
- [x] 11.9 增加 dispatcher/Agent 测试，覆盖 Trigger 与 Agent publication 双固定、服务账号权限、已有只读工具交集、job 来源证据和草稿更新不影响已接收事件
- [x] 11.10 增加 Delivery 测试，覆盖固定钉钉目标、payload URL/connector 注入拒绝、长报告分片和投递失败不重跑 Agent
- [x] 11.11 增加旧/新 Grafana route 等价性和通用 Channel 兼容测试，确认旧 URL 委托统一服务且 firing/resolved 响应不破坏现有接入
- [x] 11.12 增加管理 API 权限/CSRF/revision/脱敏测试和 React 页面测试，覆盖列表、编辑、preview、发布、回滚、轮换、事件详情及只读权限

## 12. Runtime、文档和真实验收

- [x] 12.1 增加 Webhook 请求上限、HMAC 时间窗、事件保留、outbox 扫描、队列/重试、限流默认值的 typed runtime config，并保持 secret 只使用 secret reference
- [x] 12.2 更新 RabbitMQ/Compose worker 配置和健康检查，声明 Webhook dispatch/outbox 所需队列并验证 RabbitMQ 4 durable queue、persistent message、ack/prefetch 和队列排空
- [x] 12.3 更新 API/运维文档，提供 Grafana Contact Point firing-only 配置、Bearer/HMAC 签名规范、通用 JSON 示例、202 异步语义、权限和钉钉投递排障链
- [x] 12.4 提供脱敏 Grafana firing/resolved 和通用系统 fixture/curl smoke，fixture 不包含真实 token、员工标识、Webhook URL 或业务敏感全文
- [x] 12.5 运行 migration、后端完整 pytest、ruff、mypy、前端 test/typecheck/build、Compose config 和 OpenSpec strict validation，修复全部回归
- [ ] 12.6 在 Compose 中验证新 public URL：firing 只创建一个 event/job、Agent 调用现有只读 API 工具、结论分片发送到固定钉钉机器人，resolved 不创建 job
  - 已验证 firing/resolved/重复 firing 的 event/job 幂等；因未提供真实 Claude、只读 API 和钉钉测试群凭证，尚未运行 Agent 与固定 Delivery。
- [x] 12.7 验证安全负路径：空 secret、错误 Bearer/HMAC、nonce 重放、超大 payload、越界 routing、禁用 Trigger/服务账号和 payload Delivery 注入均 fail closed且无敏感落库
- [ ] 12.8 验证故障恢复：接收后停止 RabbitMQ、确认 event/outbox 不丢失，恢复后只创建一个 job，重复 delivery 不重跑 Agent，队列最终回到零 ready/unacked
  - 已验证 RabbitMQ 停机期间 202 + pending outbox、恢复后 publisher confirm 与单 job；Agent worker 为避免外发而暂停，尚未验证 Delivery 失败后的最终队列归零。
- [ ] 12.9 使用脱敏真实 Grafana Alertmanager 报文和真实钉钉测试群完成一次端到端验收，保存 event、job、tool call、audit、delivery attempt 的安全证据并记录旧 URL 回退步骤
