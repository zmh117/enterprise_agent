# 延期完整 Network Zone，但保留 Connection Origin 边界

第一版不实现 Network Zone、CIDR 和完整 DNS/IP 出口治理，但每个 API Connection 必须固定 Scheme、Host 和 Port。Handler 只能配置该 Origin 下的相对路径，用户 Token 只能发送到被冻结的 Origin，跨 Origin 重定向必须拒绝。该边界避免声明式 Handler 任意转发用户凭据；同时本变更明确不声称已经解决通用 SSRF，完整 Egress Policy 留待后续变更。
