## REMOVED Requirements

### Requirement: Platform models an environment/base/workshop topology
**Reason**: Internal API Platform 专用 topology 模型永久退役。
**Migration**: 工具资源保留自身 environment/base/workshop 目标字段。

### Requirement: Bases are addressed by business code, not IP
**Reason**: 旧 topology Base 实体删除。
**Migration**: Job 与 Resource 继续使用业务 code，不暴露地址给模型。

### Requirement: Database engine is defined per base
**Reason**: 数据库引擎不再由 Base topology 拥有。
**Migration**: 每个数据库 Resource Revision 显式保存 provider/engine。

### Requirement: Topology is loaded from YAML and seed configuration
**Reason**: YAML topology/importer 删除。
**Migration**: 已发布工具资源作为唯一资源目录。

### Requirement: Structured addressing resolves to a concrete resource binding
**Reason**: topology resource binding 与 Application Mapping 删除。
**Migration**: `tool-mcp` 按 Job 目标直接解析唯一 Resource Revision。

### Requirement: Topology bindings describe Redis mode and Oracle client options
**Reason**: topology binding 删除。
**Migration**: Redis/Oracle 配置归属对应 Resource Revision。

### Requirement: Resource placement must be independent from business topology
**Reason**: 旧 topology 规格退役。
**Migration**: placement 继续作为 Resource 与 Job 的正交可选字段，由标准 MCP Runtime 约束。

