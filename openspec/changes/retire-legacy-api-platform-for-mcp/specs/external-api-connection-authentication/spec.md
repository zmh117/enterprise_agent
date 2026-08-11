## REMOVED Requirements

### Requirement: API Connection 使用 Draft Verify Publish 生命周期
**Reason**: 旧 API Connection 永久退役。
**Migration**: 删除 Draft/Revision/Verification 数据；模型连接和渠道 Connector 不受影响。

### Requirement: Connection 固定请求 Origin
**Reason**: 通用 API Connection executor 删除。
**Migration**: 未来专用 MCP Tool 自行声明固定上游边界。

### Requirement: Connection 明文 HTTP 必须显式授权
**Reason**: API Connection 配置删除。
**Migration**: 不保留全局明文 HTTP opt-in。

### Requirement: Authentication Profile 固定登录与认证协议
**Reason**: Authentication Profile 随 API Connection 删除。
**Migration**: 不迁移密码、Token 或登录映射。

### Requirement: 首个 Connection 可临时使用当前管理员自验证
**Reason**: Connection bootstrap verification 删除。
**Migration**: 无需迁移。

### Requirement: Connection 失效时运行时失败关闭
**Reason**: API Connection 运行时删除。
**Migration**: MCP Tool 的上游配置失败仍必须失败关闭。

### Requirement: 网络调用边界不得被描述为完整 SSRF 防护
**Reason**: 通用 Connection 网络边界不再存在。
**Migration**: 固定 MCP Tool 上游采用各自明确 allowlist。

