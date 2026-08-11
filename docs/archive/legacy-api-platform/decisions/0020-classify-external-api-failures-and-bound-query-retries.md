# 分类外部 API 失败并限制查询重试

ONES `401` 不重试并使当前用户 External API Credential 失效；`403` 表示外部授权不足但不自动失效 Token。`400/404`、响应过大、无效 JSON 和 Schema 不匹配属于确定性失败，不重试。仅 `QUERY` 的网络错误、超时、`429/502/503/504` 最多进行两次受总超时约束的退避重试。所有 External Call Attempt 共享 Job、Tool Call 和 Correlation 标识并记录脱敏结果。
