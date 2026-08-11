# 标准 MCP 工具服务

`tool-mcp` 是两个 Agent Runtime 共用的固定标准 MCP Server。

```text
Agent Runtime
  -> tool-mcp (Streamable HTTP)
  -> Job MCP Tool Snapshot
  -> 当前角色/应用/数据范围复核
  -> Published Resource Revision
  -> Secret Ref
  -> bounded readonly adapter
```

## 发布模型

1. 代码 Manifest 定义固定 tool identifier、说明、输入 Schema、schema hash、资源类型和只读属性。
2. Agent Publication 冻结精确 Tool identifier 与 schema hash。
3. Application Publication 只能选择所选 Agent Envelope 的显式子集。
4. Job 冻结发布事实与当时可用 Tool，不冻结用户消息中的 environment/base/workshop/placement。
5. Agent 在实际 Tool Call 中给出目标参数；服务端按当前角色、应用和数据范围重新鉴权，并要求资源唯一解析。

## 资源

数据库、Redis 和 Loki Tool 只解析已发布且未停用的 Resource Revision。Resource 保存连接配置与 `secret://platform/<code>` 引用；Secret 明文只在执行适配器内短暂解析。

同一目标存在多个候选时，Tool Call 必须提供足以唯一定位的参数，例如 placement。零命中或多命中均失败关闭。

## 安全边界

- MCP Server code 固定为 `tool-mcp`，Runtime 不能提交任意 URL。
- 不设置 MCP 专用 Token、JWT、HS256 signing key、RBAC 或 Resource Mapping。
- Runtime Grant 仅用于 Worker 调用 Agent Runtime，不传给 `tool-mcp`。
- 所有工具必须只读且有界；Secret、Prompt 和无界响应不得进入日志或审计。
- Tool schema drift、Job 终态、撤权、资源停用和范围不匹配均拒绝执行。

## 验证

```bash
docker compose config --quiet
docker compose up -d --build migrator tool-mcp python-agent-runtime typescript-agent-runtime agent-worker
docker compose ps
```

验收必须检查 Job 的 `agent_tool_call`、Runtime Tool Event 和最终 Delivery，不能只检查容器健康。
