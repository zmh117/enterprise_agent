# 区分应用发布就绪与用户 Capability 可用状态

业务应用发布只验证 Capability、Handler、Connection、最近验证结果和治理授权，不保存或枚举未来用户及其 Team。每次调用再按当前内部用户计算 User Capability Availability，包括外部身份、默认 Team、有效凭据、角色和能力授权。个人能力不可用只阻止该用户，不使整个应用 blocked。
