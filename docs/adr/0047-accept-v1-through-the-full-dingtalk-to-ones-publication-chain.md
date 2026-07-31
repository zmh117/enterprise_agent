# 第一版按完整钉钉到 ONES 发布链验收

第一版 Definition of Done 必须覆盖：管理员完成首个 ONES Connection 启动验证与发布；管理员正式绑定自己的 ONES 账号并选择默认 Team；管理员配置、测试、验证并发布 `cap__ones__work_item__search`；Agent 选择该精确 Release 并发布；应用选择该 Agent 且只能配置 Agent 能力上限的子集，绑定钉钉应用后发布；普通钉钉用户绑定自己的 ONES 后发送查询，运行时使用该用户的 User ID、默认 Team 和 Token 返回规范化工作项。负向场景必须证明 Agent 未选时应用不能配置、应用未选时模型不能调用，以及未绑定、Token 失效、Team 权限撤销和 Release 禁用均失败关闭且不切换主体或 Team。回归场景必须证明现有内部 Tool 和未升级的 Agent/Application Publication 行为不变；测试专用双 Capability Fixture 另行证明 Agent 组合输入链路。
