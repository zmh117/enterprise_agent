# 第一版每个用户只支持一个 ONES 账号

> 状态：单一当前 ONES 身份/默认 Team 仍有效；“不包含个人 Token、未来再设计 ONES
> MCP”已失效。当前每个身份可关联一份加密 ACTIVE credential，供固定只读 ONES Tool。

第一版暂不考虑多个 ONES 实例。每个内部用户最多存在一个当前有效的 ONES 外部身份和一个默认 Team，绑定界面不提供实例选择器。用户仍可拥有多个已验证 Team，但必须选择一个默认 Team。多 ONES 实例和同一用户多份 ONES 账号绑定明确延期，不在本变更中预建对应交互或运行时选择逻辑。

该身份模型不包含 API Connection、Capability 或个人 Token；未来 ONES MCP 的工具调用凭据必须独立设计。
