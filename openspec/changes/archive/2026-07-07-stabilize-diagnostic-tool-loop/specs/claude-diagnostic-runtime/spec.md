## ADDED Requirements

### Requirement: 诊断上下文必须包含目标 schema 目录
系统 SHALL 在诊断上下文中提供目标 environment/base/workshop 可访问的 schema 目录或明确说明无法唯一解析目标。schema 目录 MUST 来自 Internal API Platform，只包含按权限和 topology 过滤后的表、列和非密钥元数据。

#### Scenario: 单一目标问题预取 schema
- **WHEN** 用户问题能从 addressing 目录唯一解析到一个 partitioned workshop
- **THEN** Agent context 包含该 workshop 的 schema 目录摘要，供模型生成 SQL 前检查可用表和字段

#### Scenario: 目标不明确时不猜 schema
- **WHEN** 用户问题不能唯一解析 environment/base/workshop
- **THEN** Agent context 要求模型先解析目标或报告目标不明确，不得猜测不存在于 addressing 目录的目标代码

### Requirement: 诊断运行时必须停止缺证据试错
系统 SHALL 指示真实模型在 schema 不足、表不存在、字段不存在、连续策略拒绝、空结果无法支撑结论或关键业务字段缺失时停止扩散式工具试错，并输出“不具备诊断证据”的报告。最终报告 MUST 明确列出已经验证的限制条件和安全下一步。

#### Scenario: schema 中没有订单表或订单字段
- **WHEN** schema 目录不包含可用于按订单号查询的表或字段
- **THEN** Agent 不得继续猜测 `mo`、`order`、`production_order` 等未列出的表名，并必须报告当前数据结构不足以诊断该订单

#### Scenario: 工具连续返回结构化拒绝
- **WHEN** 数据库工具连续返回表不存在、字段不存在、跨 workshop、非 SELECT 或 schema 不可用等结构化拒绝
- **THEN** Agent 必须停止新的相邻表名尝试，并产出证据不足报告

#### Scenario: 缺证据报告仍遵循只读诊断格式
- **WHEN** Agent 因缺少可用证据而停止
- **THEN** 最终报告包含结论、已验证证据、限制/不确定性和非变更类下一步，不建议 Agent 执行写操作或自动修复
