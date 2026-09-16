## Why

用户收到的清单声称包含完整明细，却以省略号替代部分记录。现有平台 Prompt 强调证据摘要，未明确区分查询完整与回答完整；仅依赖特定业务 Skill 不适合约束跨工具的通用明细输出。

## What Changes

- 在平台统一系统 Prompt 中加入明细输出规则：完整列出授权结果中符合条件的记录，不省略条目、编号或标题；输出前按稳定标识自检数量、重复和遗漏。
- 区分完整数据、已筛选集合和实际展示条数；不能完成时明确说明部分结果，禁止把摘要或样例称为完整清单。
- 长标题优先编号列表；超长回复继续使用既有分片，不因为单条消息长度自行省略。用户明确只要汇总、样例或前 N 条时尊重该范围。
- 升级 Prompt template version，补充无 Skill/跨工具 Prompt 回归和长清单无损分片验证。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `execution-delivery`：新增平台级完整明细输出 Prompt 约束及其验证边界。

## Impact

修改 Python Runtime 的统一 Prompt、共享 Prompt 版本常量和相关测试。不改 Skill、ONES 查询/分页、MCP Schema、Runtime 协议、数据库或权限。此方案属于代码化模型行为约束，不是程序级完整性硬校验；不添加自由文本正则拦截、自动补造记录或新输出协议。真实模型表现需独立验收，不用合成测试冒充现场修复证明。
