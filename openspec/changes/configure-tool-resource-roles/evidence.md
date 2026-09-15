# 资源角色实现与验收记录

日期：2026-09-15。实现位于当前主工作区；本记录的功能验收完成时尚未提交、未部署、未修改业务数据库。

## 实现结果

- 工具资源新建和编辑支持可选“资源角色”，输入新值、复用已保存 Draft / Revision 的历史候选及清空；数据库与 Redis 使用，Loki 不使用。
- 保持 wire 字段 placement；旧 cloud/edge 与自定义中文角色兼容，区分大小写，不自动互译或根据资源名猜测。
- 角色在 Draft / Revision 持久化，覆盖新内容哈希；保存使验证失效，发布后才影响解析。
- 目录和查询读取当前 Published Revision 的角色。具名角色精确定位；重复角色或空角色多候选保持 AMBIGUOUS。搜索过滤和分页不掩盖歧义。
- 不新增授权维度；角色选择无法越过环境、基地、车间授权。审计支持完整 64 字符角色。

## 本地验证

- 后端相关回归：212 passed，1 skipped；覆盖资源生命周期/API、Schema 迁移、目录分页、MCP 解析及审计、Oracle 验证代理等。随后补充数据库/Redis 新建自定义角色两项测试，生命周期测试文件复跑 16 passed（合计 214 个不同测试通过）。
- 跳过项：PostgreSQL 完整资源列表 API 回归未提供专用 GOVERNED_RESOURCE_POSTGRES_DSN；不能视为真实数据库 API 验收通过。
- 前端资源治理交互：36 passed；类型检查和生产构建通过；相关 ESLint 和后端 Ruff 通过。
- 完整 SQLite 131 → 132 升级及重放检查通过。隔离 PostgreSQL 18 使用最小历史资源表 fixture 执行真实 132 SQL，确认 cloud/edge/空值保留、发布哈希不变、草稿转 DRAFT、新角色可保存；不是完整生产库迁移或真实 Oracle 连接验收。
- Compose 配置、严格 OpenSpec 校验、git diff --check 通过。构建保留原有 Vite 配置和 bundle 大小提示。
- PostgreSQL 测试实例无网络、数据在 tmpfs；验收后停止并自动移除，临时 SQL 已清理。

## 升级及现场操作

1. 合并当前工作区时保留既有知识导入变更。新增 132 迁移排在该变更的 131 后，不修改旧迁移 checksum；部署包需包含一致的迁移目录。
2. 按现有升级流程备份，停止旧版本业务进程，运行 migrator，再统一启动新版 API、tool-mcp、相关 Worker / Runtime 和管理端，避免新代码连接旧 schema。
3. 旧发布角色从身份字段原样迁移，发布哈希不重写；旧草稿需先保存，再做技术验证和发布。没有草稿时可从发布版本创建草稿。
4. 为目标两条 Oracle 资源分别显式填写“云”“边”（也可沿用 cloud/edge），保存、验证并发布。不要仅改资源编码或假定代码会自动识别名字。
5. 四个工具的 placement 输入契约已更新：get_schema_directory、query_database、query_redis_get、query_redis_scan。重新发布受影响的 Agent，再更新并重新发布对应应用。旧 Job 冻结快照不改写，应创建新 Job 验收。
6. 新 Job 查看目录应看到两条独立 AVAILABLE 资源及准确角色。明确指定云/边分别查询；不指定时应询问，重复同角色仍应拒绝。以上现场验收尚未执行。
