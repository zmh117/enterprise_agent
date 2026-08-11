# 使用受治理的声明式 Capability Handler

管理员可以配置并发布由 HTTP Method、相对路径、请求字段映射和响应字段映射组成的 Capability Handler，但 Handler 必须选择平台提供的固定代码 Executor 和已发布 API Connection。平台禁止完整请求 URL、动态主机、任意代码、脚本、SQL 和直接 Secret Header；发布版本不可变。这个方案在无需每个业务接口都重新部署代码的同时，把网络出口、凭据注入和执行能力限制在可验证的治理边界内。
