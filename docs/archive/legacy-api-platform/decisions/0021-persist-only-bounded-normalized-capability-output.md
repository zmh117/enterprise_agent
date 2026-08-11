# 只持久化有界的规范化 Capability Output

外部 HTTP 原始响应只在当前调用内存中存在，Mapping Plan 完成后立即丢弃，不进入数据库、日志、审计、错误、模型上下文或测试页面。只有通过 Capability Output Schema 校验并满足数组、字段和总大小限制的 Normalized Capability Output 可以提供给 Agent、Capability Test Preview 并正常保存到 Tool Call 结果，Agent 最终回复按现有 Job 和会话模型正常保存；Audit 仅保留版本、主体、Team、状态、耗时、结果数量和摘要 Hash。规范化输出的数据分级和访问边界遵循 ADR-0030。
