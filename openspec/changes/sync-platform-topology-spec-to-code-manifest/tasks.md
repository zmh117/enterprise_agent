## 1. 构建与当前文档清理

- [x] 1.1 删除 `api-server` 镜像对已移除 `backend/config` 的复制，并在 Docker 构建上下文中排除 Python bytecode/cache
- [x] 1.2 将 Oracle Instant Client 当前说明和构建命令统一为 `tool-mcp` 镜像
- [x] 1.3 扩展退役平台回归测试，覆盖 Dockerfile、Docker build context 与 canonical spec 的旧正向运行标记

## 2. Canonical spec 同步

- [x] 2.1 同步 `agent-model`、`identity-access` 与 `execution-delivery` 的 `tool-mcp`、Job Snapshot 和 Tool Call 事实
- [x] 2.2 同步 `builtin-tool-resource` 的标准 MCP、每次调用资源解析、Secret、Oracle、schema 与 Loki 契约
- [x] 2.3 同步 `platform-operations` 的测试资源、三个功能开关、资源 revision、Migrator 与验收契约
- [x] 2.4 扫描 canonical specs，确认旧平台仅保留明确的负向禁止/历史分层描述，不再被声明为当前执行者

## 3. 统一资源范围实现

- [x] 3.1 新增单调 migration，并让 Resource repository/service/API 在 Draft、content hash、验证和 Published Revision 中统一保存 `scope_bindings`
- [x] 3.2 让 `tool-mcp` 按当前调用目标精确选择 Published Revision 内的 DB 表前缀、Redis namespace 或 Loki selector，并在访问上游前失败关闭缺失/歧义范围
- [x] 3.3 将工具资源前端改为连接与数据范围分区编辑、统一保存发布，并接入 Provider Contract 与 Loki label key/value 有界发现
- [x] 3.4 补充 Resource API、范围规范化、运行时只读隔离和前端交互回归测试

## 4. 整体验证

- [x] 4.1 运行退役平台、Resource Scope、MCP Tool Runtime、前端与 Oracle 镜像定向测试
- [x] 4.2 运行 OpenSpec strict validation、Markdown 链接检查、Compose config 与 `git diff --check`
- [x] 4.3 定向构建 `api-server`、`file-service` 和 `tool-mcp` 镜像，确认构建链不再引用已删除目录
