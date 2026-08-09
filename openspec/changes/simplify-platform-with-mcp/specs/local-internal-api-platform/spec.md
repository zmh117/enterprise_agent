## REMOVED Requirements

### Requirement: Local Internal API Platform is available for development
**Reason**: `internal-api-platform` 服务、Compose wiring 和本地协议端点彻底删除。

**Migration**: 不保留兼容容器；开发环境启动独立 `data-mcp-server`。

### Requirement: Local platform queries real Loki through bounded endpoint
**Reason**: 旧 Loki HTTP 桥接端点和配置直接删除。

**Migration**: 不转换旧配置；使用新声明式文件与 CLI 从空状态发布 Loki Resource 后调用代码定义 MCP Tool。

### Requirement: Loki query input is constrained
**Reason**: 旧协议的 Loki 输入模型随服务删除。

**Migration**: 无数据迁移；Data MCP 重新实现结构化过滤、范围与结果上限，禁止自由 LogQL。

### Requirement: Local context endpoints provide explicit placeholders
**Reason**: Internal Platform context placeholder 端点不再存在。

**Migration**: 无；未实现的 MCP Tool 不注册，已注册 Tool 不返回静态假数据。

### Requirement: Unconfigured database and Redis tools are disabled by default
**Reason**: 旧数据库/Redis Tool 注册与快照逻辑删除。

**Migration**: 不读取旧记录；Data MCP 在新 Resource Deployment 缺失时失败为未配置。

### Requirement: Real Claude and local Loki can be validated end to end
**Reason**: 旧 E2E 路径依赖已删除的 Internal API Platform。

**Migration**: 不保留旧 smoke；新验收覆盖 Agent Worker 到 Data MCP、Loki Provider 与 MCP provenance 的完整链路。
