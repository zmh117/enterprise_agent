## ADDED Requirements

### Requirement: 管理 Web 重新加载获取当前入口版本
管理 Web 的入口 HTML SHALL 返回禁止存储的缓存策略，带哈希的静态资源路径 MUST 只返回实际资源；缺失的 JS 或 CSS 不得回退到 HTML。部署验收 SHALL 检查 HTTP 响应和真实浏览器重新加载后的页面能力。

#### Scenario: 部署新的 Webhook 表单
- **WHEN** 更新 admin-web 镜像后重新加载渠道页面
- **THEN** 获取当前入口 HTML 与资源，不持续使用旧创建表单
