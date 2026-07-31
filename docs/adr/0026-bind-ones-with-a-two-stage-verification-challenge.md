# ONES 绑定使用两阶段 Verification Challenge

用户先提交邮箱和密码，由服务端调用 ONES 登录并创建绑定当前内部用户和 Connection Revision 的短时单次 Verification Challenge；当前内部用户只能来自认证会话，客户端不得传入其他目标用户。浏览器只收到安全的 User、Team 候选和 Challenge ID，不收到 Token。用户选择候选集合中的默认 Team 后，服务端原子保存 User ID、已验证 Team、默认 Team 和加密 Token。密码在第一阶段结束后立即丢弃，确认绑定前不修改既有身份或凭据。
