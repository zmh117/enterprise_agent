## 1. 工具契约与游标基础

- [x] 1.1 在代码 Manifest、权限目录和只读策略中注册 `list_available_tool_resources`，并为目录、Schema 与 Redis SCAN 定义封闭分页输入契约
- [x] 1.2 实现绑定 Job Snapshot、authorization hash、Tool、过滤条件及资源/目录版本事实的不透明 cursor codec，并覆盖无效、跨请求和过期游标测试

## 2. 授权资源目录

- [x] 2.1 扩展资源 Resolver 的非敏感候选读取契约，提供最新 Published Revision 地址事实但不解析 Secret 或连接上游
- [x] 2.2 实现业务应用 Job 的逐 access Tool/scope 授权投影，以及直接 Job 的既有 Tool/project grant 投影
- [x] 2.3 实现 `list_available_tool_resources` 的稳定排序、过滤、歧义标记、分页响应和安全审计，并覆盖 51 项、多角色不交叉拼接及未授权资源不可见测试

## 3. Schema 与 Redis 可续查分页

- [x] 3.1 扩展 Schema directory/inspector 契约为按表 keyset 读取，分别实现 MySQL、Oracle、SQL Server 和 Fake inspector 的有界 `limit + 1` 查询
- [x] 3.2 为 `get_schema_directory` 接入 Job/目标/query/Resource Revision 绑定 cursor，返回 `next_cursor`、`has_more` 与独立字段截断状态
- [x] 3.3 扩展 standalone/cluster Redis gateway 的 provider cursor 规范化，并为 `query_redis_scan` 接入 Job/目标/pattern/Resource Revision 绑定 continuation

## 4. Agent 行为与发布集成

- [x] 4.1 更新 Agent 上下文：目标未知或询问资源目录时先调用授权目录，仅使用 AVAILABLE 目标，并禁止猜测环境或重复相同失败
- [x] 4.2 更新 Agent/Application publication、Manifest/schema hash 与权限夹具，使新 Tool 仅在显式选择、发布和 Job 冻结后可见

## 5. 验证

- [x] 5.1 运行资源目录、授权、Schema、Redis、Tool MCP、Agent 上下文及 publication 定向测试并修复回归
- [x] 5.2 运行后端静态检查、相关完整测试、`docker compose config --quiet`、严格 OpenSpec 校验与 `git diff --check`，区分本变更结果和既有工作区失败

## 6. 分页正确性修复与消息链路验收

- [x] 6.1 定位实际部署的消息接入、路由与 Job 创建阻塞，恢复链路并记录去敏运行证据
- [x] 6.2 修复 Oracle 首次目录查询的空字符串 NULL 语义，增加 51 表首尾页语义回归
- [x] 6.3 修复 Redis 超额批次漏键、空批次续查与 Cluster 主节点扫描，使用有界批次重读及摘要校验且不在 cursor 中暴露节点地址
- [x] 6.4 增加真实 Redis 边界验收和授权/资源变更拒绝回归，执行受影响服务部署及必要检查
