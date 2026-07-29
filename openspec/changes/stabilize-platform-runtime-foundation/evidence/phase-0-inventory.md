# Phase 0 身份、授权、资源与应用盘点

记录日期：2026-07-28  
记录范围：任务 1.3，只读盘点当前 PostgreSQL；未修改身份、授权、资源、
Secret 或业务应用。

## 脱敏边界与重跑方法

盘点脚本：
[`phase-0-inventory.sql`](./phase-0-inventory.sql)。

```bash
docker compose exec -T postgres sh -lc \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < openspec/changes/stabilize-platform-runtime-foundation/evidence/phase-0-inventory.sql

PYTHONPATH=backend .venv/bin/python -c \
  "from app.shared.config import load_settings; print(load_settings().identity.business_application_authorization_mode)"
```

脚本明确不查询：

- `password_hash`、`token_hash`、`csrf_hash`
- `ciphertext`、`nonce`
- `config_json`、`snapshot_json`、`metadata_json`

因此本文件仅保存 ID、code、引用、状态、版本和计数，不保存凭据值。

## 身份与新 RBAC

当前授权模式：`compatibility`。

| 项目 | 数量 |
|---|---:|
| 用户 | 7 |
| 角色 | 3 |
| 用户角色关系 | 7 |
| 管理能力 grant | 2 |
| 应用访问 grant | 2 |
| 应用能力 grant | 8 |
| 应用范围 grant | 7 |

角色：

| Role code | 状态 | 来源 | 保护 | Enabled member | Admin capability | App access |
|---|---|---|---:|---:|---:|---:|
| `authorization-browser-e2e-20260726` | enabled | custom | 0 | 1 | 2 | 1 |
| `e2e-readonly-diagnostic` | enabled | custom | 0 | 3 | 0 | 1 |
| `platform-admin` | enabled | system | 1 | 2 | 0 | 0 |

7 个身份由 `phase-0-inventory.sql` 按 username 输出。账户分布为 6 个人类账户
和 1 个服务账户；其中 5 个人类账户 enabled，1 个 disabled。

## 两名已登录验证的人类平台管理员

本次“已登录验证”采用当前可证明事实：人类账户 enabled、membership enabled、
密码凭据存在，并且至少存在一个 active session。不读取密码或 session token。

| User ID | Username | 账户 | Membership | 密码凭据 | Active session |
|---|---|---|---|---:|---:|
| `user_local_admin` | `local-user` | human/enabled | enabled | 是 | 是 |
| `user_1354ddf6d1e547faad514fec57a0a3fb` | `zmh` | human/enabled | enabled | 是 | 是 |

另有 `zmh2` 的 `platform-admin` membership 为 disabled，不计入管理员不变量。

结论：当前恰好有 2 名满足上述条件的人类平台管理员。后续修改用户、角色或管理员
关系时，必须在同一事务中保持不少于 2 名，不能依赖应用层先查后写。

## 旧授权库存

| 表 | Subject | Effect | 状态 | 数量 |
|---|---|---|---|---:|
| `permission_policy` | role | allow | enabled | 39 |
| `permission_policy` | user | allow | enabled | 15 |
| `platform_access_grant` | user | allow | enabled | 5 |

总计：

- `permission_policy`：54
- `platform_access_grant`：5

这些记录仍会被 `compatibility` 路径读取。Phase 1 在切换
`strict_application_role` 前必须证明新 RBAC 已覆盖需要保留的访问；本盘点不授权
删除它们。

## DB、Redis、Loki 资源

当前共有 25 个 enabled 资源：

| Kind | Engine | 数量 |
|---|---|---:|
| database | mysql | 3 |
| database | oracle | 6 |
| database | sqlserver | 2 |
| redis | - | 10 |
| loki | - | 4 |

Database codes：

- `agent_test_mysql_database`
- `agent_test_sqlserver_database`
- `mmk_main_database`
- `sanjiu_chenzhou_cloud_database`
- `sanjiu_chenzhou_edge_database`
- `sanjiu_guanlan_cloud_database`
- `sanjiu_guanlan_database`
- `sanjiu_guanlan_edge_database`
- `sanjiu_shunfeng_cloud_database`
- `sanjiu_shunfeng_edge_database`
- `xt_mes51_database`

