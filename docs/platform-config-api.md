# 平台工具资源与 Secret API

平台配置只保留工具资源、Secret、业务数据范围拓扑和审计。工具目录来自代码 MCP Manifest，不提供动态 Handler、Release 或任意 Server 配置。

## 工具资源生命周期

```text
Resource Identity
  -> Draft Revision
  -> technical verify
  -> Published Revision
  -> Disabled / Archived Identity
```

运行时只解析已发布 Revision。发布新 Revision后，新 Tool Call 使用新事实；历史 Job 和 Tool Call 保留原有摘要，不被回写。

资源的核心字段：

- `code`、`name`、`resource_kind`、`provider_type`
- `scope_type`、`environment_code`、`base_code`、`workshop_code`
- 可选 `placement`
- Provider config
- `secret_refs`

环境编码允许管理员输入真实字符串；基地和车间属于可选业务数据范围。无基地、无车间的环境级资源是合法资源，不创建 `default`、`none` 等虚拟节点。

## Secret

Secret API 只返回 metadata、masked value 和 `secret://platform/<code>`，不回显明文。资源配置只保存 Secret Ref。Master Key 本体必须位于仓库外的只读文件。

## 明确不存在的边界

- 不配置 API Connection 或通用 HTTP executor。
- 不配置动态 Tool Handler、安装、验证证据或 Release 生命周期。
- 不配置 Application Resource Mapping、激活代次或 Last Known Good。
- 不配置独立内部工具服务的地址或 Token。

标准调用链和授权时机见 [tool-mcp.md](tool-mcp.md)。
