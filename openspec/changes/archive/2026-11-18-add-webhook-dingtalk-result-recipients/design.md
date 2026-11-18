## Context

现有 `delivery` 是单一 ReplyRoute；Delivery Outbox 的 `(job_id, result_artifact_id)` 唯一键阻止同一结果产生多个独立投递。ChannelIngressService 对 Webhook 会用业务应用单一 target_reference 覆盖 Trigger 发布配置。Stream Connector 只允许普通 ingress；受管机器人凭据已经存在，不能要求用户复制凭据建立影子机器人。停用定义无条件调用 require_ingress，导致入口不可用时无法停用。

## Goals / Non-Goals

**Goals:** Web 管理多个钉钉群/用户接收人；发送 Agent 完成结果和现有安全失败通知；逐目标重试、幂等和查询；显式发布和授权；可靠停用；部署页面更新可见。

**Non-Goals:** 收到即转发、全企业通讯录同步、任意 HTTP URL、跨企业身份转换、文件多目标发送、停用时取消正在运行的任务、真实钉钉群或用户验收。

## Decisions

1. Webhook `delivery.type=dingtalk_recipients`，`target.recipients` 为 1–20 行列表，每行包含 `connector_id`、`kind=group|user`、`target_id` 和可选备注 `label`。群填写 openConversationId，用户填写该机器人企业内 userId；同机器人、类型、目标 ID 去重。UI 提供机器人下拉、类型选择、目标 ID、备注及增删行，不要求编辑 JSON。不引入通讯录同步或可变全员选择。
2. 新投递路线仅用于受管钉钉应用机器人，目录通过派生 `supports_robot_delivery` 能力展示；Agent Publication 仍必须显式分配该机器人为 delivery。普通 require_delivery 继续拒绝 Stream Connector；主动结果使用独立受限校验，确认启用应用、已验证企业、有效凭据和 robotCode，固定钉钉官方 endpoint。
3. 继续使用 typed ReplyRoute；多接收人作为有界聚合路线冻结到 Trigger Publication 和 Job。发送前从冻结列表按稳定 recipient key 选择目标，外部 Webhook payload 不允许设置接收人。群与用户使用群消息和机器人单聊 API；每次用户调用只含一个 userId，非空 invalid/flow-controlled 列表必须判为失败，避免批量部分失败被当作成功。
4. 一个结果为每个接收人创建独立 Outbox 行，新增 recipient_key，唯一约束为 `(job_id, result_artifact_id, recipient_key)`，稳定 event_key 同样包含 recipient key。原单目标使用空 key。沿用现有 claim、attempt、chunk、有限重试和人工 replay；同事务创建全部行。一个目标失败不会阻止其他目标，也不会重新运行 Agent。返回首个 Delivery ID 保持现有只用于追踪的内部调用合同。
5. 业务应用增加 `webhook_result` 绑定，明确授权使用绑定 Webhook 发布的结果配置，Connector 指向该 Webhook 入口。命中后保留事件冻结的 ReplyRoute，并要求其 Agent Publication 与业务应用一致；不从应用再次填写目标，不回退其他路由。原单目标应用绑定行为保留，不隐式改写已有发布。
6. 停用只要求动作权限和正确 revision，不依赖入口或凭据健康；不得借停用更换为无效 Connector。卡片可直接停用；配置面板存在未保存编辑时也能停用，编辑保留。启用继续要求已发布和入口可用。停用沿用当前入站/Dispatcher 门禁：拒绝新请求，尚未创建 Job 的事件不继续执行，已创建的 Job 和 Delivery 继续沿用冻结结果路线。
7. 管理 HTML 返回 no-store，带内容哈希的静态资产正常按文件存在性提供，不为缺失 JS 返回 index.html。重新加载获取当前 bundle；不新增轮询重载或自动丢弃未保存表单。
8. 验收分层：配置/权限/停止回归，Outbox 多目标并发与部分失败恢复，PostgreSQL/SQLite 迁移，实际 Chromium 合成页面，Compose 部署及缓存响应。真实群消息需另有明确接收人和授权，本轮使用假传输并记录边界。

## Risks / Trade-offs

- 钉钉受理不等于用户已阅读；HTTP 200 的业务错误和无效/限流用户列表必须识别。外部成功后进程崩溃仍存在远端无幂等保障的重复窗口，不承诺端到端 exactly-once。
- 人工填写稳定 ID 可能无效；页面说明类型和企业范围，提供备注；真实可达性由投递结果反馈，不以静态校验伪称可达。
- 发布或停用机器人会影响后续投递；每次发送重查机器人可用性，保持现有凭据轮换机制。

## Migration Plan

迁移 148 增加 Outbox recipient_key 并替换唯一约束；迁移 149 扩展业务应用投递类型约束，接受 webhook_result。SQLite 按现有迁移模式重建原表并复制列，PostgreSQL 原位修改，保留现有事实和引用。先运行迁移，再同时更新 API 与 Delivery Worker、Web。回滚代码前须停用新多目标定义并排空对应 Outbox，不让旧 Worker 处理新路由。

## Open Questions

无阻塞项。用户已确认发送 Agent 执行结果。停用保持当前门禁含义；同时取消已运行任务属于额外需求，当前不扩展。
