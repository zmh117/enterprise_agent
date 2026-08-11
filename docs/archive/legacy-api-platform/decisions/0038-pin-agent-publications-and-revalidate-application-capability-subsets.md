# 应用冻结 Agent Publication 并在升级时重验能力子集

Agent 新增、移除或升级 Capability 时必须创建不可变 Agent Publication，并冻结其 Agent Capability Envelope；既有 Application Publication 不自动解析最新 Agent。应用引用精确 Agent Publication，并冻结从该版本上限中选择的 Application Capability Allowlist。应用升级到新 Agent Publication 时必须重新校验原能力子集；如果新 Agent 缺失原 Capability、只提供 DEPRECATED Release 或公开 Schema 不兼容，阻止应用发布并要求管理员明确替换或移除。平台不得静默删除应用能力、自动选择替代 Release 或改写既有 Application Publication。
