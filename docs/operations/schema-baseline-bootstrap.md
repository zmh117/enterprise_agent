# 数据库迁移、旧库基线接轨与空库初始化

当前仓库的[迁移目录](../../backend/migrations/)为 `100..165`。部署时以目标 migrator 镜像中的目录、checksum 和执行结果为准。

先核对数据库类型和 `schema_migration`。空库从下文的 Compose 初始化开始。已有库先备份并验证可恢复性，暂停入口并排空写入，再按账本选择升级路径。

| 当前账本 | 下一步 |
| --- | --- |
| 完整的旧 `001..041` 前缀 | 用对应的旧版本迁移包补到精确 `042`，再执行下节。 |
| 完整的旧 `001..042`，尚未采纳 `100` | 执行下节的独立基线接轨。 |
| 从 `100` 起的新库，或已完成接轨的旧库 | 使用目标 migrator 执行后续迁移。跨越 `160` 且有旧代码预提取数据时，先在 `159` 完成[盘点和退役](code-knowledge-on-demand.md#升级到当前-head)。 |
| 已有业务表但无账本、账本缺号或 checksum 不符 | 保持停写，核对部署版本和备份，排除漂移后再迁移。 |

## 已有 042 数据库

1. 取得独立发布且活动目录**只含** `100_baseline_v1.sql` 的 migrator 包，以及配套的不可变 legacy manifest。以下三个命令都在该包中连接同一目标数据库运行，`MIGRATOR_BUILD` 填该包实际构建标识。包含 `101+` 的镜像会拒绝直接接轨。
2. 先执行只读预检，核对旧账本、schema 指纹、PostgreSQL 注释和保留数据计数。仅当返回 `ready-for-adoption` 后执行迁移，再用同一构建标识核验。

   ```bash
   python -m app.cli.baseline_adoption preflight --build "${MIGRATOR_BUILD:?}"
   python -m app.cli.migrate --build "${MIGRATOR_BUILD:?}"
   python -m app.cli.baseline_adoption verify --build "${MIGRATOR_BUILD:?}"
   ```

3. 核验返回 `adoption-verified`、head `100`，且 `marker_count` 和 `adoption_metadata_count` 均为 `1`。原 `001..042` 账本和保留数据应与预检记录一致。通过后切换至目标版本的 migrator 执行后续迁移。
4. 若接轨后的核验失败，保持停写。账本仍停在刚采纳的 `100` 时，可用该包执行 `python -m app.cli.rollback_baseline_adoption --build "${MIGRATOR_BUILD:?}"` 撤销标记，核实 head 回到 `042`。已执行 `101` 或更高迁移后，恢复需使用已验证的备份。

## 自动启动顺序

Compose 的 `migrator` 依次执行：

1. `python -m app.cli.docling_profile_cutover_preflight`
2. `python -m app.cli.migrate`
3. `python -m app.cli.bootstrap_file_storage_secrets`（受本地初始化开关控制）
4. `python -m app.cli.bootstrap_admin --non-interactive`
5. `python -m app.cli.bootstrap_agents`
6. `python -m app.cli.apply_agent_runtime_grants`

依赖服务使用 `service_completed_successfully`，任一步失败都会阻止 API、Worker 和 Runtime 接管。不要临时删除依赖条件或手工伪造 `schema_migration`。

## local / test 空库

```bash
docker compose up --build postgres migrator
docker compose ps
docker compose logs migrator
```

空库先执行 `100_baseline_v1.sql`，再顺序执行当前 forward migration `101..165`；当前
checkout 的账本 head 必须为 `165`。Baseline `100` 是建库起点，不是当前 deployable
head。如果不存在任何启用的平台管理员，bootstrap 创建：

- 用户名：`admin`
- 显示名称：`Administrator`
- 初始密码：按 bootstrap 的 local/test 策略初始化，本文不复制密码；生产环境必须使用受限文件或交互输入。

数据库只保存 Argon2 哈希。首次登录后应立即修改密码；重复启动不会重置密码、用户状态、revision、角色或成员关系。默认 Agent、应用、Connector 和测试数据仍由独立 local seed 管理。

## staging / production 空库

非本地环境禁止使用固定密码，也不接受明文 CLI 参数或普通环境变量。只允许权限为 `0400` 或 `0600` 的普通、非符号链接密码文件，或在 TTY 中交互输入：

```bash
install -m 0600 /dev/null /secure/path/initial_admin_password
# 使用安全终端编辑文件，内容为一行至少 12 字符的密码
APP_ENV=production \
INITIAL_ADMIN_PASSWORD_FILE=/secure/path/initial_admin_password \
.venv/bin/python -m app.cli.bootstrap_admin --non-interactive
```

容器部署应把 Secret 以文件挂载到 `/run/secrets/initial_admin_password` 并保持受限权限。文件缺失、权限过宽、包含多行或不可读取时 bootstrap 失败关闭。日志只输出 created / existing_admin_preserved 状态，不输出密码或哈希。

## 空库初始化验收

```sql
select version, name from schema_migration order by version;

select u.username, u.display_name, r.code
from app_user u
join rbac_user_role ur on ur.user_id = u.id and ur.status = 'enabled'
join rbac_role r on r.id = ur.role_id and r.status = 'enabled'
where r.code = 'platform-admin';
```

当前 checkout 的新库应看到连续 `100..165`，最终行为 `165`；缺号、重复、未知版本或
checksum 不一致都必须失败关闭。管理员结果必须至少一行。不要查询或输出
`user_password_credential.password_hash` 作为常规验收证据。
