# 资源查询结果文件与 Loki 上限

## 当前行为

- `query_database` 默认 100 行，显式最多 10000 行。SQL 仍只读、受真实资源的数据库/schema/表前缀约束；超时不超过 30 秒。不新增通用分页。
- `query_redis_get` 保留 GET；`query_redis_scan` 默认使用当前平台页上限（默认 200 个 key），继续使用绑定 Job/授权/资源的原分页游标，不自动无限扫描。
- `query_loki` / `diagnose_loki_probe` 保留每条实际取回的脱敏日志，不按 4000 字符丢弃正文。
- 上述五个工具的成功查询正文在 Python Runtime 中保存为 `work/query-*.md` 只读临时结果，内联返回 `returned`、`complete`、`truncated`、`truncation_reasons`、`file_complete`、`result_file`、`size_bytes` 与读取提示。Redis SCAN 同时保留 `has_more/next_cursor`。
- `file_complete=true` 仅表示本次返回内容完整保存；`complete=false` 表示查询覆盖可能不足。Loki 返回数达到 `limit` 时为 `line_limit_reached`，不能据此判断真实总匹配数。
- 资源目录、数据库结构目录、Loki 标签元数据保持有界内联返回。

## 配置

| 项目 | 默认 | 可配置/有效边界 |
| --- | --- | --- |
| Loki 资源 max_lines | 1000 | Web/API 新建编辑 1–10000 |
| 平台 MAX_LOKI_LINES | 10000 | 调用取平台与已发布资源的较小值 |
| Loki 资源 max_minutes | 60 | 1–43200（30 天） |
| 平台 MAX_LOKI_MINUTES | 60 | 1–43200；调用取平台与已发布资源的较小值 |
| 单次查询规范化结果 | 8 MiB | 独立于 MAX_TOOL_RESPONSE_CHARS；超出传输预算拒绝 |
| Sandbox（仍为 sandbox-v2） | 512 MiB/128 文件 | 单文件 15 MiB、inputs 40、work/outputs 共 80、tmp 8 |

例如：只把资源设为 43200、平台仍为 60，实际仍为 60 分钟。资源目录 `effective_limits` 显示最终可用值；不得让模型反复猜测。平台显式值和已有资源不自动迁移；修改 Draft 后须验证并发布。`LOKI_MAX_MINUTES` 为兼容配置，直接资源查询的全局限制使用 `MAX_LOKI_MINUTES`。

8 MiB 不是无限取数：数据库驱动仍按行/字节返回有界结果，Loki 上游响应统一受代码级 8 MiB 和 HTTP 超时限制，规范化结果也独立校验 8 MiB。资源表单/API 不再提供 `max_response_bytes`；旧草稿和已发布版本中的该字段兼容忽略，旧版本存储不改写，新保存草稿不保留它。达到容量应缩小查询范围；Loki 字符摘要限制取消不代表取消脱敏、超时、响应字节或授权。

### Runtime 临时容量

`AGENT_RUNTIME_TMPFS_SIZE=1g` 为单个 Runtime 容器的临时内存文件系统上限（1 GiB），不是每个 Job 的预算，且不等于启动时预分配全部容量。每个 Job Sandbox 的实际文件与预留合计最多 536870912 字节（512 MiB）；并发 Job 共享容器 tmpfs，不能把 1 GiB 与 512 MiB 相加。1 GiB 是单 Job 配额扩容后的部署起点，不保证多个满负载 Job 并发；readiness 要求当前可用空间至少 512 MiB。

单 Job 最多 128 个受管文件：inputs 最多 40 个、work/outputs 合计最多 80 个、tmp 最多 8 个；每个文件最多 15728640 字节（15 MiB），先触及容量或数量任一上限即拒绝。查询结果文件占 work/outputs 名额。当前 sandbox-v2 标识不变，启动仍校验上述固定配额，旧 env 的 224 MiB/64/16 必须同步为 512 MiB/128/80；不能只改其中一层。tmpfs 大小和清理周期不在这组六项固定校验内。Manifest schema v5 与 Runtime 协议版本不变。

`AGENT_RUNTIME_SANDBOX_CLEANUP_INTERVAL_SECONDS=300` 表示每 5 分钟检查并清理非 RUNNING Job 的异常残留，启动时也检查。正常成功、失败、取消或超时会在结束时清理，不必等 5 分钟；扫描不会删除仍在运行的任务目录。

## 生命周期与权限

结果不自动创建 File Version、不自动显示为持久工作区文件、不自动交付用户。仅有查询权限时派生 Read/Glob/Grep，不增加 Write/Edit、Shell 或 File MCP 权限。路径由代码生成，禁止 Provider/模型指定，写入失败或完整性不符回滚预留及不完整文件，不回退内联大正文。

成功、失败、取消、超时均清理当前 Job Sandbox，异常退出后恢复扫描清理不再运行的残留目录。独立运行/MCP 审计按原保留策略保留，不随临时文件删除。模型若需要在后续新 Job 使用相同数据，应重新授权查询；用户明确要求交付报告时仍走既有显式文件提交流程。

## 部署步骤

1. 先等待旧任务结束，执行迁移 `136_expand_sandbox_v2_capacity.sql`，同版本构建/升级 tool-mcp、python-agent-runtime、API/Agent Worker、file-service 和 admin-web，勿让旧 Runtime 承接新增文件结果合同。迁移只放宽快照配额 CHECK 并更新新行默认值，不改历史快照数值或 hash。
2. 同步现有 `.env`：`AGENT_RUNTIME_SANDBOX_CAPACITY_BYTES=536870912`、`AGENT_RUNTIME_SANDBOX_MAX_FILES=128`、`AGENT_RUNTIME_SANDBOX_MAX_WORK_OUTPUT_FILES=80`；tmpfs 至少按示例配置 `AGENT_RUNTIME_TMPFS_SIZE=1g`，并发需求另行规划。重建容器后核对 `/ready`。本次配额扩容本身不升级 sandbox-v2/Runtime/工具 schema；前面的工具结果合同变化仍需在 Web 重新发布受影响 Agent，再更新应用固定版本并发布，旧 Job Snapshot 不自动改写。
3. 需要 30 天范围时设置 `MAX_LOKI_MINUTES=43200`，按运行配置提示重启/重建相关服务以加载配置；对应 Loki 资源亦须配置 43200 并验证发布。行数需要 10000 时同步发布资源 `max_lines=10000`。
4. 新 Job 先查资源目录，再执行合法查询；确认返回临时路径而非正文，Read/Grep 能定位末尾数据，文件不可写且终态后消失。
5. 分别验收 Redis 续页、数据库 100/10000 边界、Loki 60/43200 有效限制、10000 行触限及字节超限；Windows 环境另验 Sandbox 临时目录清理。

本地合成与 Mock 通过不等同真实 Provider 或 Windows 已验收。真实部署验收在 OpenSpec 中保持单独未完成项。
