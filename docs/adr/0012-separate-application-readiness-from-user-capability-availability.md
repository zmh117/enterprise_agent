# 区分应用发布就绪与用户 Capability 可用状态

业务应用发布只验证 Capability、Handler、Connection、固定 Team、Verification Credential 和治理授权，不要求所有未来用户都已绑定 ONES 或持有有效 Token。每次调用再按当前内部用户计算 User Capability Availability，包括外部身份、Team、有效凭据、角色和能力授权。个人能力不可用只阻止该用户，不使整个应用 blocked。
