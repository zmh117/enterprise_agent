## Context

当前 ONES result bridge 已在 Runtime 内使用 JobSandbox 原子预留、只读发布和清理。tool-mcp 查询直接返回模型，Loki highlights 被 4000 字符裁剪；DB 驱动容量又与摘要字符数耦合。资源目录不返回限制，Loki schema 仅有 minimum。

## Goals / Non-Goals

目标：复用受控结果 bridge；让实际查询正文完整保留在单 Job 文件中；提供准确行数/完整性与有效限制；实现已确认的 DB/Loki 上限。

非目标：无限查询、通用 DB/Loki cursor、跨 Job 文件共享、自动文件交付、扩大 Redis namespace 或 SQL/Loki 授权、改变 ONES 查询协议或 sandbox-v2 标识、删除审计。

## Decisions

1. Runtime 对 query_database、query_redis_get、query_redis_scan、query_loki、diagnose_loki_probe 的成功结果物化；目录、schema 和 Loki label 元数据继续内联。复用 ONES 的连接/冻结契约校验和 Sandbox 发布逻辑，按 Server 隔离 bridge；无 File MCP 时仅派生 Read/Glob/Grep。
2. 结果文件使用代码生成的 work/*.md，正文标为不可信数据；只读、不可作为持久文件直接提交。元数据保留 returned、complete、truncated、原因、分页控制、文件大小/路径。只把完成校验的文件暴露给模型；失败不得退回大正文内联。
3. 业务结果使用独立 8 MiB 规范化传输预算，脱离 4000 字符摘要配置；沙盒单文件仍不超过 15 MiB，总量扩至 512 MiB/128 文件，work/outputs 共 80 槽位，inputs 40/tmp 8 不变。数据库驱动保留有界行数/字节，超预算明确 truncated；Redis/Loki 传输超预算安全失败，不伪造完整文件。Loki 原始响应使用同一代码级 8 MiB 上限，资源不再配置 max_response_bytes；Web/API 新草稿不保留该字段，旧草稿和不可变发布版本中的旧字段兼容忽略，不修改历史存储、哈希或其他查询限制。技术验证、标签发现、业务查询使用一致的代码级上限。
4. DB 默认 100、显式 1–10000，拒绝超限而不是静默夹取；SQL 方言只读及 30 秒超时不变。Redis 每页默认/平台上限 200，保留当前 cursor，不自动翻到末页。
5. Loki max_lines 的默认值 1000 与最大值 10000 分离；max_minutes 最大 43200、默认 60；平台也接受同一时间边界。已有显式配置和 Published Revision 不变，运行取 min。目录仅读取已发布配置中的白名单数字，不解析凭据；上限参与分页候选指纹。
6. Loki 逐条脱敏且不按字符数省略正文；返回数达到 limit 时保守标注可能还有结果（不能断言真实总量）。上游返回条数、落盘完整性与查询覆盖完整性分开；字节超限仍为失败。
7. 配额常量由 shared/sandbox_contract 共享给 Runtime、Manifest 预检/新快照和审计计数；sandbox-v2、Manifest v5、Runtime 1.5 与派生工具 schema 不因本次配额扩容改变。迁移 136 允许历史/新配额值共存，不回写历史快照；新 Job 保存新配额。启动仍要求 env 精确匹配当前代码配额，readiness 要求至少 512 MiB 可用空间。配套 tmpfs 为 1 GiB，但不宣称能承载多个满负载 Job；部署先排空旧 Job，迁移并同步更新服务和 env。

## Risks / Trade-offs

- 更大 Provider 数据 → 独立字节预算、原有 timeout 与 Sandbox 原子容量预留继续生效，配额按本次批准值扩容。
- 反复查询会占用 80 个工作文件槽位 → 目录/标签不物化，失败明确报告预算，不自动删仍被引用的结果。
- 旧 Runtime 不识别新文件结果机制 → tool-mcp 与 Python Runtime 同版本部署，schema 变化后重新发布 Agent/应用；不改写历史 Job。
- 实际环境差异 → 本地合成/Mock 测试与真实 DB/Redis/Loki、新 Job/Windows 验收分别记录。

## Migration Plan

先排空旧 Job，再执行 136 数据库迁移并同版本升级 tool-mcp、Python Runtime、API/Worker、file-service 与 Web。同步 env 的三项新配额和 tmpfs，管理员按需发布资源、Agent 与应用。历史快照保留旧值；回滚须先排空新任务并恢复旧代码、env 和对应发布版本，已存在扩容快照时不能直接收紧数据库 CHECK。已有资源超过旧上限需先调回兼容值。

## Open Questions

无待决产品规格；真实环境验收需在部署后新 Job 中执行，不在本次直接访问真实业务数据。
