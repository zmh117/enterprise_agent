## 1. 基线、边界与安全预检

- [x] 1.1 记录当前测试、Compose 服务、数据库 migration head、RabbitMQ 拓扑和前后端构建基线，并保存可重复的只读检查命令
- [x] 1.2 为 Debug 身份覆盖、Internal API Header 伪造、空 Connector Secret、migration 重复版本、DB 全局连接和 DB/Rabbit 双写窗口补充失败特征测试
- [x] 1.3 盘点并导出身份、新 RBAC、两名人类平台管理员、旧 `permission_policy`/`platform_access_grant`、全部 DB/Redis/Loki 资源、Secret 和受影响应用清单
- [x] 1.4 盘点精确 RabbitMQ exchange、queue、binding、consumer 与待处理消息，区分当前路径、旧路径和后续 Outbox 目标
- [x] 1.5 定义本次新增/修改表、索引、唯一键、状态枚举、审计事件和 correlation/idempotency 字段的数据字典
- [x] 1.6 建立六阶段 Gate 检查脚本/文档，明确任何破坏性 apply 前必须重新生成 digest、展示精确影响并获得用户确认

## 2. Phase 1：严格授权与运行时信任边界

- [x] 2.1 为当前登录用户实现 `agent.debug.execute` 权限检查，重构 Debug 创建 DTO，拒绝 `user_id`、任意 Agent、资源、Connector 和 reply route
- [x] 2.2 实现 Debug 可用业务应用、Execution Scope、可选 Delivery binding 查询，并为 Job/Step/Tool Call 查询增加创建人、应用运维或平台管理员授权
- [x] 2.3 将 Debug 创建事务改为固化登录用户、业务应用发布、Execution Scope、会话策略和幂等上下文，并补充越权/重复提交测试
- [x] 2.4 实现 `INTERNAL_API_AUTH_TOKEN_FILE` 与 current/next 受控轮换装配、常量时间校验、非测试缺失启动失败和全链路脱敏测试
- [x] 2.5 重构 Internal API 授权器：按 Job ID 重读 Job、状态、应用发布、Handler、Resource Revision 与 Execution Scope，并把其余 Header 降为一致性校验
- [x] 2.6 增加无 Token、伪造 user/scope Header、未知 Job、非执行状态 Job、越权资源和有效 Job 的 Internal API 集成测试
- [x] 2.7 删除 `compatibility` 配置项、代码分支和授权 fallback，使全局运行时只接受 `strict_application_role`
- [x] 2.8 在用户禁用、删除、角色移除与管理员变更事务中实现“两名已登录验证的人类 platform-admin”不变量并补充并发测试
- [x] 2.9 将所有外部 HTTP Webhook binding 改为唯一强 `Authorization: Bearer` Secret，删除空 Secret/fail-open、旧 `X-Grafana-Token` 入口和兼容翻译
- [x] 2.10 实现 Connector Secret 不可解析时的 MISCONFIGURED、ingress/delivery 停用、重绑和测试流程，并覆盖 Grafana 仍可用标准 Bearer 正常触发
- [x] 2.11 实现发布版本/Connector/外部会话/Execution Scope 隔离的 Session key，停用新 Job 的 `application`/`actor` 模式并验证旧 Session 只读
- [x] 2.12 完成 Phase 1 自动化 Gate：无效 Token 不创建 Job、缺失新 RBAC 拒绝、Debug 不可冒充、会话不跨用户/发布/范围复用且无 Secret 泄漏

## 3. Phase 2A：独立 Migrator 与操作级 Unit of Work

- [x] 3.1 建立唯一 migration version 校验和稳定 checksum 计算，修复现有重复版本并为已应用 migration 建立兼容账本基线
- [x] 3.2 实现 one-shot Migrator CLI/入口、PostgreSQL advisory lock、逐版本完整事务、失败回滚和账本记录
- [x] 3.3 为并发 Migrator、checksum 漂移、重复版本、中途失败和幂等重跑增加数据库集成测试
- [x] 3.4 从 API、Worker、Dispatcher、Internal API Platform 启动路径删除 auto-migrate，只保留只读 schema head 校验和安全失败
- [x] 3.5 更新 Docker Compose，使业务服务等待 Migrator 成功退出，并验证 migration 失败时业务服务不得进入 ready
- [x] 3.6 引入同步数据库连接池与显式 Unit of Work，消除全局共享 connection 和 transaction depth
- [x] 3.7 按请求、消息与 CLI 边界迁移 Repository/Service，确保异常回滚、连接归还和并发事务相互隔离
- [x] 3.8 审计模型、HTTP、RabbitMQ、数据库工具和 DingTalk 调用点，拆除跨外部 I/O 的数据库事务并增加事务边界测试
- [x] 3.9 完成 Phase 2A Gate：多副本启动只迁移一次、所有服务校验同一 head、连接池并发与回滚测试通过

