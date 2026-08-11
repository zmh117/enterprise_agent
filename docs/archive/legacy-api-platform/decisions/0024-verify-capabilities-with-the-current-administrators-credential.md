# 使用当前管理员自己的凭据验证 API Capability

执行 Connection 或 Capability Verify 的授权管理员使用自己已绑定的外部身份、默认 Team 和 External API Credential 完成真实调用；首个 Connection 没有可绑定发布版本时，仅按 ADR-0029 执行临时启动验证，发布后仍须正式绑定才能验证 Capability。平台不再维护独立 Verification Credential；管理员 Token 只在验证请求中解析，不进入 Handler、Capability Release 或真实 Agent Job。发布证据只保存验证人、Team、时间、结果摘要和 Hash，其他用户运行时始终使用自己的 User ID、默认 Team 和凭据。本决定取代 ADR-0009。
