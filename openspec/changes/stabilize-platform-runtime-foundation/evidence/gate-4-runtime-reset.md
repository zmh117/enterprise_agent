# Gate 4：Oracle、热加载与受控资源重置

状态：**PASS**

记录日期：2026-07-29

## 已通过

- migration head 为 023，022/023 ledger checksum 与仓库一致。
- Oracle 11.2 contract、19c Thick Client 静态边界和禁止 Thin fallback 已有
  自动化验证；真实 Oracle 11.2.0.4 连接因本机无 Oracle 明确 deferred。
- Runtime Generation、原子 swap、每请求固定 generation、LKG、
  degraded/blocked 和 Secret 轮换回归通过。
- `/health` 与 `/ready` 分离及 schema/core dependency readiness 回归通过。
- 实际资源 reset 使用经过验证的备份、精确 operation ID、同一 digest 和用户
  二次确认。
- 25 个旧 DB/Redis/Loki binding 已单事务删除，正式 verify 全部通过。
- 删除后数据库资源和 binding 全部为空，存在一个 0 资源的 ACTIVE Generation。
- 3 个 Secret、身份、RBAC、2 个应用、19 个 Job、Delivery、审计和拓扑均按
  约束保留。
- Phase 4 固定回归：29 passed。
- 当前后端全量回归：
  `648 passed, 20 skipped, 2 warnings, 4 subtests passed`。
- 当前 `internal-api-platform` 使用 023 兼容镜像，`/health` 与 `/ready`
  均为 HTTP 200，schema 023、Master Key、Token 和 runtime assembly 就绪，
  `resource_count=0`、`degraded=false`。
- 未认证工具请求返回 HTTP 401，证明重建后的服务认证边界仍生效。

详细实际操作证据：

- [PREPARED 基线](phase-4-reset-prepared.md)
- [APPLIED/VERIFIED 结果](phase-4-reset-verified.md)

## 实际运行时恢复

旧 Internal API 镜像因 migration 021/023 不兼容而按 schema 门禁拒绝重启。
经用户再次确认，服务被单独构建、重建并切换到当前镜像。恢复过程中发现并修复
Internal API readiness 未加载已挂载 Master Key 的启动缺口；聚焦回归
`18 passed`，第二次后端全量回归全部通过。

恢复使用的临时 Token 文件始终为 `0600`，未读取或输出内容，并在验证后连同
一次性脚本和临时目录删除。其他 API/Worker 未重启。
