# Phase 4 实际资源重置 PREPARED 证据

记录日期：2026-07-29

> 用户随后明确确认了本文记录的 operation ID 和 digest，`apply/verify`
> 已成功；结果见
> [phase-4-reset-verified.md](phase-4-reset-verified.md)。本文继续保留删除前
> 的精确确认基线。

## 已执行且未越过的边界

- 经用户明确确认，对实际 PostgreSQL 应用了 additive migration 022/023。
- Migrator 结果：
  `MIGRATION_SUCCEEDED: head=023 baselined=0 applied=022,023`。
- ledger 中 022/023 的 checksum 与仓库文件一致：
  - 022：
    `fc587f4cf3b7317baf97bed5cc3dbc1410dbb176187ef5d0a1fb073021faa2a7`
  - 023：
    `cc5f3692797611c62a9d47e1af09c5f76516da8eae88eb42d6989008f8da9cb0`
- 未重启任何现有 API、Internal API、Worker 或 DingTalk Runtime。
- 未读取、修改或删除任何平台 Secret。
- 已执行 `resource-reset report/prepare`，但没有执行 `apply` 或资源删除。

## 已验证备份

备份目录权限为 `0700`，文件权限为 `0600`。

| 时点 | 路径 | 大小 | SHA-256 |
|---|---|---:|---|
| migration 022/023 前 | `/private/tmp/enterprise-agent-reset-20260728T234226Z/pre-022-023.dump` | 601377 bytes | `2de062157a83c6ef2468270c743bf4461cc9bf2506836cfcd8b63c89706a49dc` |
| migration 023 后、reset 前 | `/private/tmp/enterprise-agent-reset-20260728T234226Z/post-023-pre-resource-reset.dump` | 678653 bytes | `a97445211d1fcf0e2d712d406e0f9145ba3a843cc2bd855c9292420508268b5a` |

两份备份均使用 PostgreSQL custom format，并在容器内通过
`pg_restore --list`。迁移后备份复制前后的 SHA-256 完全一致。

## report 与 prepare

- report 文件：
  `/private/tmp/enterprise-agent-reset-20260728T234226Z/resource-reset-report.json`
- prepare 文件：
  `/private/tmp/enterprise-agent-reset-20260728T234226Z/resource-reset-prepare.json`
- operation ID：
  `resource_reset_b6a2fbfbc4934740b2b3de880097eb6f`
- operation status：`PREPARED`
- database fingerprint：
  `a6074da128d7b226a98f2f2f92992bbb89b3cdffde028ec0e8922a2217ee09bc`
- manifest digest：
  `0cd4d4f41e6f75f6b357690d5d9159eff4c03be1f9533237a3b5f5598a62f966`
- backup reference 指向上表迁移后备份及其 SHA-256。

精确目标共 25 条，全部为现有 `platform_resource_binding` 中的
`legacy_binding`，动作均为 `DELETE`。目标 ID、code 和 revision 与
[迁移前精确清单](phase-4-actual-reset-preflight.md#旧资源精确清单)
完全一致：

- DB：11
- Redis：10
- Loki：4
- 新 governed Resource/Draft/Revision：0
- 应用资源 binding：0
- Handler 资源 binding：0
- activation/runtime state：0
- 活动资源 Job：0
- 受影响应用：0

## 明确保留的实际计数

`prepare` 记录的保护对象基线：

| 类别 | 数量 |
|---|---:|
| platform Secret | 3 |
| app user | 7 |
| RBAC role | 3 |
| RBAC user-role | 7 |
| business application | 2 |
| business application publication | 9 |
| Agent Job | 19 |
| Delivery Outbox | 1 |
| Audit Event | 1362 |
| platform environment | 4 |
| platform base | 11 |
| platform workshop | 16 |

Job Execution Scope/Binding、Handler Installation/Publication 和历史 Runtime
Generation 当前均为 0，也属于 verify 必须保留或按定义单调增加的类别。

## 摘要 Gate 与停点

实际 CLI 的 `prepare --output` 生成 `{digest, manifest}` 包装对象。首次运行
Gate 发现它只接受裸 manifest，因此补充了包装对象兼容和内嵌 digest 一致性
校验；回归测试 `12 passed`，Ruff 和 `git diff --check` 均通过。

修复后：

- `manifest-digest` 重算出
  `0cd4d4f41e6f75f6b357690d5d9159eff4c03be1f9533237a3b5f5598a62f966`。
- `destructive-preflight` 对同一 operation 和 digest 输出
  `USER_CONFIRMATION_REQUIRED`，并按设计以退出码 3 停止。
- 数据库复核为 `25 targets | 25 resources | 3 Secrets | 2 applications |
  19 Jobs`。

由于现有业务容器仍是迁移前的旧镜像，它们不会主动识别新的维护状态。在用户
确认 `apply` 前不得新增/编辑资源或启动调试 Job；即使发生并发漂移，`apply`
仍会重新 report 并拒绝不匹配的 operation/digest。

当前严格停在第二次用户确认边界。只有用户明确确认上述 operation ID 与
manifest digest 后，才允许执行 `resource-reset apply` 和 `verify`。
