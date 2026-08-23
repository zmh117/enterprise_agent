# 05 安全与治理

- 身份、RBAC、Application、MCP Tool 和数据范围是独立事实源。
- Agent/Application 发布只冻结可重复校验的 identifier、revision 和 hash。
- `tool-mcp` 不使用 MCP 专用用户 Token/JWT/RBAC；每次调用使用 Job 事实并复核当前权限。
- `ones-mcp` 与 File MCP 使用精确 audience/scope 的短时 Principal JWT；这是外部个人
  凭据与文件授权边界，不是第二套管理 RBAC。
- Runtime Grant 仅保护 Worker 到 Agent Runtime，Model Probe Token 仅保护模型测试。
- Secret 以仓库外 Master Key 加密，只通过 Secret Ref 使用。
- Prompt、Secret、原始凭据、无界工具结果不得写入日志、事件或审计。
- 数据库/Redis/Loki 工具必须只读、有界、显式失败。
- ONES 邮箱/密码/Token 只在本人流程中接收，并使用平台 Master Key 与 purpose AAD
  加密保存到 Challenge/当前 credential；API、日志和审计不返回敏感材料。管理员不能
  代验、读取凭据或代解绑。
- MinIO 凭据只进入 File Service；原始 PDF/Office/图片不进入 Agent Sandbox。
