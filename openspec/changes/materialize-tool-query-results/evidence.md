# 本地验证记录（2026-09-18）

## 实现

- 独立 8 MiB 查询结果合同与通用 ResultFileBridge；ONES 继续使用原字段/集合协议，tool-mcp 五个业务查询使用新物化器。
- 不内联查询正文，无 File MCP 时只派生 Read/Glob/Grep；按冻结 schema 连接并校验工具，保留 MCP audit 元数据，写入失败回滚，终态清理。
- DB 显式 10000 行、Loki 配置 10000 行/43200 分钟、资源目录 effective_limits、明确的超限错误码及截断原因。
- 保留默认值与旧发布配置；未修改真实数据、Secret、运行配置或部署。
- 大结果压测发现既有 URI 凭据脱敏正则对无 URL 的长连续文本发生超线性匹配；增加必要分隔符检查与 scheme 起点边界，保持凭据脱敏语义，新增 600 KiB 合成文本与凭据回归。

## 已通过

- 相关 18 个测试文件合并执行：**489 passed, 1 skipped**，44.39 秒。覆盖查询文件、ONES 原协议、Runtime 及权限/预算、资源治理、Loki、Redis/schema 分页、DB 驱动、Sandbox、运行配置与工具审计摘要。
- 新增验证涵盖 10000 条 DB 文件、单行超过 4000 字符完整保留、500/1000/10000 行范围、43200/43201 分钟边界、目录不解析 Secret、保留 Redis cursor、文件写入失败回滚、16 文件配额、字节超限失败关闭、冻结契约不符、安全脱敏。
- 新增无 File MCP 的查询 Job 全流程合成测试：数据库/Loki 正常读取、禁止写入，在成功/失败/取消/超时四类退出后 Sandbox 消失；既有 ONES 同类验收保持通过。
- `mypy backend/app`：434 个源文件通过；受影响代码与测试 Ruff 检查通过；`git diff --check` 通过。
- `frontend` 的 `npm run build` 通过（既有 Vite configLoader 和 chunk-size 警告，不阻塞）。
- `docker compose config --quiet` 与 `openspec validate materialize-tool-query-results --strict` 通过。

## 尚未验证

- 跳过项为未配置 GOVERNED_RESOURCE_POSTGRES_DSN 的真实 PostgreSQL 资源目录回归；SQLite/合成目录测试已通过，不能代替该项。
- 未构建/切换部署镜像、未连接真实业务数据库/Redis/Loki、未执行真实模型新 Job 或 Windows 验收；3.3 保持未完成。
- 运行说明见 `docs/runbooks/tool-query-result-files.md`。部署后须重新发布受影响 Agent 与应用，按需发布资源；要查询 30 天，平台和资源的时间限制都须配置到 43200。

## 工作区边界

开始时存在的知识向量索引运行手册/evidence/tasks 修改及 enable-governed-knowledge-retrieval 目录均未改动。本次未提交、未推送、未归档或同步 canonical specs。

## 补充：删除 Loki 资源响应字节配置（2026-09-18）

- Web 默认值、输入项、提交副本和 Provider 配置合同移除 max_response_bytes；旧字段在规范化及旧发布版本运行投影时兼容忽略，不改写历史版本或原表单对象。目录读取不再要求旧字段，返回的只读有效字节保护为代码级 8 MiB。
- Loki 业务查询、标签发现及 selector 技术验证统一使用 QUERY_RESULT_MAX_BYTES，保留上游超限失败与规范化结果容量校验。
- 新增无旧字段/带旧字段兼容验证及三条 HTTP 路径 2 MiB 可读、超过 8 MiB 拒绝测试；本次相关 10 个后端测试文件 **274 passed**。Web 新建/编辑上限及旧草稿保存回归 **4 passed**（仅选择这 4 项）。
- mypy 434 文件、受影响 Python Ruff、Web 构建、Compose 配置、严格 OpenSpec、git diff --check 通过。未部署，未修改 .env 或沙盒固定配额；真实环境验收仍未完成。
- 运行手册补充 512 MiB 容器 tmpfs 与单 Job 224 MiB 的区别，以及 sandbox-v2 固定配额校验和 300 秒残留清理含义。

## 补充：sandbox-v2 数值扩容（2026-09-18）

- 根据后续明确批准，单 Job 配额变为 512 MiB/128 文件，work/outputs 合计 80，inputs 40/tmp 8/单文件 15 MiB 不变。sandbox-v2、Manifest v5 和 Runtime 1.5 不升级；单次查询 8 MiB 不变。
- 新增共享配额常量，同步 Runtime 启动/readiness、文件 Manifest 预检/新快照、日志审计数值边界。新增迁移 136 放宽数据库旧固定 CHECK：历史 64 文件/224 MiB 和新 128 文件/512 MiB 并存；新行默认新值，旧快照数值/hash/version 不改写。
- `.env.example`、本机 `.env` 和 Compose 配额已同步；tmpfs 为 1 GiB，避免与单 Job 512 MiB 完全重合。它是容量上限，不预分配全部内存，也不保证多个满负载 Job 并发。readiness 仍检查实际剩余空间，至少 512 MiB 才就绪。
- 核心回归 7 个测试文件 **243 passed**（Sandbox、Manifest、迁移、容量实写 benchmark、查询文件、Runtime、ONES）；兼容回归 12 个测试文件 **153 passed, 1 skipped**。两组存在测试主题重叠，不合并为唯一测试数。跳过项仍为未配置的真实外部环境用例。
- 一次性 PostgreSQL 18 隔离容器验证 **2 passed**：旧快照迁移前后逐字段一致、新默认值和非法值约束；完整新库迁移到 136 及数据库注释检查。该容器只使用合成数据，不访问业务数据库，不代表 Windows 已验收。
- 边界回归确认第 81 个工作输出文件被拒绝，512 MiB 的跨文件预留可用、再多 1 字节被拒绝；输入仍限 40，单文件仍限 15 MiB，readiness 的 512 MiB 边界与旧 env 拒绝均覆盖。合成 benchmark 实写 128 个文件共 512 MiB 并清理。
- mypy 435 文件、受影响 Ruff、Compose 配置、严格 OpenSpec 与 git diff --check 通过。未提交/推送、未执行业务数据库迁移、未构建或重启现有服务，3.3 真实新 Job/Windows 验收仍未完成。
