# 允许 API Connection 显式使用明文 HTTP

HTTPS 继续作为 API Connection 的默认传输，但企业内网和本地 ONES 可能只提供 HTTP。管理员可以在单个 Connection Draft 中显式启用 `allow_plain_http`；未启用时任何环境的 HTTP Origin 都失败关闭，启用后开发、测试和生产环境可以验证、发布并调用该固定 Origin。授权进入 Draft 内容 Hash 和不可变 Connection Revision，管理界面必须警告密码、Token 和业务数据可能被窃听或篡改；HTTPS Connection 会把该字段规范化为 false。

固定 Scheme、Host、Port、相对路径、同 Origin 认证传播、跨 Origin 重定向拒绝、超时和响应大小限制保持不变。明文 HTTP 授权不表示关闭 HTTPS 证书校验，也不表示已实现 Network Zone、CIDR、DNS 重绑定或完整 SSRF 防护。

升级期后端接受旧输入字段 `allow_insecure_local_http`，但新 API、UI、持久化列和发布快照统一使用 `allow_plain_http`。本决定取代既有 OpenSpec 与运维文档中的“生产 API Connection 必须使用 HTTPS、HTTP 仅限本地 Mock”约束，不改变 Web 管理会话、Cookie 或其他 Provider 独立规定的 HTTPS 要求。