## 4. Phase 2B：Job Dispatch Outbox

- [x] 4.1 新增 Job Dispatch Outbox schema、状态、attempt、到期时间、唯一 event/idempotency key、审计与查询索引
- [x] 4.2 重构所有 Job 创建入口，使 Job、消息、授权快照和唯一 Outbox event 在同一 Unit of Work 中提交
- [x] 4.3 实现多副本安全 Dispatcher 领取、publisher confirm、有限退避、RETRY_WAIT/DEAD 和安全指标
- [x] 4.4 将 RabbitMQ payload 收敛为 event/job/correlation 标识，并让消费者从 PostgreSQL 加载完整执行事实
- [x] 4.5 实现持久化消费者幂等和原子 Job claim，验证重复 RabbitMQ 消息不会重复执行已完成 Job
- [x] 4.6 实现按 event/job 精确定位的只读状态与 CLI replay，拒绝任意 payload 和无限重试
- [x] 4.7 实现旧 pending/retry 消息的 dry-run/backfill/quarantine 切换工具，输出精确旧拓扑和 digest，不执行通配删除
- [x] 4.8 增加数据库提交失败、RabbitMQ 中断、confirm 前后崩溃、重复发布、多 Dispatcher 和 DEAD replay 集成测试
- [x] 4.9 文档化本次不恢复已经 RUNNING 的崩溃 Job，状态页/验收报告不得把 Outbox 描述为执行租约
- [x] 4.10 完成 Phase 2B Gate：证明已提交 Job 不丢失、重复 event 无重复业务结果、失败有限进入 DEAD

## 5. Phase 2C：Delivery Outbox 与独立状态机

- [x] 5.1 新增 Delivery Outbox 与 `PENDING/RUNNING/RETRY_WAIT/SUCCEEDED/FAILED/DEAD/SKIPPED` 状态、attempt、chunk、唯一键和索引
- [x] 5.2 重构 Agent 成功/最终失败事务，使结果 artifact、Job 终态和 Delivery event 原子保存且不直接调用 adapter
- [x] 5.3 实现 Delivery Dispatcher、有限退避、终态 DEAD、none route SKIPPED 和多副本安全领取
- [x] 5.4 实现 Delivery event/attempt/chunk 端到端幂等，确保重复消费不重复发送已成功分片
- [x] 5.5 实现 Job 详情中的独立 Delivery 时间线、只读状态/指标和不误报“已送达”的前端/API contract
- [x] 5.6 实现按 delivery ID 的安全 CLI replay，只复用固化 binding、目标摘要和结果 artifact，拒绝改写目标/payload
- [x] 5.7 增加 Job 成功但 Delivery 失败、分片中断、RabbitMQ 恢复、重复 event、耗尽 DEAD 和 replay 的集成测试
- [x] 5.8 完成 Phase 2C Gate：证明 Delivery 故障不重跑 Agent，Job 与投递终态可独立审计和恢复

## 6. Phase 3A：固定 Master Key 与凭据中心后端

- [x] 6.1 定义仓库外固定 Master Key 文件格式、权限检查、备份与非测试缺失失败，删除 Compose/代码硬编码回退
- [x] 6.2 加固 Secret 加密存储、版本、active/disable、内存解密边界和明文永不回显，并补充日志/异常/审计泄漏测试
- [x] 6.3 将可创建 Provider 限定为 `secret://platform/<code>`，让 `vault:`/`kms:` 明确返回未实现并阻止创建/发布
- [x] 6.4 实现旧 `env:` 引用的 report/import dry-run、一次读取、平台 Secret 创建、引用改写和幂等审计；新 API/UI 禁止创建 env 绑定
- [x] 6.5 实现凭据列表、创建、轮换业务 Secret、禁用、用途/依赖查询和仅 metadata 响应的授权 API
- [x] 6.6 实现 Secret active version 变化通知相关资源 reload，失败时保持 Last Known Good
- [x] 6.7 编写仅用于紧急情况的离线 Master Key 重加密 runbook，不实现 Web 管理、多 keyring、有效期或周期轮换
- [x] 6.8 完成 Phase 3A Gate：数据库、API、日志、审计、Job、tool-call 和前端状态均找不到明文/密文，禁用 Secret 能安全降级

## 7. Phase 3B：工具资源版本、Provider 契约与 Handler 基础