Redis codes：

- `agent_test_mysql_redis`
- `agent_test_sqlserver_redis`
- `mmk_main_redis`
- `sanjiu_chenzhou_cloud_redis`
- `sanjiu_chenzhou_edge_redis`
- `sanjiu_guanlan_cloud_redis`
- `sanjiu_guanlan_edge_redis`
- `sanjiu_guanlan_redis`
- `sanjiu_shunfeng_cloud_redis`
- `sanjiu_shunfeng_edge_redis`

Loki codes：

- `agent_test_mysql_loki`
- `agent_test_sqlserver_loki`
- `mmk_main_loki`
- `sanjiu_guanlan_loki`

全部 25 个资源都带有 config 和 Secret 引用。完整 resource ID、scope、
environment/base/workshop、revision 由脱敏 SQL 输出。用户此前表达了“全部删除、
从空配置重新开始”的意图，但本阶段没有执行；到达破坏性任务前必须重新生成
digest、展示精确目标并再次确认。

## Secret 元数据

平台加密 Secret 共 3 个，均为 enabled `encrypted_db`，只保存
`secret://platform/...` 引用：

| Code | Ref | Active version | Version count |
|---|---|---:|---:|
| `123456789` | `secret://platform/123456789` | 1 | 1 |
| `deepseek_api_key` | `secret://platform/deepseek_api_key` | 10 | 10 |
| `dingtalk-dingb9feetjdec11m5wb-a7d92d77fa` | `secret://platform/dingtalk-dingb9feetjdec11m5wb-a7d92d77fa` | 3 | 3 |

资源 Secret reference registry 共 49 条：

- provider `secret`、enabled：48
- provider `env`、disabled：1（`env:ORDER_DB_PASSWORD` 示例）

48 条 enabled 引用全部使用 `secret://`；命名空间分布如下：

| Namespace | 数量 |
|---|---:|
| `secret://agent_test/...` | 13 |
| `secret://mmk/...` | 5 |
| `secret://sanjiu/...` | 27 |
| `secret://xt/...` | 3 |

完整 reference ID、code、ref、purpose、status、revision 由脱敏 SQL 导出。
本盘点没有读取平台 Secret 的 ciphertext/nonce，也没有解析任何 reference。

## 受影响业务应用

| Application | 状态 | Publication | Active deployment/route | 资源关联 |
|---|---|---:|---|---|
| `default-diagnostic-application` | enabled | 8，最新 revision 17 | local 1 个 deployment、3 个 route | 当前发布版本含 DB/Redis/Loki 诊断能力；RBAC scope 命中 8 个当前资源 |
| `assist01` | enabled | 1，revision 2 | 无 active deployment/route | RBAC scope 命中 3 个当前资源 |

`default-diagnostic-application` revision 17 当前启用：

- `query_database`
- `query_redis_get`
- `query_redis_scan`
- `query_loki`
- `diagnose_loki_labels`
- `diagnose_loki_label_values`
- `diagnose_loki_probe`
- `get_schema_directory`

因此删除全部 DB/Redis/Loki 不只是资源表清理：至少会影响两套应用授权 scope，
并使当前 active 的默认诊断应用失去工具资源。正式删除前必须连同引用、发布绑定、
运行中 Job/Session 和 Last Known Good 影响一起重新检查。

## 结论

- 新 RBAC 已存在，但运行时仍是 `compatibility`，旧授权记录仍是有效风险面。
- 当前两名人类平台管理员都具备可登录和 active-session 事实，正好达到后续不变量
  下限。
- 25 个资源和 49 条资源 Secret reference 都属于后续受控重置影响面。
- 平台加密 Secret 本身是独立资产，不属于“删除全部 DB/Redis/Loki”的默认删除范围。
- `default-diagnostic-application` 是明确的运行时受影响应用，`assist01` 是明确的授权
  scope 受影响应用。
