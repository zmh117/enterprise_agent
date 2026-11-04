## Why

当前 Runtime v7 对长标题强调编号明细，但缺少钉钉消息的阅读结构；投递按字符硬切可能拆开记录和 Markdown 标记。需要改善消息可读性，同时保留完整明细、原始文本和投递幂等性。

## What Changes

- 根据 Job 已冻结的回复路由选择钉钉呈现指引，使用小标题、适量状态 emoji、分段记录；其他输出不禁止表格。
- Prompt 升至 v8，Worker 与所有 Runtime 副本同步更新；不改变 MCP Schema 或 Runtime 协议。
- 新文本投递优先在段落、换行边界分片，超长单段保留有界硬切；计算包含分片前缀的最终长度。
- 首次投递前持久化分片版本和长度，重试沿用；已存在分片记录的任务按原固定切片恢复。
- 使用合成回归验证，不访问生产原文，不发送真实钉钉消息。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `execution-delivery`：钉钉呈现指引、Prompt v8、文本无损分片和重试固定分片规则。

## Impact

影响 Agent Context、Runtime Prompt、Delivery 分片/持久层、相关回归及运维说明。不需要数据库迁移，不重建知识索引；与正在进行的 Compose 整合独立。
