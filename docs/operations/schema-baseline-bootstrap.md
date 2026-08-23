# 空库 Baseline 100、当前迁移 119 与初始管理员

本文适用于全新空数据库。Schema、初始管理员和本地业务样例是三个独立步骤，禁止把用户或 fixture 写入 baseline SQL。

## 自动启动顺序

Compose 的 `migrator` 依次执行：

1. `python -m app.cli.migrate`
2. `python -m app.cli.bootstrap_admin --non-interactive`
3. `python -m app.cli.apply_agent_runtime_grants`

依赖服务使用 `service_completed_successfully`，任一步失败都会阻止 API、Worker 和 Runtime 接管。不要临时删除依赖条件或手工伪造 `schema_migration`。

## local / test 空库

```bash
docker compose up --build postgres migrator
docker compose ps
docker compose logs migrator
```

空库先执行 `100_baseline_v1.sql`，再顺序执行当前 forward migration `101..119`；当前
checkout 的账本 head 必须为 `119`。Baseline `100` 是建库起点，不是当前 deployable
head。如果不存在任何启用的平台管理员，bootstrap 创建：

- 用户名：`admin`
- 显示名称：`Administrator`
- 本地测试初始密码：`111111111111`

数据库只保存 Argon2 哈希。首次登录后应立即修改密码；重复启动不会重置密码、用户状态、revision、角色或成员关系。默认 Agent、应用、Connector 和测试数据仍由独立 local seed 管理。

## staging / production 空库

非本地环境禁止使用固定密码，也不接受明文 CLI 参数或普通环境变量。创建只允许权限为 `0400` 或 `0600` 的普通、非符号链接密码文件，或在 TTY 中交互输入：

```bash
install -m 0600 /dev/null /secure/path/initial_admin_password
# 使用安全终端编辑文件，内容为一行至少 12 字符的密码
APP_ENV=production \
INITIAL_ADMIN_PASSWORD_FILE=/secure/path/initial_admin_password \
.venv/bin/python -m app.cli.bootstrap_admin --non-interactive
```

容器部署应把 Secret 以文件挂载到 `/run/secrets/initial_admin_password` 并保持受限权限。文件缺失、权限过宽、包含多行或不可读取时 bootstrap 失败关闭。日志只输出 created / existing_admin_preserved 状态，不输出密码或哈希。

## 验收

```sql
select version, name from schema_migration order by version;

select u.username, u.display_name, r.code
from app_user u
join rbac_user_role ur on ur.user_id = u.id and ur.status = 'enabled'
join rbac_role r on r.id = ur.role_id and r.status = 'enabled'
where r.code = 'platform-admin';
```

当前 checkout 的新库应看到连续 `100..119`，最终行为 `119`；缺号、重复、未知版本或
checksum 不一致都必须失败关闭。管理员结果必须至少一行。不要查询或输出
`user_password_credential.password_hash` 作为常规验收证据。
