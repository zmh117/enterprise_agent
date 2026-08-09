# MCP 基线验收记录（2026-08-09）

## 结论

本轮结论为 **未通过最终生产门禁**。可在本地自动完成的破坏性切换、Resource Runtime、MCP 协议、失败关闭、轻量门户和静态回归已经完成；正式 MCP Tool Publication 写路径、真实 Claude/ONES/钉钉链路及拒绝审计仍不完整，因此任务 10.2–10.7 保持未完成。

## 已确认事实

- 在独立 PostgreSQL 18、RabbitMQ 4、Redis 7.4、Loki 3.5.2 和 MinIO 环境执行不可恢复切换；检查识别 81/81 个旧表和 4/4 个旧列，清理后 `cutover verify` 返回 `verified=true`、旧表/列为空、旧凭据/Challenge 为 0、旧历史不可查询。
- 迁移器到达 schema head 036；常规 API 已恢复 `enterprise_agent_api` 最小权限身份，破坏模式恢复为 `false`。
- 从空状态通过 `platformctl` 创建加密 Secret，并完成 PostgreSQL、Redis、Loki Resource 的 `plan → apply → verify → publish`；三个 Deployment 最终均为 ACTIVE generation。
- Redis Resource 已实际执行取消发布、从历史 Revision 建 Draft、重新验证及重新发布。为支持内容相同但身份不同的新 Revision，新增迁移 036。
- 数据库 Secret 已执行成功轮换、随机无效密码轮换和有效密码恢复。无效密码生成 `provider_verification_failed`，精确同 Revision LKG 保持可用且状态为 DEGRADED；恢复后新 generation 原子切换为 ACTIVE，健康恢复 ready。
- 使用受控、验收后删除的 fixture，通过 MCP v2 客户端真实调用 PostgreSQL、Redis、Loki；通过 Agent Worker 的 MCP 1.x 客户端连接 MCP v2 Server 并真实读取 Redis。过期 Token 和禁用 Publication 均失败关闭。
- 完整 Compose 镜像重建成功；API、ONES MCP、Data MCP、钉钉 Runtime 和带健康检查的 Worker 均 healthy。Agent/Job/Webhook/Channel Worker 不挂载 Master Key，只有实际解密的 Delivery/Attachment Worker 挂载。
- Playwright 运行时检查确认：未认证显示登录页；登录后只保留本人 Job/会话历史、外部身份、密码与会话；MCP 调试只展示脱敏摘要；旧 `/applications` 与 `/platform/resources` 明确显示已退役页面；空状态钉钉 Challenge 可创建且未形成伪造外部身份。
- 最终 fixture 已清理；`active_publications=0`，三个 Resource 仍为 ACTIVE，`/api/ready`、两个 MCP 健康和门户 HTTP 均正常。零 Publication 是下述正式发布路径缺失的真实基线，不是验收通过证据。

## 自动回归

- Backend：287 passed，15 skipped；唯一警告为 Starlette TestClient 的 `httpx` → `httpx2` 迁移提示。
- Frontend：lint、typecheck、17 tests、production build 通过；仅保留单个 bundle 大于 500 kB 的构建警告。
- DingTalk Runtime：lint、typecheck、9 tests 通过。
- Ruff 全仓通过；Mypy 253 个 backend source 通过；OpenSpec strict 84 passed / 0 failed；`git diff --check` 通过。

## 阻断项

1. `mcp_tool_publication` 只有 schema、读取和运行时消费路径，没有受治理的创建/更新入口；`platformctl mcp tools/status` 也是只读。空库无法通过正式操作产生 Agent/Application 的 MCP Tool Publication，因此不能创建真实精确 allowlist Job。
2. 当前环境没有真实 Claude 模型凭据、ONES 用户重新验证凭据和真实钉钉 App/用户事件，不能把受控协议 probe 记为 Agent/ONES/渠道 E2E。
3. 过期 Token 与禁用 Publication 会失败关闭，但本轮真实 probe 没有产生 `DENIED` provenance；安全拒绝审计仍需补齐并验证。
4. ONES 401/403、Delivery retry 和 `Runtime → Inbox → Outbox → RabbitMQ → Job → Worker → MCP → Delivery` 尚未在真实外部链路完成。

## 生产门禁

任务 10.7 保持关闭。不得在生产执行不可恢复切换，直至上述阻断项解决并完成 10.2–10.6 的真实验收。
