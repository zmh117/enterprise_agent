# 只持久化有界的规范化 Capability Output

外部 HTTP 原始响应只在当前调用内存中存在，Mapping Plan 完成后立即丢弃，不进入数据库、日志、审计、错误或模型上下文。只有通过 Capability Output Schema 校验并满足数组、字段和总大小限制的 Normalized Capability Output 可以提供给 Agent 和 Tool Call 响应摘要；Audit 仅保留版本、主体、Team、状态、耗时、结果数量和摘要 Hash。
