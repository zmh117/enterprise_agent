# MCP 平台不可恢复切换 Runbook

## 适用范围与硬性边界

本 Runbook 只用于将旧 API Capability / Internal API Platform 切换为 ONES MCP 与 Data MCP。清理会直接删除旧表、列、Job/Tool 历史和旧凭据；不备份、不导出、不转换、不迁移，也不存在数据回滚。历史为空是预期结果。

生产执行前必须已经在可丢弃、与生产同版本的 PostgreSQL 环境完成 OpenSpec 任务 10.2–10.6 的全链路演练并保存验收记录。未满足时禁止在生产设置 `DESTRUCTIVE_CUTOVER_ENABLED=true`。

## 角色

- 切换负责人：宣布维护窗口、控制入口恢复和最终决策。
- 平台管理员：使用 `platformctl` 执行检查、清理和新资源发布。
- 部署管理员：停止/启动进程并核对实际容器状态。
- 验收人：独立核对身份、MCP、渠道、投递和敏感信息证据。

任何一个角色发现对象清单、Hash、进程状态或验收结果不一致，都必须停止；不得临时修改 SQL、跳过检查或用旧服务恢复业务。

## 1. 维护窗口前检查

1. 部署包含 `claude-agent-sdk==0.2.134`、独立 `mcp==2.0.0` Server 包、迁移 034–036、最小权限服务角色和本 Runbook 的同一构建。
2. 确认仓库中的对象清单和脚本未被现场修改：
   - `config/legacy-platform-retirement.json`
   - `backend/maintenance/legacy_platform_cutover.sql`
3. 准备仓库外 Master Key、MCP Token 签名 Key 和四个数据库服务身份密码。Master Key 只能挂载给 API、两个 MCP Server 及确实解密投递/附件凭据的 Runtime；Agent Worker 和前端不得获得它。
4. 准备不含明文密码/Token 的 DB、Redis、Loki Manifest，以及通过 `0600` 文件或受保护文件描述符提供的新 Secret 明文。
5. 明确通知：旧历史和旧配置会永久删除，系统不会生成任何备份或迁移副本。

## 2. 关闭入口并排空 Job

1. 先停止钉钉 Stream/Webhook、公开 Webhook、调试创建 Job 入口和其他渠道入口。
2. 将 API 部署为 `DESTRUCTIVE_CUTOVER_ENABLED=true` 的维护实例。该维护实例必须同时满足：
   - 只允许切换负责人通过受限管理网络访问，不暴露普通用户或外部渠道入口；
   - 临时使用迁移/对象所有者数据库身份，因为 PostgreSQL 最小权限 API 角色无权删除旧表；
   - 数据库身份通过部署 Secret 注入，不写入 Compose、命令参数、日志或验收记录；
   - 清理验证完成后立即恢复常规 `enterprise_agent_api` 最小权限身份。
   该模式会拒绝新的 Job，但保留幂等查询和管理员切换接口。
3. 等待已接收 Job 到达 `SUCCEEDED`、`FAILED`、`CANCELLED` 或 `DEAD_LETTER`。不得通过直接改表伪造终态。
4. 停止以下进程：
   - Agent Worker；
   - Job、Webhook、Channel、Delivery、Attachment dispatch worker；
   - ONES MCP 和 Data MCP；
   - 所有旧 API Capability Runtime、Internal API Platform 或本地兼容进程。
5. 用部署平台或 `docker compose ps` 核对实际进程。执行清理时只能保留 PostgreSQL、RabbitMQ 和维护 API 等必要控制面；容器“未连接流量”不等于已停止。

若入口无法完全关闭、仍有非终态 Job，或旧服务仍在运行，本次窗口到此结束。将维护 API 恢复为常规最小权限数据库身份，并将 `DESTRUCTIVE_CUTOVER_ENABLED` 恢复为 `false` 后重新开放原有入口；此时尚未执行数据删除。

## 3. 不可恢复清理

先登录维护 API：

