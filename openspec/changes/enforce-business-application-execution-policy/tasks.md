## 1. 执行策略领域模型与持久化

- [ ] 1.1 新增下一顺序幂等 migration，为 `agent_job` 增加默认空 JSON 的 `business_application_execution_policy_json`，补充列注释并验证现有数据库升级
- [ ] 1.2 新增版本化的业务应用 Job Execution Policy 值对象，严格解析 `requested`、`effective`、`sources` 和 `schema_version`，空 JSON 保持兼容路径
- [ ] 1.3 实现纯领域 `EffectiveExecutionPolicyResolver`，对 `max_turns`、`timeout_seconds` 取业务应用与固定 Agent Publication 的更严格值，对 `max_tool_calls` 使用规范化应用值
- [ ] 1.4 为缺失 Agent 值、业务应用更严格、更宽松、`max_tool_calls=0`、边界值和非法快照补齐领域单元测试
- [ ] 1.5 扩展 `AgentJob`、`CreateAgentJobCommand`、PostgreSQL 仓储创建/读取/运行记录投影以保存和返回固定策略，确保日志与审计不写入敏感内容
- [ ] 1.6 增加仓储兼容测试，证明旧行空 JSON、新行完整快照、重复消息幂等和 Job 重读均保持正确

## 2. 入口固定策略与Job provenance

- [ ] 2.1 在 `ChannelIngressService` 命中 Business Application route 后读取固定 Publication 的 `execution_policy` 并传给 Job 创建命令
- [ ] 2.2 在 `CreateAgentJobService` 完成 Agent Publication revision/hash 校验后计算有效策略，并在创建 Session、Job、用户消息的既有事务中持久化
- [ ] 2.3 确保 RabbitMQ payload 仍只包含 `job_id`、`correlation_id`，Worker 不从消息体接收策略 JSON
- [ ] 2.4 增加路由集成测试，证明请求值与有效值、应用/Agent Publication 来源、config hash 和 route provenance 同时固定
- [ ] 2.5 增加发布、激活、回退和重试测试，证明已入队 Job 不重新读取当前 Deployment，新 Job 才使用新策略
- [ ] 2.6 增加旧 Job、调试入口和非业务应用入口兼容测试，证明没有业务应用策略时沿用 Agent Publication/运行时默认值

## 3. Worker与Agent运行时强制执行

- [ ] 3.1 扩展 `AgentExecutionContext` 和上下文构建器，从 Job 固定快照提供有效 `max_turns`、`timeout_seconds`、`max_tool_calls`，不得从活动应用重新解析
- [ ] 3.2 保持 Agent Publication 作为兼容 Job 的限制来源，并补齐业务应用策略只收紧、不放宽 Agent 限制的测试
- [ ] 3.3 实现单 attempt 共享的 `ToolCallBudget`，在每个内部 MCP handler 调用 `ToolRegistry` 前计数成功或失败的调用尝试
- [ ] 3.4 实现专用策略耗尽异常和 `execution_policy_max_tool_calls_exhausted` 稳定错误码，保证超过上限的调用不进入 ToolRegistry 或下游数据源
- [ ] 3.5 将有效 `max_turns` 传给 Claude SDK options，将有效 `timeout_seconds` 用于 SDK session 墙钟超时，并保留现有兼容默认值
- [ ] 3.6 在真实 Claude、Stub runtime 和 fake SDK 测试夹具中统一执行策略契约，覆盖零工具预算、恰好达到上限、超过上限、失败调用计数、最大轮次和 timeout
- [ ] 3.7 确保最大工具调用和最大轮次耗尽不进入普通 transient retry，timeout 保持现有 retry 分类且每次 attempt 复用同一固定策略
- [ ] 3.8 确保策略耗尽前的工具事件由 `AgentExecutor` 持久化，Job step、失败原因、审计和原钉钉会话失败 Delivery 使用安全摘要
- [ ] 3.9 增加并发/重复 RabbitMQ delivery 测试，证明现有 Job claim 幂等仍阻止同一 Job 同时执行和重复发送失败通知

