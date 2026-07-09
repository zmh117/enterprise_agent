## Context

Internal API Platform 已具备基地级 Redis / 多方言只读 DB 网关，但连接层偏「开发友好」：

- Redis：`redis.Redis(host, port, db)` 单节点，无 Cluster。
- Oracle：`oracledb` **thin** 模式，DSN 为 Easy Connect；无 Instant Client，对旧版 Oracle（尤其 11g 及部分 12c 场景）兼容不足。
- Docker：`internal-api-platform` stage 仅 pip 安装纯 Python/thin 驱动，刻意不打 Instant Client。

生产侧已出现 Redis Cluster 与旧版 Oracle 接入需求；归档 change 中「是否必须 Instant Client」的 Open Question 需要在本变更中关闭。

约束：对外工具 HTTP 契约不变；车间隔离（Redis key 前缀、Oracle 表前缀）与只读策略不变；密钥仍走 secret ref，不进拓扑明文。

## Goals / Non-Goals

**Goals:**

- Redis 支持 `standalone` 与 `cluster` 两种连接模式，配置可声明，默认保持 standalone 兼容。
- Oracle 支持 thick 模式：镜像内打包 Instant Client，进程启动时 `init_oracle_client`；可按基地配置启用 thick / 连接参数（service name / SID）。
- 旧版 Oracle 限行：在需要时使用 `ROWNUM` 包装，避免仅依赖 `FETCH FIRST`（12c+）。
- YAML 与 DB registry 的 Redis/Oracle 绑定字段同步扩展，校验清晰。

**Non-Goals:**

- 不支持 Redis Sentinel（本变更不做；若后续需要另开 change）。
- 不改变 Agent 侧工具请求字段，不暴露 host/IP 给模型。
- 不实现 Oracle Schema Directory（仍可为 unsupported）。
- 不为 api-server / agent-worker 镜像安装 Instant Client（仅 platform 镜像）。
- 不引入写操作或跨车间放宽策略。

## Decisions

### 1. Redis：配置驱动的 standalone / cluster 双模式

在 `RedisConnection`（及 YAML / `config_json`）增加：

| 字段 | 含义 | 默认 |
|------|------|------|
| `mode` | `standalone` \| `cluster` | `standalone` |
| `nodes` | Cluster startup nodes 列表 `[{host, port}]` | 空；cluster 时必填或由 host/port 推导单入口 |
| `host` / `port` / `db` / `password` | 现有字段 | 不变；cluster 下 `db` 忽略（Cluster 无 SELECT db） |

连接实现：

- `standalone` → 现有 `redis.Redis(...)`。
- `cluster` → `redis.RedisCluster(startup_nodes=..., password=..., decode_responses=True, socket_timeout=...)`。

车间 key 前缀策略、`GET` / 有界 `SCAN` 不变；Cluster 上 `SCAN` 使用客户端提供的 cluster-aware 扫描（或按 keyslot / 文档约定的安全方式），仍强制 pattern 落在车间前缀内。

**替代方案：** 仅支持 URL（`redis://` / `redis+cluster://`）。否决——与现有 host/port/secret_ref 模型不一致，且 secret 拆分更难。

**替代方案：** 始终用 RedisCluster 连单节点。否决——行为与错误语义不同，破坏现有基地。

### 2. Oracle：镜像固定 thick 可用，配置选择是否 init / 连接形态

- **镜像**：在 `internal-api-platform` stage 安装 Oracle Instant Client（Basic 或 Basic Light）及依赖（如 `libaio`），设置 `ORACLE_CLIENT_LIB_DIR` / `LD_LIBRARY_PATH`。
- **运行时**：应用启动时若检测到客户端库，则调用一次 `oracledb.init_oracle_client(lib_dir=...)`（幂等守卫）；未检测到则保持 thin（便于本地无 Instant Client 的单测/开发）。
- **连接配置扩展**（`DatabaseConnection` 或 Oracle 专用扩展字段，引擎为 `oracle` 时生效）：

