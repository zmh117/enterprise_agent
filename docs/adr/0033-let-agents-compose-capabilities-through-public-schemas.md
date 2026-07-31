# Agent 通过公开 Schema 组合多个 API Capability

API Capability Revision 的 Input Schema 允许配置字段名称、类型、说明、必填性、枚举、默认值以及字符串、数值、对象和数组边界。Agent 可以根据用户消息、会话上下文或前一个 Capability 的 Normalized Capability Output 组织另一个 Capability 的结构化输入；平台不建立 Handler 到 Handler 的隐式流水线，也不透传原始外部响应。每次调用都必须独立校验 Input Schema、应用访问、Agent Capability Envelope、Application Capability Allowlist、用户能力可用状态、外部身份和凭据。User ID、默认 Team、Token 等系统上下文字段不属于 Agent 可写输入。规范化外部文本仍是不可信业务数据，不能提升为系统、开发者或 Tool 指令。第一版只用测试专用的双 Capability Fixture 证明组合机制，生产验收仍保持单个 `ones.work_item.search`。
