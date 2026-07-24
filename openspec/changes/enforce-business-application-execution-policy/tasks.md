## 1. 执行策略领域模型与持久化

- [x] 1.1 枚举所有直接或间接引用 `agent_job`、`agent_session`、`agent_message`、附件和投递记录的表及 MinIO object key，形成删除顺序、保留控制面表清单和删除前后计数
- [x] 1.2 实现一次性维护清理命令，在数据库删除前枚举并删除旧 Job 关联的 MinIO 附件/产物对象，任一对象清理失败时停止并返回安全报告
- [x] 1.3 新增下一顺序可重放 schema migration 临时增加可空 `agent_job.execution_policy_json`；由显式确认的一次性维护命令按外键安全顺序删除旧运行数据和孤立 Session，随后将该列改为 `NOT NULL` 且不设置默认值
- [x] 1.4 新增版本化 `JobExecutionPolicySnapshot` 值对象，严格解析 `requested`、`effective`、`sources` 和 `schema_version`，拒绝空对象、未知版本和缺失有效字段
- [x] 1.5 实现纯领域 `EffectiveExecutionPolicyResolver`，对 `max_turns`、`timeout_seconds` 取业务应用与固定 Agent Publication 的更严格值，对 `max_tool_calls` 使用规范化应用值，并为非业务应用新 Job 生成相同 v1 快照
- [x] 1.6 为缺失 Agent 值、业务应用更严格、更宽松、`max_tool_calls=0`、边界值、非法快照和不同 `source_kind` 补齐领域单元测试
- [x] 1.7 扩展 `AgentJob`、`CreateAgentJobCommand`、PostgreSQL 仓储创建/读取/运行记录投影以强制保存和返回固定策略，确保日志与审计不写入敏感内容
- [x] 1.8 增加仓储与迁移测试，证明所有新 Job 必须提供合法策略、旧运行链完整删除、控制面配置保留、重复消息幂等和 Job 重读正确

## 2. 入口固定策略与Job provenance

- [x] 2.1 在 `ChannelIngressService` 命中 Business Application route 后读取固定 Publication 的 `execution_policy` 并传给 Job 创建命令
- [x] 2.2 在 `CreateAgentJobService` 完成 Agent Publication revision/hash 校验后计算有效策略，并在创建 Session、Job、用户消息的既有事务中持久化
- [x] 2.3 逐一修改调试 API、旧钉钉 webhook、受管 Webhook 和其他 Job 创建入口，使其在创建阶段从 Agent Publication/运行时默认值生成必填 v1 策略
- [x] 2.4 确保 RabbitMQ payload 仍只包含 `job_id`、`correlation_id`，Worker 不从消息体接收策略 JSON
- [x] 2.5 增加路由集成测试，证明请求值与有效值、应用/Agent Publication 来源、config hash 和 route provenance 同时固定
- [x] 2.6 增加发布、激活、回退和重试测试，证明已入队 Job 不重新读取当前 Deployment，新 Job 才使用新策略
- [x] 2.7 增加所有 Job 创建入口的契约测试，证明迁移后不存在空策略 Job，缺失或不合法策略在入队前失败关闭

## 3. Worker与Agent运行时强制执行

- [x] 3.1 扩展 `AgentExecutionContext` 和上下文构建器，从 Job 固定快照提供有效 `max_turns`、`timeout_seconds`、`max_tool_calls`，不得从活动应用重新解析
- [x] 3.2 在 Worker claim 后、调用模型前验证 v1 快照；空对象、未知 schema 或字段缺失以不可重试 Job 完整性错误结束且不调用模型/工具
- [x] 3.3 实现单 attempt 共享的 `ToolCallBudget`，在每个内部 MCP handler 调用 `ToolRegistry` 前计数成功或失败的调用尝试
- [x] 3.4 实现专用策略耗尽异常和 `execution_policy_max_tool_calls_exhausted` 稳定错误码，保证超过上限的调用不进入 ToolRegistry 或下游数据源
- [x] 3.5 将固定有效 `max_turns` 传给 Claude SDK options，将固定有效 `timeout_seconds` 用于 SDK session 墙钟超时，删除 Worker 阶段的 Agent Publication/全局默认 fallback
- [x] 3.6 在真实 Claude、Stub runtime 和 fake SDK 测试夹具中统一执行策略契约，覆盖零工具预算、恰好达到上限、超过上限、失败调用计数、最大轮次和 timeout
- [x] 3.7 确保最大工具调用和最大轮次耗尽不进入普通 transient retry，timeout 保持现有 retry 分类且每次 attempt 复用同一固定策略
- [x] 3.8 确保策略耗尽前的工具事件由 `AgentExecutor` 持久化，Job step、失败原因、审计和原钉钉会话失败 Delivery 使用安全摘要
- [x] 3.9 增加并发/重复 RabbitMQ delivery 测试，证明现有 Job claim 幂等仍阻止同一 Job 同时执行和重复发送失败通知

