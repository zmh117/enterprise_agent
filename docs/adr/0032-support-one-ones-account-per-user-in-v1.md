# 第一版每个用户只支持一个 ONES 账号

第一版暂不考虑多个 ONES 实例，只治理一个逻辑 ONES Connection；所有 ONES API Capability 复用该 Connection 的已发布版本。每个内部用户最多存在一个当前有效的 ONES 外部身份、默认 Team 和个人 Token，绑定界面不提供实例选择器。用户仍可拥有多个已验证 Team，但必须选择一个默认 Team。多 ONES 实例和同一用户多份 ONES 账号绑定明确延期，不在本变更中预建对应交互或运行时选择逻辑。
