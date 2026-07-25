# 后端阶段验收记录

验收日期：2026-07-25

## 已通过

- SQLite 迁移和 Managed Channel 契约测试通过。
- PostgreSQL 18 实例已应用迁移，并可读取 Runtime 状态。
- Backend 全量测试：`362 passed, 12 skipped, 4 subtests passed`。
- Ruff：通过。
- 本变更 Backend mypy：通过；全仓仅保留 8 个与本变更无关的既有错误。
- TypeScript Runtime：test、lint、typecheck、build 全部通过。
- Runtime 重启遇到旧租约交接窗口后，已增加有界租约等待；重建后 13 秒内恢复
  healthy 并重新建立 Stream WebSocket。
- Fake SDK 验证单个 Client 的启动、停用、重建和失败不影响其他 Client。
- Connector 级幂等、Inbox/Outbox 同事务、RabbitMQ 故障恢复和安全队列载荷通过。
- `docker compose config --quiet`、新镜像构建和服务健康检查通过。
- 旧 Python `dingtalk-stream-ingress` 已停止并从 Compose 默认拓扑移除。
- 现有真实钉钉 Connector 已由新 Runtime 建立 WebSocket，控制面如实显示
  `CONNECTED`；SDK 尚未上报 registered，因此没有误报为 `READY`。

## 明确未执行

- 当前只有一套真实钉钉凭据，无法执行“双真实机器人同时 READY、分别收消息”
  验收。该项保留为未执行，不以 fake 测试冒充真实验收。
- 为避免中断当前真实钉钉入口，没有在浏览器中停用现有 Channel，也没有用无效
  凭据创建假机器人冒充 STARTING/READY 验收。

## 前端与浏览器证据

- Frontend：`27 passed`，lint 和 production build 通过。
- 浏览器已验证应用详情存在“渠道与触发器”页，能展示钉钉与 Webhook、安全运行
  状态、最近消息和最近错误。
- 浏览器已验证钉钉编辑抽屉不回显 Client Secret，并明确“留空表示不修改”。
- 浏览器已验证私聊和群聊 Trigger 只通过 eligible Channel 选择器选择当前可用的
  钉钉应用机器人，不再使用自由 Connector 输入。
