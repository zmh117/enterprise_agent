## Why

知识库命中只是历史片段，修复是否生效、现场是否换包、问题是否重开常见于 ONES 评论。当前 Agent 仅按需读取评论，消息接口也只取一页，可能遗漏影响结论的证据。

## What Changes

- 知识库命中后的故障分析，对采用的相关 ONES 工作项读取最新详情和评论时间线，区分历史线索、当前来源记录和现场根因。
- **BREAKING** 消息工具仅接受工作项 UUID；服务端按 ONES 已公开的 count/max 微秒时间戳协议自动有界分页，不再接受模型 limit 或游标。
- 明确返回消息收集数量、覆盖范围、条目/正文截断信息；沿用 Job 只读临时结果文件，未完整读取必须告知用户。
- 详情补充描述及关联摘要截断标记。保留现有授权、敏感信息过滤及外部不可信数据边界。
- 更新 Skill、工具合同、Prompt、回归测试，并更新相关容器及 assist03 发布。

## Capabilities

### New Capabilities

无新增领域。

### Modified Capabilities

- `builtin-tool-resource`: 明确知识库命中后的相关 ONES 证据核验流程。
- `governed-api-capability`: 消息自动分页与详情/消息完整性合同。

## Impact

ONES REST Provider、消息工具合同与服务、Runtime 结果文件桥、知识检索提示、ones-query/bug-analysis Skill、相关测试及部署。无需数据库迁移，不改知识库采集范围和业务权限。
