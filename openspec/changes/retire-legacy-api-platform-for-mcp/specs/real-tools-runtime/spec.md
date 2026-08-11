## ADDED Requirements

### Requirement: Real-tools 必须通过标准 MCP Tool Runtime 执行
真实工具验收 SHALL 启动 PostgreSQL、RabbitMQ、`tool-mcp`、两个 Agent Runtime、Worker 与所需工具资源；MUST NOT 启动 Internal API Platform 或配置 `INTERNAL_API_*`。

#### Scenario: 真实数据库工具链
- **WHEN** Python 或 TypeScript Agent Job 对已授权目标调用数据库只读 Tool
- **THEN** 请求沿 `Runtime -> tool-mcp -> Resource` 完成并记录精确审计

### Requirement: Real-tools 验收必须覆盖拒绝和恢复
验收 MUST 覆盖未授权 Tool、数据范围越界、资源零命中、多命中、Secret 不可用、只读策略拒绝以及配置恢复后的成功调用。

#### Scenario: 歧义资源修复
- **WHEN** 两个资源导致调用被拒绝，管理员停用冲突 revision 后重试新 Job
- **THEN** 新调用唯一解析并成功，旧失败历史保持不变

## REMOVED Requirements

### Requirement: Real-tools profile shall start the topology-aware platform
**Reason**: topology-aware Internal API Platform 永久删除。
**Migration**: real-tools 直接启动 `tool-mcp`。

### Requirement: Runtime modes shall be documented and distinguishable
**Reason**: mock/local/real Internal API Platform 三模式删除。
**Migration**: 文档只区分 fake executor 测试和真实工具资源验收。

### Requirement: Real-tools smoke test shall verify platform and agent layers
**Reason**: 独立 platform layer 删除。
**Migration**: smoke 验证 Runtime、MCP Tool 和 Resource 层。

### Requirement: Missing real-tools configuration shall fail safely
**Reason**: 旧 `FEATURE_REAL_INTERNAL_TOOLS`/URL 配置删除。
**Migration**: 缺 Resource/Secret 时 Tool Call 失败关闭。

### Requirement: Real-tools 验收必须覆盖拒绝与恢复
**Reason**: 旧场景依赖 Internal API Platform。
**Migration**: 使用新的 MCP 链路拒绝与恢复要求。

### Requirement: Real-tools 报告必须说明本地边界和延期测试
**Reason**: 旧 profile 报告格式退役。
**Migration**: 报告必须明确实际 MCP/资源/外部系统证据和未验证项。

