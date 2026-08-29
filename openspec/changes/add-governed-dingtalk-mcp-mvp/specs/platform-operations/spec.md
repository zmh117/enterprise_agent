## ADDED Requirements

### Requirement: dingtalk-mcp 与 Action worker 必须进入固定部署拓扑
平台 Compose SHALL 部署固定 `dingtalk-mcp` Streamable HTTP 服务和外部操作 worker，使用非 root 身份、只读镜像文件系统、私网 MCP 地址、独立健康/就绪检查与数据库 claim。Agent Runtime、API 和 `dingtalk-runtime` MUST NOT 接收 Connector Secret 原值。

#### Scenario: dingtalk-mcp 未就绪
- **WHEN** MCP 服务、Action worker、migration 或卡片回调能力任一未就绪
- **THEN** 新 Application Publication 不得宣称 `dingtalk_create_todo` 可运行

#### Scenario: 扫描 Compose 配置
- **WHEN** 运维渲染生产 Compose
- **THEN** Secret 只通过既有平台 Secret 解析路径到达拥有外部连接的 worker，且不出现在环境示例明文中

