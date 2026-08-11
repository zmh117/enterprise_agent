## ADDED Requirements

### Requirement: 平台配置不得暴露旧 API 平台对象
平台配置 API MUST 不提供 API Capability、Handler、API Connection、Application Resource Mapping、Internal API topology/runtime generation/activation 或 Internal API Token 的读取与写入端点；工具资源、凭据、模型和渠道配置继续使用各自边界。

#### Scenario: 请求旧管理端点
- **WHEN** 客户端访问已退役旧平台 API
- **THEN** 路由不存在且不得返回兼容数据

## REMOVED Requirements

### Requirement: Platform configuration API exposes topology management
**Reason**: Internal API Platform 专用拓扑控制面永久退役。
**Migration**: 工具资源按 environment/base/workshop 保存自身目标字段。

### Requirement: Platform configuration API validates domain invariants
**Reason**: 旧拓扑领域校验随平台退役。
**Migration**: 工具资源验证器只校验资源自身及业务目标字段。

### Requirement: YAML topology import upserts database configuration
**Reason**: YAML topology/importer 永久退役。
**Migration**: 通过工具资源 API 显式创建和验证资源。

### Requirement: API exposes runtime topology snapshot
**Reason**: Internal API runtime snapshot 永久退役。
**Migration**: `tool-mcp` 每次调用读取一致资源快照。

### Requirement: Imported topology can be verified as runtime-ready
**Reason**: topology import 已删除。
**Migration**: 使用工具资源 Draft verification。

### Requirement: Platform configuration API supports runtime verification workflow
**Reason**: Internal API Platform runtime generation/verification 已删除。
**Migration**: 验收直接覆盖 Runtime→tool-mcp→Resource。

### Requirement: Platform configuration API documents restart or reload semantics
**Reason**: 旧平台 reload/activation 已删除。
**Migration**: 工具资源发布不要求独立 Internal API Platform 重启。

### Requirement: Platform API accepts secret values through write-only fields
**Reason**: 旧 topology API 的 Secret 写入入口已删除。
**Migration**: Secret 只通过凭据中心写入并由资源保存 Secret Ref。

### Requirement: Resource API 必须实施技术发布门禁
**Reason**: 旧要求混合 Internal API Platform activation。
**Migration**: 资源 Draft/verify/publish 生命周期继续由 governed-tool-resource-management 约束。

### Requirement: 破坏性资源重置不得暴露为普通 CRUD
**Reason**: 旧要求包含 Mapping/runtime generation 清理。
**Migration**: 新资源重置契约仅处理工具资源与 revision。

