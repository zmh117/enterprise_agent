# 区分应用发布就绪与用户 Capability 可用状态

业务应用发布验证所选 Capability 是 Agent Capability Envelope 的子集，并验证 Capability、Handler、Connection、最近验证结果和治理授权，不保存或枚举未来用户及其 Team。钉钉调用先按 ADR-0039 计算 DingTalk Application Access；再按当前内部用户计算 User Capability Availability，包括应用访问、Agent 能力上限、应用能力子集、Release 运维状态、外部身份、默认 Team 和有效凭据。个人能力不可用只阻止该用户，不使整个应用 blocked。