- [x] 7.1 新增 Resource Identity、Draft、Verification、immutable Revision、Application Publication Binding、activation/LKG 记录及数据库约束
- [x] 7.2 实现 DRAFT→VERIFIED→PUBLISHED 单发布者技术门禁、Draft 删除、Published disable/archive 和禁止原地修改/普通物理删除
- [x] 7.3 建立管理 API、前端 schema、验证器和运行时共享的 canonical Provider contract，显式转换或拒绝旧字段
- [x] 7.4 实现 MySQL 与 SQL Server 的结构化连接、`username/password_ref`、只读账号权限探针、AST 单 SELECT/readonly WITH、timeout/rows/bytes 门禁
- [x] 7.5 实现 Oracle 11.2.0.4 Host/Port + Service Name/SID 二选一 contract、19c Thick 初始化、架构检查、ROWNUM 限制和禁止 Thin fallback
- [x] 7.6 更新 Oracle 镜像/客户端布局并完成静态、单元、镜像启动测试；因无真实 Oracle，将真实连接发布门禁保持 blocked 并标记 deferred
- [x] 7.7 对齐 Redis `host/port/database/username/password_ref/TLS` 与 Loki `base_url/tenant_id/auth_ref/limits`，保留 prefix/label 只读边界
- [x] 7.8 实现代码 Handler Registry 的稳定 ID、不可变版本、schema、风险、权限和逻辑资源槽，拒绝数据库动态 Python/脚本/SQL/URL 实现
- [x] 7.9 实现 installed∩published∩resource-bound∩agent∩application∩role∩scope 解析，并把 `query_database` 开放为受同一治理交集约束的只读业务能力
- [x] 7.10 在业务应用发布时绑定具体 Handler version 和 Resource Revision，在 Job 创建时固化不可变 Execution Scope
- [x] 7.11 增加资源状态机、并发发布、不可变性、Provider 字段、只读探针、Handler 交集、scope 越权和普通业务应用可配置受治理通用 SQL 的测试
- [x] 7.12 完成 Phase 3B Gate：所有新资源只含 `secret://platform/`、发布后不可变、应用/Job 不浮动版本且未实现 Provider 不可用

## 8. Phase 4：运行时热加载、Readiness 与受控资源重置

- [x] 8.1 实现 published generation 轮询、完整不可变快照构建、原子 swap 和每请求固定 generation
- [x] 8.2 实现加载失败保留 Last Known Good、资源/应用 degraded/blocked、无 LKG 时只阻止相关应用并输出脱敏状态
- [x] 8.3 拆分 `/health` 进程存活与 `/ready` 核心依赖/schema/Token/Master Key 校验，补充资源级 readiness 且不调用外部模型
- [x] 8.4 实现 `resource-reset report`，精确列出全部 DB/Redis/Loki identity、Draft、revision、binding、effective snapshot 和受影响应用
- [x] 8.5 实现 `resource-reset prepare`：进入维护模式、阻止新资源依赖 Job、等待运行任务排空、超时中止、创建备份引用/operation ID/digest
- [x] 8.6 实现 `resource-reset apply` 的再次确认、digest/change 检查和受控事务，只删除目标资源对象并把依赖应用标为 blocked
- [x] 8.7 实现 `resource-reset verify`，证明资源为空、无悬空 binding，Provider/Secret/身份/RBAC/应用/Job/Delivery/审计/历史快照均保留
- [x] 8.8 增加热加载并发、失败 LKG、无 LKG 阻断、Secret 轮换和 reset dry-run/change-detection/rollback 集成测试
- [x] 8.9 生成实际资源 reset report/prepare 及精确影响后暂停，等待用户再次确认；未确认前不得执行实际 apply
- [x] 8.10 完成 Phase 4 Gate：经确认执行后从空资源配置开始，且所有明确保留的数据类别通过 verify

## 9. Phase 5：凭据、工具资源与调试界面

- [x] 9.1 新增“平台治理 → 凭据中心”路由、权限、列表、创建/轮换业务 Secret、禁用、用途和永不回显交互
- [x] 9.2 新增“平台治理 → 工具资源”列表与筛选，清晰展示 type、scope、draft、published、effective、activation、degraded/blocked
- [x] 9.3 实现 MySQL、SQL Server、Oracle、Redis、Loki canonical 表单和凭据中心 Combobox，只保存 Secret reference
- [x] 9.4 实现 Draft 创建/编辑/删除、技术测试、发布、disable/archive，并在验证后内容变化时提示重新验证
- [x] 9.5 实现发布成功但激活失败、Last Known Good 和受影响应用状态，不得把 published 误显示为 effective
- [x] 9.6 新增“运行中心 → 发起调试”，只列授权应用、Execution Scope 和可选 Delivery binding，默认 none
- [x] 9.7 调试创建成功后导航到受保护 Job 详情，分别展示 Agent、dispatch Outbox、tool-call 和 Delivery 时间线
- [x] 9.8 增加前端权限、表单契约、Secret 不回显、状态展示、越权选项不可见和关键交互浏览器测试
- [x] 9.9 完成 Phase 5 Gate：凭据/资源可从空配置安全建立并生效，Debug UI 无任意身份、资源、Connector 或路由输入

