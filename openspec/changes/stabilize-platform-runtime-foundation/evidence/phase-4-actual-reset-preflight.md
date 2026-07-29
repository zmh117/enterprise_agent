# Phase 4 实际资源重置只读预检

记录日期：2026-07-28

> 本文件保留迁移前只读基线。经用户明确确认后，migration 022/023、
> 实际备份和 `resource-reset report/prepare` 已于 2026-07-29 完成；后续证据见
> [phase-4-reset-prepared.md](phase-4-reset-prepared.md)。实际删除尚未执行。

## 当前边界

- 实际 PostgreSQL migration head：
  `021_platform_secret_hardening.sql`
  (`f8f8aad4fb36e82faa93c0206a7ff4068beb46915ad8d83dbbe557c4ab1afff5`)。
- `platform_resource`、`runtime_snapshot_generation`、
  `resource_reset_operation` 均不存在；正式 `resource-reset prepare` 依赖尚未应用的
  migration 022/023，因此本文件只是只读预检，不是可执行 manifest。
- migration 022 checksum：
  `fc587f4cf3b7317baf97bed5cc3dbc1410dbb176187ef5d0a1fb073021faa2a7`。
- migration 023 checksum：
  `cc5f3692797611c62a9d47e1af09c5f76516da8eae88eb42d6989008f8da9cb0`。
- 现有 Compose PostgreSQL、RabbitMQ、API、Internal API、Worker/Dispatcher 均仍在
  运行；本次预检没有迁移数据库、重启服务、创建维护操作或修改 Secret。

## 旧资源精确清单

共 25 条旧 `platform_resource_binding`：

| 类型 | ID | code | revision |
|---|---|---|---:|
| database | `resource_d5a3e78cfe8b41459b7032a92f66e373` | `agent_test_mysql_database` | 5 |
| database | `resource_b39b7cbd55734871a56b958b0d9d9320` | `agent_test_sqlserver_database` | 5 |
| database | `resource_374e730781b842afbdc0c8cdb4a1c970` | `mmk_main_database` | 11 |
| database | `resource_5bc5ebed3f8c4891aa992f509b4ef09b` | `sanjiu_chenzhou_cloud_database` | 6 |
| database | `resource_6f69795b304347b994fa81cbb477fb0a` | `sanjiu_chenzhou_edge_database` | 6 |
| database | `resource_5014ef73537744e2ba125d777cbe7704` | `sanjiu_guanlan_cloud_database` | 6 |
| database | `resource_88fc48ccb4ba4a74b08a47e1511492ca` | `sanjiu_guanlan_database` | 5 |
| database | `resource_fccb4b7ee18e4f4c81ee661c7c3093e6` | `sanjiu_guanlan_edge_database` | 6 |
| database | `resource_c25e039660b3451580e4a72b973b4f28` | `sanjiu_shunfeng_cloud_database` | 6 |
| database | `resource_1c9e97122cc949318704a1c7b08a266c` | `sanjiu_shunfeng_edge_database` | 6 |
| database | `resource_65379709033d4acfa90a4a317074657d` | `xt_mes51_database` | 6 |
| redis | `resource_a9ad83f3fc4a41a5b50385dcd1a26c8a` | `agent_test_mysql_redis` | 5 |
| redis | `resource_b24d6bf90ea946b791182062ab111df1` | `agent_test_sqlserver_redis` | 5 |
| redis | `resource_7c7ba8bf356841a0a950361e19518070` | `mmk_main_redis` | 5 |
| redis | `resource_a6eccf42eb9a4ab98fef25b8e38f2b38` | `sanjiu_chenzhou_cloud_redis` | 6 |
| redis | `resource_3e24b2ce8da04d7e8e2c2ac28b52c388` | `sanjiu_chenzhou_edge_redis` | 6 |
| redis | `resource_5b08784217104c9d98339d5ec29172f8` | `sanjiu_guanlan_cloud_redis` | 6 |
| redis | `resource_82e8e7bcbea44e8c9c256fcccc73dacd` | `sanjiu_guanlan_edge_redis` | 6 |
| redis | `resource_a77395c1e0b14a8695621f60a2e0e81d` | `sanjiu_guanlan_redis` | 5 |
| redis | `resource_b3d6a7f32f9849c6aaed6d69c2557b45` | `sanjiu_shunfeng_cloud_redis` | 6 |
| redis | `resource_b03160120f4f4e3987855ae52ae580d9` | `sanjiu_shunfeng_edge_redis` | 6 |
| loki | `resource_632a84defc3649f88e819a7c54abd74d` | `agent_test_mysql_loki` | 3 |
| loki | `resource_7bc42ebc3986472b9d0c0b597a3864e4` | `agent_test_sqlserver_loki` | 3 |
| loki | `resource_1e788a6d482b409cae0f275b8b4bcc69` | `mmk_main_loki` | 5 |
| loki | `resource_edb1a2a28bbd446da96f6e3452428194` | `sanjiu_guanlan_loki` | 5 |

汇总：11 DB、10 Redis、4 Loki。

## 排空与保留对象

- Agent Job：19 个，全部 `SUCCEEDED`；当前没有
  `WAITING_INPUT/PENDING/RUNNING/RETRY_WAIT`。
- 平台 Secret：3 个，正式 reset 必须全部保留且不得读取、输出或改写明文/密文。
- 业务应用：2 个，正式 reset 必须保留；存在资源依赖的应用在 apply 后标为
  `BLOCKED`。
- 身份、新 RBAC、Handler、Job、Delivery、Audit、拓扑节点和历史 generation
  snapshot 均属于保留类别。

## 进入正式 prepare 的前置动作

1. 获得用户对“只应用 additive migration 022/023，不重启业务服务、不修改旧
   Secret”的明确同意。
2. 创建并验证实际 PostgreSQL 备份引用。
3. 运行正式 `resource-reset report/prepare`，生成新的 operation ID、数据库
   fingerprint、精确 target 和 SHA-256 digest。
4. 展示同一份 manifest 后再次等待用户确认；此前不得执行 `apply`。

## Phase 4 实现回归

```text
backend: 645 passed, 20 skipped, 2 warnings, 4 subtests passed
Phase 4 focused: 17 passed
frontend: 10 files passed, 45 tests passed
frontend lint: passed
frontend build: passed
ruff: All checks passed
docker compose config: passed
git diff --check: passed
OpenSpec strict validation: passed
```

已知非阻断告警仍是 Starlette `TestClient` 上游弃用提醒、一个既有 Pytest 测试函数
返回 `Settings` 的提醒，以及前端主 bundle 大于 500 kB。
