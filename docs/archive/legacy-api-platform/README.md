# 已退役 API Platform 历史

这里保存 API Capability、Handler、API Connection、Resource Mapping、个人 API Token 和旧工具发布平台的历史 ADR，仅用于审计设计演进。

这些文档不再描述当前实现。当前工具路径使用标准 MCP：`Worker -> Runtime -> tool-mcp -> Resource`。协议替换没有删除身份、RBAC、应用发布、资源发布、Secret、审计或 Job 历史治理。ONES 本人身份绑定也独立保留，不属于旧 API 调用凭据。

新实现不得恢复归档中的通用 HTTP Executor、动态 Handler、长期个人 API Token 或旧 Runtime 签名密钥。当前有效决策见 [当前 ADR](../../reference/decisions/README.md)。
