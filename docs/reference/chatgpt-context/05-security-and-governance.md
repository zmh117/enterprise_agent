# 05 安全与治理

- 身份、RBAC、Application、MCP Tool 和数据范围是独立事实源。
- Agent/Application 发布只冻结可重复校验的 identifier、revision 和 hash。
- `tool-mcp` 不使用 MCP 专用 Token/JWT/RBAC；每次调用使用 Job 事实并复核当前权限。
- Runtime Grant 仅保护 Worker 到 Agent Runtime，Model Probe Token 仅保护模型测试。
- Secret 以仓库外 Master Key 加密，只通过 Secret Ref 使用。
- Prompt、Secret、原始凭据、无界工具结果不得写入日志、事件或审计。
- 数据库/Redis/Loki 工具必须只读、有界、显式失败。
- ONES 邮箱/密码只用于当前本人验证请求；管理员不能代验或代解绑。