## 4. 运行时就绪判定与管理API

- [x] 4.1 为 `RuntimeComponentStatus` 增加服务端返回的 `impact=runtime|governance`，所有列表、详情、Publication、Deployment、effective 和审计投影复用统一模型
- [x] 4.2 将现有 Session 组件拆分为已接线的 `session_policy` 和非阻塞 `retention_policy`，后者保持 `retention_days=stored_only` 与稳定 reason code
- [x] 4.3 将 Execution Policy 组件改为逐字段报告 `max_turns= wired`、`timeout_seconds=wired`、`max_tool_calls=wired`，仅在 Worker 确实支持策略 schema 时标记已接线
- [x] 4.4 修改整体聚合器只用 `impact=runtime` 组件计算 `wired/partially_wired/blocked`，保留 Workflow 等已声明未执行的同步组件对整体状态的降级
- [x] 4.5 更新激活预检、运行状态 reason code 和 API schema，保证 retention 治理警告不阻止激活且不被误报为已执行
- [x] 4.6 扩展运行记录管理 API，返回 Job 的 requested/effective 策略、来源 Publication、实际工具调用数和策略耗尽字段
- [x] 4.7 增加状态矩阵契约测试，覆盖“执行策略已接线且仅retention缺失时wired”“Workflow未执行时partially_wired”“Publication策略schema不支持时partially_wired/blocked”和 Worker 遇到非法 Job 快照时失败关闭

## 5. 管理Web展示

- [x] 5.1 扩展前端业务应用与运行记录 domain schema，解析组件 `impact`、Execution Policy 逐字段状态和 Job requested/effective 策略
- [x] 5.2 将总状态文案明确为“运行接管”，把 `retention_days` 单独展示为非阻塞“治理提示”，禁止显示已执行清理
- [x] 5.3 在应用详情展示 Execution Policy 请求值、有效值及被 Agent Publication 收紧的原因，不让前端自行计算有效策略
- [x] 5.4 在 Agent 运行记录展示固定策略来源、三个有效限制、实际工具调用数和策略耗尽错误
- [x] 5.5 增加前端组件测试，覆盖 wired 加治理提示、真正 partially_wired、请求值与有效值差异、零工具预算和错误码显示

## 6. 迁移、文档与端到端验证

- [x] 6.1 更新 OpenAPI/管理 API 示例、运行状态说明和运维文档，明确限制按单 attempt 执行、timeout retry 语义以及 retention 不在本变更中执行
- [x] 6.2 编写维护窗口 Runbook，明确停止 API/Ingress/Worker、输出删除清单、清理 MinIO、执行一次性破坏性维护命令并完成 schema 约束、校验保留控制面数据和恢复服务的顺序
- [x] 6.3 在带旧 Job、消息、工具调用、投递、附件、Webhook 事件和审计的数据库副本上运行清理/迁移测试，证明运行数据被删除、对象无残留且用户/身份/Agent/业务应用/Publication/Deployment/Connector 均保留
- [x] 6.4 验证迁移后的 `execution_policy_json` 为 `NOT NULL` 且无默认值，旧版本 API 无法继续创建 Job，所有新入口都必须显式写入 v1 快照
- [x] 6.5 运行完整后端测试，覆盖 business application routing、全部 Job 创建入口、job/worker、Claude client、retry、failure delivery、管理 API 和安全审计
- [x] 6.6 运行前端 lint、typecheck、全量测试和生产构建，修复所有新增契约不一致
- [x] 6.7 在维护窗口内以同一提交重建 `api-server`、`agent-worker`、`dingtalk-stream-ingress`、Webhook/Attachment Worker 和 `admin-web`，验证没有新旧版本混跑且无新增 Feature Flag
- [x] 6.8 使用保留的默认诊断应用、用户身份和 Connector 创建全新 local Job，核对 v1 requested/effective 策略、Worker实际限制、运行记录和原会话投递
- [x] 6.9 使用确定性 fake Agent 触发超过 `max_tool_calls` 的真实 Job/Worker 流程，证明多余调用未到达 ToolRegistry、失败不瞬时重试且安全错误进入 Delivery
- [x] 6.10 验证默认诊断应用在 Trigger、Agent、Session、Execution Policy、Delivery 全部接线且仅 retention 未执行时显示 `wired`，同时仍显示 `retention_days=stored_only`
- [x] 6.11 检查代码、Compose、队列声明和任务入口，确认除一次性旧测试数据迁移外没有新增 retention 清理 Worker、定时任务、消息删除或附件删除逻辑
- [x] 6.12 运行 `openspec validate enforce-business-application-execution-policy --strict` 并保存最终验证结果
