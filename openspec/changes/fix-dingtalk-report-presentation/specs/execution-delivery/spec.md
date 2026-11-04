## ADDED Requirements

### Requirement: 钉钉回复使用渠道专属的可读呈现指引
系统 SHALL 从 Job 冻结回复路由生成非敏感格式标识，仅为钉钉最终消息添加小标题、适量状态 emoji、短列表和独立记录段落的指引。单条长记录 SHALL 分行呈现标识/完整标题、状态和相关原因，不强制挤成一行。普通查询先给相关结论；用户明确要求全量明细时 MUST 保留已有完整性规则。表格限制 MUST 不影响 Web 或另行生成的 Markdown 文件；源记录和用户文字不得改变渠道选择。

#### Scenario: 钉钉长明细
- **WHEN** 冻结回复路由为钉钉，用户请求完整记录清单
- **THEN** Prompt 要求保留全部符合范围的标识和完整标题，以独立段落、短行和已证实状态呈现，不用省略或泛化状态图标替代内容

#### Scenario: 非钉钉输出
- **WHEN** 回复路由不是钉钉，即使输入或 Skill 中包含钉钉字样
- **THEN** 系统不注入钉钉专用禁用管道表规则；文件报告仍按用户要求选择格式

## MODIFIED Requirements

### Requirement: 明细输出约束必须可识别验证边界
系统 SHALL 对新的输出约束使用新 Prompt template version，并用合成数据验证无 Skill/跨工具注入及明细文本经过现有分片时无损。测试结果 MUST 区分 Prompt/分片回归与真实 Provider/模型验收，MUST NOT 回写历史 Job 的 Prompt 观测版本。

#### Scenario: 新版本 Prompt
- **WHEN** 新构建准备新 invocation
- **THEN** 当前 Prompt template version 为 v8，Worker 请求和 Runtime 观测保持一致；MCP Schema 和 Runtime 协议保持原值

#### Scenario: 长清单投递回归
- **WHEN** 包含 20 条唯一编号和长标题的合成清单超过单片长度
- **THEN** 分片按序重组后与原清单完全一致，不遗漏、替换或重复任何记录；该测试不冒充真实模型已遵循规则的证据

### Requirement: Long reports are delivered in chunks
系统 SHALL 在最终报告超过目标平台单条消息限制时，将报告分片发送并持久化每个分片状态。新任务 SHALL 优先在段落、换行处切分，超长单段才有界硬切，保留正文所有字符；单片正文连同 part 前缀 MUST 不超过固定字符上限。首次发送前 MUST 固定算法版本和长度，后续重试不随运行配置或默认算法变化。

#### Scenario: Report exceeds DingTalk chunk limit
- **WHEN** DingTalk delivery 的报告长度超过配置的单片字符限制
- **THEN** 系统按顺序发送多个分片，每片包含 `part x/y` 标识，并记录每个 delivery chunk

#### Scenario: Report fits in one chunk
- **WHEN** 报告长度未超过目标平台单片字符限制
- **THEN** 系统发送一个分片并将 delivery attempt 标记为成功

#### Scenario: 持久分片计划跨重试保持一致
- **WHEN** 第一片已成功而后续片暂时失败，重试进程的默认长度不同
- **THEN** 系统使用原计划重建相同片号与内容 hash，跳过已成功片，不重跑 Agent

#### Scenario: 恢复升级前已部分投递的报告
- **WHEN** 旧任务没有计划但已有第一片的持久字符数与片数
- **THEN** 系统恢复原固定字符分片并固定该计划；不足以恢复时失败关闭，不改写成功片
