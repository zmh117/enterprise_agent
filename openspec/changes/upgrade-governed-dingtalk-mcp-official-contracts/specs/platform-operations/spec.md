## MODIFIED Requirements

### Requirement: dingtalk-mcp 与 Action worker 必须进入固定部署拓扑
平台 Compose SHALL 部署固定 `dingtalk-mcp` Streamable HTTP 服务和外部操作 worker，使用非 root 身份、只读镜像文件系统、私网 MCP 地址、独立健康/就绪检查与数据库 claim。Agent Runtime、API 和 `dingtalk-runtime` MUST NOT 接收 Connector Secret 原值。新 Publication 的就绪门禁 MUST 覆盖当前启用的通讯录、部门、待办、日历、AI 表格、机器人消息和工作通知 profile，验证其代码 Manifest、固定官方契约清单、Provider method/path 和响应样例一致；任何未分类 Tool、旧接口违规或未知成功响应结构都必须失败关闭。

#### Scenario: dingtalk-mcp 未就绪
- **WHEN** MCP 服务、Action worker、migration、卡片回调能力或任一已启用 profile 的官方契约校验未就绪
- **THEN** 新 Application Publication 不得宣称对应钉钉 Tool 可运行

#### Scenario: 扫描 Compose 配置
- **WHEN** 运维渲染生产 Compose
- **THEN** Secret 只通过既有平台 Secret 解析路径到达拥有外部连接的 worker，且不出现在环境示例明文中

#### Scenario: 全部容器健康但 AI 表格响应样例失败
- **WHEN** Compose 服务健康而 AI 表格官方 `value` 响应样例未被正确投影
- **THEN** `dingtalk-mcp` 就绪检查或发布门禁失败
- **AND** 系统不得创建声称 AI 表格 Tool 可运行的新 Publication
