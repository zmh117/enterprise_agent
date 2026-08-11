# Agent 选择精确 Capability Release，应用只选择其子集

一个 Agent Publication 对同一稳定 Capability Code 最多选择一个精确的 `ACTIVE` Release。Agent 配置默认推荐最新 `ACTIVE` Release，但管理员可以展开版本列表选择仍活动的旧 Release；`DEPRECATED` Release 只在既有引用中显示警告，不能用于新 Agent 配置。Application 配置不提供独立版本选择器，只能勾选所选 Agent Publication 已冻结的 Capability Release，从而避免 Agent 与应用版本不一致。Agent 和应用的选择界面都必须展示 Capability 名称、稳定 Code、业务 `description`、Release Revision 和运维状态；管理端可额外展示 `release_note`，但模型上下文不得包含它。
