## 1. 运行时状态模型与数据迁移

- [x] 1.1 新增统一的 RuntimeReadiness、RuntimeComponentStatus、RuntimeRouteResolution 领域值对象和稳定 reason code，覆盖 `matched/not_matched/blocked` 与 `not_wired/partially_wired/wired/blocked`
- [x] 1.2 实现 `RuntimeReadinessEvaluator`，集中计算数据面闸门、当前 `APP_ENV`、Trigger、Agent、Session、Delivery、Execution、Workflow 和 Capability 的逐组件状态
- [x] 1.3 删除 Business Application service、controller、snapshot summary 和 audit 中硬编码的 `runtime_wired`，统一使用 evaluator 结果
- [x] 1.4 增加 agent_job 业务应用 provenance 可空字段、路由决策摘要字段和 application/publication/deployment 查询索引
- [x] 1.5 更新 Job 领域模型、Repository 映射、Admin DTO 和历史记录展示，使旧 Job 返回 `legacy_unattributed` 而不猜测回填
- [x] 1.6 增加并验证向前兼容和回滚安全的数据库迁移，确保现有 Job、Session、Delivery 和 Worker 查询不受空字段影响

## 2. Resolver与部署环境边界

- [x] 2.1 修改 Channel runtime 解析入口，只使用 Bootstrap 注入的 `settings.environment`/`APP_ENV` 选择 Business Application Deployment
- [x] 2.2 保持 `ChannelEvent.routing.environment` 仅作为数据库、Redis、Loki 等业务数据范围写入 Job，不再传给 Business Application Resolver
- [x] 2.3 将 `resolve_trigger_optional` 的含糊返回替换或封装为三态 `RuntimeRouteResolution`，明确区分无匹配和命中后完整性失败
- [x] 2.4 在 Resolver 返回中加入 application、Publication、Deployment、route 标识与经 evaluator 计算的组件状态，不返回 Secret 或完整敏感路由值
- [x] 2.5 为数据面闸门关闭、非当前 Deployment 环境、route 不存在、旧路由键、hash 错误、schema 不支持和组件缺失实现稳定 reason code
- [x] 2.6 增加部署环境与业务数据环境分离测试，覆盖 `APP_ENV=local + routing.environment=sanjiu`、只激活 test 及合法 local 路由

## 3. 钉钉Stream路由键

- [x] 3.1 在钉钉 Stream 适配器中从受信 payload 解析 robotCode/bot identity，并在 Connector 配置中提供受控固定身份回退
- [x] 3.2 为私聊生成 `bot:<normalized_bot_identity>` 路由键，禁止使用用户 ID、私聊 conversation ID、消息正文或可伪造 routing context
- [x] 3.3 为群聊生成 `conversation:<normalized_conversation_id>` 路由键并保持当前消息发送人作为统一身份与 RBAC 主体
- [x] 3.4 在发布/激活预检中校验 Trigger type、`CURRENT_SENDER` actor policy、connector 方向和路由键命名空间
- [x] 3.5 将现有 `default` 等无命名空间路由报告为 `blocked/legacy_routing_key`，不自动改写已发布 Publication 或猜测 bot/group 归属
- [x] 3.6 增加私聊多用户共享 bot route、同 bot 多群分流、缺少 bot identity、群聊缺少 conversation ID 和非法旧路由键测试
- [x] 3.7 验证路由计算不改变钉钉 Stream 快速 ACK、重复投递幂等、附件规范化和统一身份解析顺序

## 4. Channel入口与Job版本固定

- [x] 4.1 在 Channel ingress 的身份解析之后、Job 创建之前接入三态业务应用路由，并为每个结果记录关联 correlation ID 的审计
- [x] 4.2 对 `not_matched` 停止 Job 创建和 MQ 发布，记录 `route.not_matched` 并向钉钉原会话发送安全配置错误
- [x] 4.3 对 `blocked` 停止 Job 创建和 MQ 发布，调用现有 Channel 拒绝通知能力且禁止回退其他应用或默认 Agent
- [x] 4.4 命中应用时以 Application Publication 的 Agent ID、revision 和 hash 为最高优先级；一致的事件固定值可接受，不一致值返回 `agent_override_conflict`
- [x] 4.5 扩展 CreateAgentJobCommand 和 Job 创建事务，在消息、Session、Job 与 Outbox/MQ 发布前持久化完整应用 provenance 和安全路由摘要
- [x] 4.6 保持 RabbitMQ payload 最小化，只携带 Job 回读所需标识，禁止复制应用 snapshot、消息原文、session webhook 或 Secret
- [x] 4.7 修改 Worker 与执行重试路径只读取 Job 固定的 Agent Publication 和应用 provenance，不在消费或重试时重新解析 Deployment
- [x] 4.8 增加无匹配失败关闭、命中成功、命中损坏、事件 Agent 冲突、激活后旧 Job 不漂移和重复事件不创建第二 Job 的集成测试

## 5. 应用会话策略与隔离

- [x] 5.1 将稳定 business_application_id 纳入 Agent Session 复用键，同时保持 legacy Session 命名空间向后兼容
- [x] 5.2 按 `conversation_mode` 分别实现 channel、actor 和 application 会话主体选择，并确保不同应用不共享最近消息或摘要
- [x] 5.3 将 `recent_message_limit`、`continuous_conversation_enabled` 和 `attachments_enabled` 从固定 Application Publication 传入会话与上下文构建链路
- [x] 5.4 对尚未由清理任务执行的 `retention_days` 返回 `stored_only`，不得因保存了字段而显示为已生效
- [x] 5.5 增加同会话不同应用隔离、同应用跨 Publication 连续对话、最近消息上限和应用禁用附件测试

