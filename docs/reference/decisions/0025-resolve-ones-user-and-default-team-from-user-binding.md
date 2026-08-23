# ONES User ID 和默认 Team 来自当前用户绑定

> 状态：部分被当前实现取代。User ID/Team 身份事实仍有效；“邮箱、密码、Token 不入
> Challenge/数据库”已失效。当前实现使用加密 Challenge，并在确认后写入加密的
> `external_identity_credential`。正文保留历史决策语境。

用户验证 ONES 时，平台从本次登录响应提取 User ID 和已验证 Team 集合；如果存在多个 Team，用户必须选择一个默认 Team。第一版每个内部用户最多存在一个当前有效的 ONES 账号绑定，不提供 ONES 实例选择。

外部身份绑定只保存 ONES User ID、显示名称、已验证 Team、默认 Team 和验证时间。邮箱、密码和登录响应中的任何 Token 都只能用于本次验证，不写入数据库、日志、审计或 Challenge。ONES 身份事实独立于 MCP 和已退役的 API Platform，不自动成为工具调用凭据。本决定取代 ADR-0006 中的旧 Capability 绑定语义。
