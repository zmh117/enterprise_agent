# ONES User ID 和默认 Team 来自当前用户绑定

用户验证 ONES 时，平台从登录响应提取 User ID、Token 和已验证 Team 集合；如果存在多个 Team，用户必须选择一个默认 Team。第一版每个内部用户最多存在一个当前有效的 ONES 账号绑定，不提供 ONES 实例选择。外部身份绑定保存 User ID、已验证 Team 和默认 Team，外部凭据单独加密保存 Token。API Capability、Handler 和业务应用配置不保存 User ID 或 Team ID；运行时始终从当前钉钉发送人的绑定中安全注入这些值。本决定取代 ADR-0006。
