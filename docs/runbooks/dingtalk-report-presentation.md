# 钉钉报告排版与分片恢复

本说明记录 `fix-dingtalk-report-presentation` 在 Prompt v8 引入的分片与呈现方案。
后续模板已迭代：v10 起多条可比较记录优先使用 Markdown 表格，当前版本以
`backend/app/shared/tool_contract.py` 和对应 Runtime 代码为准，部署不要固定检查 v8。
版本不一致时参见[Worker / Runtime 版本核对](runtime-prompt-version-drift.md)。
真实模型遵循情况和钉钉客户端显示效果需在部署后验收。

## v8 回复格式（历史说明）

Worker 从 Job 冻结的回复路由生成 `response_presentation=dingtalk-markdown`。
Runtime 根据这个标识加入钉钉专用指引，不根据用户问题或 Skill 中的“钉钉”字样判断渠道，
也不将接收者、Webhook 地址或凭据投影到这个标识中。

- 使用 `###` 小标题、空行、短列表和少量有意义的 emoji。
- 每条记录保留编号和完整标题，状态、日期、相关原因分成短行；记录之间留空行。
- 普通问题先回答结论和高度相关证据，避免先输出冗长的检索过程或全部命中记录。
- 明确要求完整清单时仍保留所有符合范围的记录，超过长度交给投递分片处理。
- 保留原始状态及不确定性；`Closed` 不能被改写为“已发布”，emoji 不能替代证据。
- 钉钉消息不依赖 GFM 管道表。Web 及另行生成的 Markdown 文件仍可以使用表格。

合成示例（不是业务记录或真实模型输出）：

```markdown
### 🔎 检索结论
找到两条与描述相关的历史记录，是否属于同一原因仍需核实。

### 相关记录
**SYN-001｜合成问题的完整标题**
- 状态：Closed；发布情况：未核实
- 相关点：描述中包含相同的操作顺序。

**SYN-002｜另一条合成问题的完整标题**
- 状态：处理中
- ⚠️ 待确认：版本与复现条件是否一致。
```

这些是 Prompt 指引，不是确定性的 Markdown 重写器。投递层保留模型正文，不删除粗体、
标题或 emoji；用户要求的格式和实际源记录仍需由模型正确理解。

## 长报告与重试

新文本投递采用 `paragraph-v1`：优先在空行、其次在换行处切分；单段过长时硬切。
正文不做 `strip` 或改写。默认上限为 3500 个字符，新增 `part x/y` 前缀也计算在内。
这个上限按 Python 字符数计算，不是字节数；超长行中的 Markdown 标记仍可能被硬切。

首次调用外部投递前，Dispatcher 在当前 claim 下将算法版本和长度保存到
`delivery_outbox.delivery_binding_json.text_chunking`。后续重试使用同一计划，跳过已成功
分片；修改默认长度不会改变在途任务。系统说明消息也使用相同机制，文件附件不走此路径。

升级前已产生 `delivery_chunk`、但尚无计划的任务，会根据第一片已有的字符数和总片数恢复
`fixed-v1` 固定字符切法，保留原先的前缀长度行为。无法恢复时返回
`delivery_chunk_plan_invalid`；内容 hash 不一致仍返回 `delivery_chunk_payload_drift`。
不能通过删除成功分片、清空计划或覆盖 hash 来绕过这些检查。

Provider 已收件但成功记录尚未落库时，仍受原有至少一次投递边界约束，本次修复不提供
外部收件的 exactly-once 保证。

## 更新服务与验收

本地 Compose 的相关服务是 `agent-worker`、`python-agent-runtime-a`、
`python-agent-runtime-b` 和 `delivery-dispatch-worker`。部署时处理完在途模型调用，
再协调更新为同一代码版本的镜像；只改 Runtime 或只重启 Worker 会留下 Prompt 版本不匹配。
退回旧投递镜像前，应先完成使用新分片计划的在途投递。

不需要数据库迁移、知识库重新分块或索引，也不需要更改 MCP Schema 或 Runtime 协议。
更新只影响后续生成的回复；重投递旧报告不会重新排版其已保存的正文。

本地验证使用合成记录、内存数据库和假钉钉传输，覆盖渠道隔离、全文无损、长度边界、
配置变化重试、历史分片恢复、失效 claim、未知计划及 hash 漂移拒绝，并检查相关文件投递和
Runtime 协议回归。这些测试不证明真实模型必然遵循，也不证明客户端排版已经验收。

部署后用新请求检查短回复、长明细、完整清单和文件报告；核对 Worker 请求与 Runtime 观测
版本与本次发布一致，并在真实钉钉客户端确认小标题、分行、图标和连续分片。无需为此读取或输出
生产凭据、原始业务消息。

## 实现与主规格差异

Canonical `execution-delivery/spec.md` 当前仍记录 Prompt v7，实际模板版本已继续迭代。v8 呈现规则和稳定分片
已记录在 [变更规格](../../openspec/changes/fix-dingtalk-report-presentation/specs/execution-delivery/spec.md)，
本次未同步或归档主规格，也未将本地回归写成生产验收。
