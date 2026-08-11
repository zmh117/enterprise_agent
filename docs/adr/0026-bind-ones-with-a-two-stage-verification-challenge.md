# ONES 绑定使用两阶段 Verification Challenge

用户先提交邮箱和密码，由服务端完成一次 ONES 身份验证，并创建绑定当前内部用户的短时、单次 Verification Challenge；当前内部用户只能来自认证会话，客户端不得传入其他目标用户。Challenge 与浏览器只包含安全的 User/Team 候选、验证时间和 Challenge ID，不包含邮箱、密码或 Token。

用户选择候选集合中的默认 Team 后，服务端原子保存 User ID、显示名称、已验证 Team、默认 Team 和验证时间。邮箱、密码和登录 Token 在第一阶段完成后立即丢弃；确认绑定前不修改既有身份事实。
