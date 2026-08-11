# 09 协作指南

处理本仓库任务时：

1. 先区分当前代码、主规格、活动变更和历史资料。
2. 身份/权限/迁移问题先只读检查真实 schema、routes、Compose 和运行链路。
3. 不把“使用 MCP”解释成删除 RBAC、Secret、发布或审计。
4. 不恢复旧 API Platform、任意 HTTP、Shell、动态 Tool 或 Application Resource Mapping。
5. ONES 身份修改必须验证本人/管理员边界和敏感字段不持久化。
6. Runtime 问题必须沿 Ingress -> Outbox -> Queue -> Job -> Worker -> Runtime -> MCP -> Delivery 取证。
7. 修改后运行聚焦测试、类型检查、OpenSpec strict validation 和残留扫描；不能把配置存在当作 E2E 成功。

权威入口：根 [README](../../README.md)、[tool-mcp](../tool-mcp.md)、活动 OpenSpec 和当前实现。
