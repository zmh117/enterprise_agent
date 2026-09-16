## ADDED Requirements

### Requirement: 完整明细输出必须包含平台级模型约束
系统 SHALL 在统一 Runtime 系统 Prompt 中注入明细输出规则，不依赖业务 Skill。规则 MUST 要求模型在用户请求记录清单或完整明细时列出授权且已获取的符合条件记录，保留所需标识和完整标题，不能用省略号、其余略或样例替代；用户明确要求汇总、前 N 条或样例时遵守其范围。此 Requirement 约束 Prompt 的内容与作用范围，不将模型自检等同于程序级完整性保证。

#### Scenario: 无业务 Skill 的明细请求
- **WHEN** Runtime 为没有启用业务 Skill 的 Job 构造系统 Prompt
- **THEN** Prompt 仍包含完整列出、禁止人为省略、数量与稳定 ID 自检以及部分结果说明规则

#### Scenario: 获取数量与筛选数量不同
- **WHEN** 工具获取 29 条，用户条件筛选后为 20 条
- **THEN** Prompt 要求模型核对并列出筛选后的 20 条唯一记录，区分获取数和展示数，不把“工具无截断”当成“回复已完整”的证明

#### Scenario: 上游或输出限制导致不完整
- **WHEN** 结果有截断、工具返回只读结果文件尚未完整读取，或预算不足以完整回答
- **THEN** Prompt 要求在既有授权和预算内继续读取；仍无法完成时报告已获取/已展示数量及原因，不称为完整明细，不补造记录

#### Scenario: 长标题和原文中的省略号
- **WHEN** 记录标题很长或本身含省略号
- **THEN** Prompt 要求优先用编号列表保留完整原文；不新增基于省略号的正则拒绝或删改，支持分片的渠道继续使用既有长报告投递机制

### Requirement: 明细输出约束必须可识别验证边界
系统 SHALL 对新的输出约束使用新 Prompt template version，并用合成数据验证无 Skill/跨工具注入及明细文本经过现有分片时无损。测试结果 MUST 区分 Prompt/分片回归与真实 Provider/模型验收，MUST NOT 回写历史 Job 的 Prompt 观测版本。

#### Scenario: 新版本 Prompt
- **WHEN** 新构建准备新 invocation
- **THEN** 当前 Prompt template version 为 v7，Worker 请求和 Runtime 观测保持一致；MCP Schema 和 Runtime 协议保持原值

#### Scenario: 长清单投递回归
- **WHEN** 包含 20 条唯一编号和长标题的合成清单超过单片长度
- **THEN** 分片按序重组后与原清单完全一致，不遗漏、替换或重复任何记录；该测试不冒充真实模型已遵循规则的证据
