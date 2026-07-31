# 钉钉应用访问来自路由命中和启用用户身份

第一版 DingTalk Application Access 不设置额外应用用户白名单或访问角色。钉钉消息命中绑定活动 Application Publication 的连接器，且实际发送人能够解析为已启用内部用户时，即取得该应用访问权，并获得 Application Capability Allowlist 的运行时调用资格。群聊按每条消息的实际发送人独立判断，不存在群级共享主体。未绑定钉钉身份或内部用户已停用时拒绝访问并返回安全中文提示；应用未配置或用户 ONES 凭据不可用的 Capability 仍不得暴露或执行。该决定只定义钉钉入口，不扩大其他 Trigger 类型的访问模型。