| 字段 | 含义 | 默认 |
|------|------|------|
| `oracle_client_mode` | `thin` \| `thick` \| `auto` | `auto`（有 Instant Client 则 thick，否则 thin） |
| `connect_descriptor` | 可选完整连接串 / TNS | 空则用 `host:port/database` |
| `use_sid` | 若 true，用 SID 而非 service name 建 DSN | `false` |

旧版兼容：当配置声明 `oracle_row_limit=rownum` 或探测/配置为「legacy」（建议显式配置 `oracle_compat: legacy|modern`，默认 `modern`）时，方言限行使用 `SELECT * FROM ( ... ) WHERE ROWNUM <= n`，否则继续 `FETCH FIRST n ROWS ONLY`。

**替代方案：** 仅 thin + 要求升级 Oracle。否决——生产无法短期升级。

**替代方案：** 单独 `internal-api-platform-oracle` 镜像。可选优化，本变更先单镜像打入 Instant Client，接受体积增加，避免双镜像运维成本。

### 3. 拓扑与校验

- YAML loader、`PlatformTopologySnapshotBuilder`、importer/validation 同步识别新字段。
- Cluster 缺少 nodes（且无可用 host）→ 配置校验失败（非 retryable）。
- `oracle_client_mode=thick` 但进程未成功 init → 请求时返回明确 upstream/配置错误（提示镜像/库路径），不静默回退到 thin（避免「以为 thick 实际 thin」连上错误协议）。
- `auto` 允许回退 thin。

### 4. 测试策略

- 单元：连接工厂按 mode 选择客户端类；Oracle DSN/SID/ROWNUM 分支；配置校验。
- 集成：有条件跳过（`RUN_REDIS_CLUSTER_INTEGRATION` / `RUN_ORACLE_THICK_INTEGRATION`）；无真实集群/旧库时不阻塞 CI。
- 镜像：构建后检查 Instant Client 文件存在与 `init_oracle_client` 冒烟（可在 CI 用 mock 或仅文件存在断言）。

## Risks / Trade-offs

- **[镜像体积与许可]** Instant Client 显著增大镜像，且受 Oracle 许可约束 → 文档注明来源与版本；仅打入 platform 镜像；优先 Basic Light。
- **[Cluster SCAN 语义]** 跨 slot 扫描成本高、行为与单节点不同 → 保持严格前缀与 `REDIS_SCAN_LIMIT`；文档说明 Cluster 下 scan 可能更慢。
- **[Cluster 忽略 db]** 误配 `db!=0` 的 cluster 基地 → 校验告警或拒绝非 0 db。
- **[thick 全局 init]** `init_oracle_client` 进程级一次，之后 thin 不可用 → 用 `auto`/`thick` 明确预期；单进程内不混用「必须 thin 的库」与 thick（若出现，需拆进程/另开 change）。
- **[旧版 SQL]** `ROWNUM` 与子查询改写可能改变优化器计划 → 仅在 `oracle_compat=legacy` 启用；默认 modern 不变。
- **[密钥与 nodes]** Cluster 多节点 host 列表可能含内网 IP → 仍仅存配置侧，不返回给 Agent。

## Migration Plan

1. 发布含 Instant Client 的新 platform 镜像；现有 standalone Redis / modern Oracle 配置零改动。
2. 将 Redis Cluster 基地的 topology 改为 `mode: cluster` + `nodes`（或等价 DB config）。
3. 将旧版 Oracle 基地设为 `oracle_client_mode: thick`（或依赖 `auto`）+ 必要时 `oracle_compat: legacy` / `use_sid: true`。
4. 回滚：回退镜像与配置字段忽略（旧代码忽略未知字段需确认；若 DB 已写入新字段，旧版本应忽略未知键或做兼容读取）。

## Open Questions

- Instant Client 具体版本与安装介质来源（官方 zip 拷贝进 build context vs 构建时下载）——建议锁定版本号写入 Dockerfile ARG。
- 是否必须在首版支持 Redis Cluster TLS / ACL username——默认本变更支持 password；TLS/username 若生产必需则补进同一实现小步。
- 旧版 Oracle 目标版本下限（11gR2？）——用 `oracle_compat` 显式声明，避免盲目探测。
