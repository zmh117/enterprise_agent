# ONES Capability 只使用当前消息发送人的凭据

每个 Capability Handler 必须声明凭据主体策略。ONES 查询第一版固定使用 `CURRENT_ACTOR`：私聊和群聊都按当前消息发送人解析内部用户、外部身份及加密 Token；群会话不共享任一成员的凭据。凭据缺失或失效时调用失败关闭，不回退平台服务账号。无人触发场景未来若需服务账号，必须使用显式声明 `SERVICE_ACCOUNT` 的独立 Capability 配置。
