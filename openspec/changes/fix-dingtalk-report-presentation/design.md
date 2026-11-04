## Context

当前 Prompt v7 的完整明细要求没有渠道呈现指引；ReportChunker 按字符硬切。Delivery 根据片号和 payload hash 防重发，不能在重试中更换分片规则。当前工作区另有 Compose 整合，保持独立。

## Goals / Non-Goals

**Goals:** 钉钉消息使用清晰段落和少量状态图标；保留授权范围内用户要求的完整记录；分片无损、长度有界、重试稳定。

**Non-Goals:** 不新增卡片/表格渲染器，不改知识检索，不发真实消息，不部署或重建容器，不保证模型必然遵从提示。

## Decisions

1. AgentContextBuilder 从冻结的 reply_route 生成仅含格式标识的 response_presentation，放入已有 retrieved_context；不传目标、凭据或 webhook。Runtime 只在明确钉钉标识下加入专用指引，不根据用户文字猜渠道。协议结构无需扩展。
2. v8 仍要求长标题完整、明确请求全量时不省略；普通问题先结论再高度相关证据。钉钉记录分成 2–4 个短行并留空行，少量 emoji 只能表达已证实状态。Web 与文件报告仍可用表格。
3. 分片优先空行，其次换行，最后硬切；不 strip、不改变正文；正文和分片前缀合计不超过单片字符上限。超长单段仍可能被拆开，不引入 Markdown 解析器。
4. 第一次发送前在现有 delivery_binding_json 中固定 text_chunking 的算法版本和长度，通过现有 claim token 条件更新。已有计划只读取，不跟随运行配置；未知版本失败关闭。没有计划但已有历史分片记录时，从第一片持久的字符数/片数恢复固定字符算法。恢复信息不足则安全失败，不覆盖成功记录。
5. 保留现有 payload hash 漂移检查。此方案不新增表、迁移或正文副本，也不修改 Job 和发布快照。

## Risks / Trade-offs

- Prompt 不等于渲染证明：合成回归和真实钉钉新消息分别验收。
- 在途模型调用存在版本门禁：更新 Worker 和所有 Runtime 副本，先处理在途调用；切片由 delivery-dispatch-worker 应用。
- 钉钉只按已验证 Markdown 子集设计；历史固定字符任务保留旧的前缀长度行为。
- 没有任何持久分片记录的旧任务无法证明 Provider 已收件，沿用原来至少一次投递的边界。

## Migration Plan

无需数据库迁移。协调更新 agent-worker、全部 python-agent-runtime 副本和 delivery-dispatch-worker；不改 MCP 工具合同，不要求知识重建。已有分片任务用持久计划恢复；退回不识别新计划的旧投递镜像前需先完成在途投递。真实客户端排版验收另行记录，不在本次本地修复中假称完成。