```bash
platformctl login --base-url https://platform.example.com --username platform-admin
platformctl cutover check
```

`check` 必须同时满足：PostgreSQL、破坏模式已开启、活动 Job 为 0、保留表存在、检测到待删除旧对象，并返回本次 `manifest_hash`、`script_hash` 和确认短语。将输出与当前构建制品中的两个文件 Hash 对照；任何不一致都必须停止。

在部署管理员再次确认入口、Worker、旧服务已实际停止后，使用 `check` 返回的精确 Manifest Hash 执行：

```bash
platformctl cutover clean \
  --manifest-hash <manifest_hash_from_check> \
  --confirm DELETE-LEGACY-PLATFORM-IRREVERSIBLY \
  --entrances-stopped \
  --workers-stopped \
  --legacy-services-stopped
platformctl cutover verify
```

`verify` 必须报告：

- `verified=true`；
- `remaining_legacy_tables=[]`；
- `remaining_legacy_columns=[]`；
- `missing_preserved_tables=[]`；
- 旧 Credential/Challenge 行数为 0；
- 所有保留 ONES Identity 均为 `REVERIFICATION_REQUIRED`；
- `legacy_history_queryable=false`。

清理成功后没有“恢复旧数据”步骤。`verify` 成功后必须先将 API 恢复为常规 `enterprise_agent_api` 最小权限数据库身份，再进行新系统配置。若验证失败，保持入口和 Worker 关闭，只能修复新 schema/代码或在可丢弃环境重新初始化；不得重建旧平台表来继续运行。

## 4. 从空状态建立 MCP 配置

1. 再次运行迁移器和固定服务角色授权，确认 schema head 及 API/Worker/MCP 独立 DSN 可用。
2. 使用 `platformctl secret create/rotate` 从 stdin、`0600` 文件或受保护文件描述符输入 Secret。不得把明文写进命令参数、YAML、Shell 历史或日志。
3. 对每个 DB、Redis、Loki Resource 依次执行 `plan`、`apply`、`verify`、`publish`；记录 Resource Revision、Deployment 和 generation。
4. 执行 `platformctl mcp status` 与 `platformctl mcp tools`，确认 Server 版本、Schema Hash、固定 Server Code 和允许 Tool 集合。
5. 每位 ONES 用户必须在轻量门户重新验证并选择默认 Team。系统只保存加密 Token，不保存邮箱密码；钉钉主体只能通过受信事件和单次 Challenge 绑定。

## 5. 启动与恢复入口条件

按以下顺序启动：

1. PostgreSQL、RabbitMQ、迁移器/服务角色授权；
2. API；
3. ONES MCP、Data MCP；
4. Agent Worker 和各 Outbox/Delivery Worker；
5. 钉钉 Runtime 与轻量前端；
6. 最后才恢复外部入口。

恢复入口前必须全部满足：

- `/api/ready` 为 ready；没有 Resource 时明确显示 `UNCONFIGURED`，已发布 Resource 必须有精确 ACTIVE generation；
- ONES MCP `/health` 和 `/metrics` 可用，Data MCP `/health` 显示 generation 与精确 LKG 状态；
- 登录、Session、修改密码、本人钉钉 Challenge、ONES 重新验证和默认 Team 正常；
- Agent Worker 的 allowlist 只包含本 Job 精确发布的 MCP Tool；取消发布后立即失败关闭；
- ONES、DB、Redis、Loki 真实只读调用均成功，Provider 401/403、Token 过期、generation 失败和服务重启行为符合预期；
- 完成 `Runtime → Inbox → Outbox → RabbitMQ → Job → Worker → MCP → Delivery` 真实链路；
- 日志、审计、API、CLI、前端产物和 Tool 结果扫描不含 Secret、Token、认证 Header、Master Key 或连接凭据。

验收人签字后，将 API 恢复为 `DESTRUCTIVE_CUTOVER_ENABLED=false` 并逐步开放入口。任何一项失败都保持入口关闭，在新系统内修复；数据删除本身不可回滚。
