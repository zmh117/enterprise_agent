# 07 实现状态

当前代码具备双 Runtime、标准 `tool-mcp`、MCP Manifest/Envelope、应用显式 Tool 子集、动态 Tool Call 目标、工具资源与 Secret、统一身份/RBAC、渠道和 Job/Delivery 历史。

旧 API Capability、Handler、Connection、Resource Mapping、Tool Release 控制面和 Internal API Platform 已从活动实现移除。ONES 身份绑定被保留为独立统一身份能力，不依赖旧业务调用凭据。

验收状态以活动 OpenSpec 的 `tasks.md`、测试输出、Compose 配置和真实 Runtime 链路证据为准；历史完成度数字不作为当前事实。
