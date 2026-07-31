# 首个 Connection 使用管理员临时自验证解除启动循环

首个 ONES Connection 尚无 Published Connection Revision，管理员无法先建立正式绑定，因此 Connection Verify 允许拥有 `api_connections.verify` 的当前管理员临时输入自己的 ONES 邮箱和密码。服务端只在该请求内验证 Draft 的固定 Origin、登录协议、User/Team/Token 提取和认证 Header 注入，随后丢弃密码与 Token，不创建身份绑定、外部凭据或运行时回退账号。验证通过后才可发布 Connection Revision；管理员随后必须使用该发布版本完成正式两阶段绑定，保存自己的外部 User ID、默认 Team 和加密 Token，之后才能测试、验证或发布 API Capability。
