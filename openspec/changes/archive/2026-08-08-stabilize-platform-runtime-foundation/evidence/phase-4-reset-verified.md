# Phase 4 实际资源重置 APPLIED/VERIFIED 证据

记录日期：2026-07-29

## 用户确认与操作结果

用户明确确认了以下同一份操作和摘要：

- operation ID：
  `resource_reset_b6a2fbfbc4934740b2b3de880097eb6f`
- manifest digest：
  `0cd4d4f41e6f75f6b357690d5d9159eff4c03be1f9533237a3b5f5598a62f966`

执行前再次验证：

- operation status 为 `PREPARED`
- 25 个目标未变化
- DB 11、Redis 10、Loki 4
- 19 个 Agent Job 全部为 `SUCCEEDED`
- 迁移后备份 SHA-256 仍为
  `a97445211d1fcf0e2d712d406e0f9145ba3a843cc2bd855c9292420508268b5a`

`resource-reset apply` 在单事务内完成：

```text
status=APPLIED
affected_rows=25
```

随后 `resource-reset verify` 完成，operation 最终状态为 `VERIFIED`，25 个
target 的 `apply_status` 全部为 `APPLIED`。

## 空资源验证

以下实际计数均为 0：

- 旧 `platform_resource_binding` 中的 DB/Redis/Loki
- Resource Identity、Draft、Verification、Revision
- Application Resource Binding
- Handler Resource Binding
- Resource Activation
- Resource Runtime State

重置创建了一个 `ACTIVE` 的空 Runtime Generation：

```text
resource_count=0
application_count=0
snapshot_digest_length=64
```

删除后的 `resource-reset report` 返回：

```text
counts={}
targets=[]
resources=[]
legacy_bindings=[]
runtime status=READY
```

本地证据文件：

- `/private/tmp/enterprise-agent-reset-20260728T234226Z/resource-reset-verify.json`
  - SHA-256：
    `6e8d2d14fa85c57c32f970e887f8be5367f1af72066bdc0e06aa9d2a723526e1`
- `/private/tmp/enterprise-agent-reset-20260728T234226Z/resource-reset-post-report.json`
  - SHA-256：
    `6e107b86646cffc298dcda164855fe5697ecc7c2e77b3cb4f772dc2ea3072e4b`

文件权限均为 `0600`。

## 保护对象验证

| 类别 | reset 前 | verify 后 | 结果 |
|---|---:|---:|---|
| platform Secret | 3 | 3 | 保留 |
| app user | 7 | 7 | 保留 |
| RBAC role | 3 | 3 | 保留 |
| RBAC user-role | 7 | 7 | 保留 |
| business application | 2 | 2 | 保留 |
| business application publication | 9 | 9 | 保留 |
| Agent Job | 19 | 19 | 保留 |
| Delivery Outbox | 1 | 1 | 保留 |
| platform environment | 4 | 4 | 保留 |
| platform base | 11 | 11 | 保留 |
| platform workshop | 16 | 16 | 保留 |
| Audit Event | 1362 | 1364 | 仅按操作单调增加 |
| Runtime Generation | 0 | 1 | 新增空 Generation |

正式 verify 的全部布尔检查均为 `true`，包括资源为空、无悬空 binding、受影响
应用状态正确、保护对象精确或单调保留、历史 Generation 保留。

## 回归与当前运行态

```text
Phase 4 focused: 29 passed
backend full: 648 passed, 20 skipped, 2 warnings, 4 subtests passed
Ruff: passed
API /api/health: HTTP 200
API /api/ready: HTTP 200
Internal API /health: HTTP 200
Internal API /ready: HTTP 200
Compose containers: healthy
```

真实 Oracle 11.2.0.4 连接仍按既定决策 deferred；本机没有 Oracle，未声称真实
Oracle 连接已通过。

## Internal API 空运行时切换

用户授权清除旧 Internal API 进程缓存。仅重启旧镜像时，schema 安全门禁发现
该镜像只认识 migration 021，而数据库已到 023，因此正确拒绝启动。经再次
获得用户授权后：

1. 从停止容器复制既有 Internal API Token 到 `0600` 临时文件，全程未读取或
   输出内容。
2. 构建并仅重建 023 兼容的 `internal-api-platform`。
3. 首次 readiness 发现启动路径未把已挂载 Master Key 加载到 readiness 使用的
   Settings；补充 `load_master_key_settings()`、回归测试并再次构建。
4. 验证 `/health` 和 `/ready` 均为 HTTP 200，schema head 为 023，
   `master_key=true`、`internal_api_token=true`、`resource_count=0`、
   `degraded=false`，Generation 1 生效。
5. 未认证工具请求返回 HTTP 401；API 和其他 Worker 未重启。
6. 临时 Token、恢复脚本和临时目录均已删除。

新增启动回归与相关聚焦测试为 `18 passed`。全量套件第一次运行遇到一个既有
SQLite Delivery Dispatcher 并发用例的单次时序失败；该用例随后连续 11 次
通过，第二次全量套件 648 个测试全部通过。