## 6. Delivery Binding运行时约束

- [x] 6.1 在激活预检和运行时匹配中要求钉钉 Trigger 具有唯一启用的 `reply_original` Delivery Binding
- [x] 6.2 校验 Delivery Binding connector 与 Stream ingress source connector 一致，并拒绝缺失、重复、不匹配或不支持的 Delivery
- [x] 6.3 将 Delivery Binding 作为授权策略应用到事件生成的 `dingtalk_stream_session_webhook` reply route，禁止应用草稿或模型覆盖临时目标
- [x] 6.4 确保 Publication、runtime status、审计和普通管理 API 不保存或返回完整 session webhook、Token 或敏感 URL
- [x] 6.5 保持 Delivery Worker 从 Job 使用固定 reply route；可重试投递只重试 Delivery，永久过期不得重跑 Agent 或改发未授权目标
- [x] 6.6 增加私聊和群聊回复原会话、connector 不匹配、Binding 缺失、webhook 过期、分片投递及投递失败不重跑 Agent 测试

## 7. 激活回退与管理API

- [x] 7.1 在激活、历史 Publication 回退和 effective 查询中运行统一预检，返回当前 `APP_ENV`、受影响 routes、整体状态、逐组件状态和兼容回退说明
- [x] 7.2 `local` 的受支持 Trigger 存在 blocked 组件时拒绝激活并保持原 Deployment；所有非 `local` 环境请求直接返回字段错误
- [x] 7.3 保持激活和 route 投影更新的事务性、乐观并发和冲突检查，并使重复激活保持幂等
- [x] 7.4 停用 Deployment 时原子移除 route 投影，明确后续消息失败关闭且已入队 Job 不受影响
- [x] 7.5 扩展应用列表、详情、Publication、Deployment、effective 和 Job API schema，移除前端只能接受 `runtime_wired=false` 的 literal 限制
- [x] 7.6 更新 OpenAPI/管理 API 契约测试，覆盖 wired、partially_wired、not_wired、blocked、非 local 环境拒绝和字段级预检错误

## 8. 管理Web运行状态与操作影响

- [x] 8.1 用服务端 RuntimeReadiness DTO 替换业务应用列表和详情中的固定 `runtime_wired=false` 文案与静态判断
- [x] 8.2 在应用列表和详情展示未接线、部分接线、已接线、已阻塞状态以及当前运行环境和逐组件原因
- [x] 8.3 在 Trigger 区域展示私聊 bot identity、群 conversation identity 和 connector 的安全摘要，并对旧 routing key 给出重新发布指引
- [x] 8.4 在激活、回退和停用确认界面展示将接管或释放的入口、未命中失败行为以及“已入队 Job 不切换版本”
- [x] 8.5 在运行记录和会话/Job 详情展示 Business Application、Publication、Deployment、route 和 legacy unattributed provenance
- [x] 8.6 增加前端 schema、查询、状态徽标、预检错误、确认流程、窄屏和基础无障碍测试，并验证缺失状态字段时不会默认显示已接管

## 9. 审计可观测性与安全

- [x] 9.1 增加 `route.matched`、`route.not_matched`、`route.blocked`、runtime activated/rolled_back/deactivated 审计事件和安全 payload
- [x] 9.2 用 correlation ID、external event ID、job ID、application code、Publication、Deployment 和 route 串联入口、执行与 Delivery 日志
- [x] 9.3 增加 matched、not_matched、blocked reason、Job 创建、Agent 结果和 Delivery 结果的指标或等效可查询统计
- [x] 9.4 增加审计脱敏测试，确保 bot/group 路由值按策略摘要化且任何 Secret、Token、完整 session webhook、原始 payload 和内部堆栈均不泄露
- [x] 9.5 验证统一身份和 RBAC 继续先于 Agent Job 创建生效，群聊权限按当前发送人而不是应用所有者或群共享主体计算

## 10. 自动化验证与真实运行验收

- [x] 10.1 运行 Business Application、Channel、DingTalk Stream、Job、Session、Delivery、身份/RBAC 和 Admin API 聚焦测试并修复全部回归
- [x] 10.2 运行完整后端 pytest、Ruff 和项目现有类型检查，记录通过数量与所有明确跳过项
- [x] 10.3 运行前端单元测试、lint/typecheck 和生产构建，确认 API schema 与页面状态一致
- [x] 10.4 运行 `openspec validate complete-business-application-runtime-routing --strict` 并修复所有 proposal、design、spec 和 tasks 结构问题
- [x] 10.5 在 Docker Compose 中先以数据面闸门关闭验证 `not_wired` 和失败关闭状态，再开启既有闸门验证接管切换
- [x] 10.6 使用当前 `APP_ENV` 创建明确 bot 私聊 route 和群 conversation route，发布、激活并通过真实或受控模拟 Stream 事件证明两类 Job provenance 正确
- [x] 10.7 验证 `routing.environment=sanjiu` 不再造成应用环境校验失败，并证明其仍能传递给只读数据库、Redis 或 Loki 工具范围
- [x] 10.8 验证无匹配和命中损坏配置均失败关闭并回复错误、重复事件不重复建 Job
- [x] 10.9 验证历史 Publication 回退、Deployment 停用、已入队 Job 版本不变、后续新事件切换及最终钉钉原会话回复
- [x] 10.10 从数据库与审计核对 application/Publication/Deployment/route/Job/Delivery 全链路证据，并在确认实际成功前不宣称运行时接管完成