## 4. 运行时就绪判定与管理API

- [ ] 4.1 为 `RuntimeComponentStatus` 增加服务端返回的 `impact=runtime|governance`，所有列表、详情、Publication、Deployment、effective 和审计投影复用统一模型
- [ ] 4.2 将现有 Session 组件拆分为已接线的 `session_policy` 和非阻塞 `retention_policy`，后者保持 `retention_days=stored_only` 与稳定 reason code
- [ ] 4.3 将 Execution Policy 组件改为逐字段报告 `max_turns= wired`、`timeout_seconds=wired`、`max_tool_calls=wired`，仅在 Worker 确实支持策略 schema 时标记已接线
- [ ] 4.4 修改整体聚合器只用 `impact=runtime` 组件计算 `wired/partially_wired/blocked`，保留 Workflow 等已声明未执行的同步组件对整体状态的降级
- [ ] 4.5 更新激活预检、运行状态 reason code 和 API schema，保证 retention 治理警告不阻止激活且不被误报为已执行
- [ ] 4.6 扩展运行记录管理 API，返回 Job 的 requested/effective 策略、来源 Publication、实际工具调用数和策略耗尽字段
- [ ] 4.7 增加状态矩阵契约测试，覆盖“执行策略已接线且仅retention缺失时wired”“Workflow未执行时partially_wired”“策略schema不支持时partially_wired/blocked”及旧数据兼容

## 5. 管理Web展示

- [ ] 5.1 扩展前端业务应用与运行记录 domain schema，解析组件 `impact`、Execution Policy 逐字段状态和 Job requested/effective 策略
- [ ] 5.2 将总状态文案明确为“运行接管”，把 `retention_days` 单独展示为非阻塞“治理提示”，禁止显示已执行清理
- [ ] 5.3 在应用详情展示 Execution Policy 请求值、有效值及被 Agent Publication 收紧的原因，不让前端自行计算有效策略
- [ ] 5.4 在 Agent 运行记录展示固定策略来源、三个有效限制、实际工具调用数和策略耗尽错误
- [ ] 5.5 增加前端组件测试，覆盖 wired 加治理提示、真正 partially_wired、请求值与有效值差异、零工具预算和错误码显示

## 6. 迁移、文档与端到端验证

- [ ] 6.1 更新 OpenAPI/管理 API 示例、运行状态说明和运维文档，明确限制按单 attempt 执行、timeout retry 语义以及 retention 不在本变更中执行
- [ ] 6.2 运行 migration 幂等与升级测试，证明已有 Job、活动 Publication、Session、投递和审计数据不被重写或删除
- [ ] 6.3 运行完整后端测试，覆盖 business application routing、job/worker、Claude client、retry、failure delivery、管理 API 和安全审计
- [ ] 6.4 运行前端 lint、typecheck、全量测试和生产构建，修复所有新增契约不一致
- [ ] 6.5 重建 `api-server`、`agent-worker`、`dingtalk-stream-ingress` 和 `admin-web`，验证共享 PostgreSQL/RabbitMQ 装配正常且无新增 Feature Flag
- [ ] 6.6 在 Compose 中发布并激活一个带策略的 local 应用，创建 Job 后核对固定 requested/effective 策略、Worker实际限制、运行记录和原会话投递
- [ ] 6.7 使用确定性 fake Agent 触发超过 `max_tool_calls` 的真实 Job/Worker 流程，证明多余调用未到达 ToolRegistry、失败不瞬时重试且安全错误进入 Delivery
- [ ] 6.8 验证默认诊断应用在 Trigger、Agent、Session、Execution Policy、Delivery 全部接线且仅 retention 未执行时显示 `wired`，同时仍显示 `retention_days=stored_only`
- [ ] 6.9 检查代码、Compose、队列声明和任务入口，确认本变更没有新增 retention 清理 Worker、定时任务、消息删除或附件删除逻辑
- [ ] 6.10 运行 `openspec validate enforce-business-application-execution-policy --strict` 并保存最终验证结果