## 10. 维护窗口切换与旧路径清理

- [x] 10.1 冻结配置写入并创建 PostgreSQL、Master Key、RabbitMQ 定义和运行配置的可恢复备份，校验备份引用
- [x] 10.2 重新生成 strict RBAC 预检并实际登录验证至少两名人类 platform-admin；缺少新授权先修复 RBAC，不启用 compatibility
- [ ] 10.3 展示旧授权数据精确数量/digest 并再次获得用户确认后，事务清理 `permission_policy`、`platform_access_grant` 及其运行时代码/配置
- [x] 10.4 停止旧 Worker/Dispatcher，排空或幂等 backfill pending/retry Job 与 Delivery，隔离无法转换的记录并核验新 Outbox
- [ ] 10.5 展示旧 RabbitMQ 拓扑精确清单并再次获得用户确认后，只按精确名称删除已排空且无消费者的旧 exchange/queue/binding
- [ ] 10.6 显式导入仍需保留的旧 `env:` Secret 引用并核验新资源引用；不迁移或声明 `vault:`/`kms:` 可用
- [x] 10.7 按 Phase 4 重新生成的 report/prepare 及用户确认执行全量 DB/Redis/Loki reset，并保存 verify 证据
- [ ] 10.8 从空配置建立并发布本地验收所需 MySQL 或 SQL Server、Redis、Loki 资源及业务应用 binding；Oracle 保持未发布
- [ ] 10.9 完成维护切换核验：无 compatibility、无旧消息消费者、无运行时 YAML 资源 fallback、无悬空 binding、核心服务 ready

## 11. Phase 6：CI、Compose 与真实链路验收

- [ ] 11.1 将 CI、Dockerfile 和文档统一到 npm lockfile 与 `npm ci`，移除 pnpm lock 路径并验证冷构建
- [ ] 11.2 建立 PR 快速 Gate：后端单元/契约、前端 lint/type/build/test、migration 静态/checksum、OpenSpec 严格校验
- [ ] 11.3 建立 Compose 集成 Gate：Migrator 先行、schema head、多个 API/Dispatcher 安全、PostgreSQL/RabbitMQ 中断恢复和健康状态
- [ ] 11.4 用无效 Webhook Token 验证不创建 Inbox/Session/Job/Outbox，用缺失 RBAC 验证 fail closed
- [ ] 11.5 对 RabbitMQ 中断、Job retry/DEAD、Delivery retry/DEAD、重复消息和精确 CLI replay 执行故障注入并保存证据
- [ ] 11.6 扫描 API 响应、数据库普通表、日志、审计、Job、tool-call、Outbox 和前端产物，证明没有 Secret 明文或 Master Key
- [ ] 11.7 使用真实本地 Grafana + 标准 Bearer 发送新鲜合成 firing 事件，贯通 Inbox/Job Outbox/RabbitMQ/Worker
- [ ] 11.8 使用真实只读 MySQL 或 SQL Server 工具取得受限证据，再贯通结果/Delivery Outbox/真实 DingTalk 回复并保存 correlation 证据
- [ ] 11.9 验证受保护 Debug UI 的创建、查询、默认 none 和可选现有 Delivery binding，不依赖公开 API/PAT
- [ ] 11.10 在验收报告中明确 HTTP 仅限本地，并将真实 Oracle、Worker RUNNING 崩溃恢复、任务取消、HTTPS/HMAC、Egress、Vault/KMS 标记为未实现/延期
- [ ] 11.11 完成 Phase 6 Gate：所有自动化与真实链路证据通过，任何延期能力均未被误报为已完成

## 12. 文档、证据与后续交接

- [ ] 12.1 更新本地部署、固定 Master Key、Internal API Token 轮换、资源发布、Outbox/DLQ CLI、维护窗口和故障排查文档
- [ ] 12.2 记录六阶段实现证据、数据库与 RabbitMQ 切换摘要、资源 reset verify、真实 E2E correlation 和已知限制
- [ ] 12.3 复核 `reset-identity-and-authorization-bootstrap` 仍保持暂停且未被本 change 修改，记录其未来需同步 strict-only 决策
- [ ] 12.4 为后续 Worker 执行租约/fencing/取消建立独立 change 候选，不在本次 tasks 中实施
- [ ] 12.5 为后续 API Capability Catalog/Handler 管理界面提供稳定的 Handler Registry、Resource Slot 和 Application Publication contract 交接说明
- [ ] 12.6 运行最终 OpenSpec 严格校验和全量测试，确认 tasks、specs、design 与实际行为一致后再申请归档
