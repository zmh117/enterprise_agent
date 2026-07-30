# Handler 验证凭据与运行时用户凭据完全隔离

每个 API Connection 可以配置一个权限受限的 Verification Credential 和固定测试范围，用于 Handler 的真实 Verify/Test。配置时通过外部登录获取 Token 并立即丢弃密码；验证凭据加密保存，不能进入真实 Agent Job，也不能作为用户 External API Credential 的回退。验证记录只保存状态和脱敏摘要，不持久化完整外部响应。
