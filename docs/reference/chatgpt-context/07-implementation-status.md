# 07 实现状态

当前代码以 Python 作为唯一 Agent Runtime，具备标准 `tool-mcp`、身份感知
`ones-mcp`、File MCP、MCP Manifest/Envelope、应用显式 Tool 子集、调用时目标、工具
资源与 Secret、统一身份/RBAC、受管钉钉渠道、Task Workspace/Docling 和
Job/Delivery 历史。历史 `typescript-v1` 记录保持原值并只读展示。

旧 API Capability、Handler、Connection、Resource Mapping、Tool Release 控制面和
Internal API Platform 已从活动实现移除。ONES 当前凭据由独立加密 credential 模型提供，
不依赖旧 API Platform。

Canonical spec 表示已接受契约，不自动证明运行能力。实现状态必须核对当前代码、
migration `119`、测试、Compose 和真实 Runtime 链路；active change 的 `tasks.md` 只是该
change 的工作记录，不能覆盖 canonical baseline 或代码事实。当前已知未闭环项包括：
真实 ONES Provider 双 Tool 兼容验收，以及覆盖全部密文域的 Master Key 重加密工具。
