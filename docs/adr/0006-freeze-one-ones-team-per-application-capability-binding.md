# 每个应用 Capability Binding 冻结一个 ONES Team

业务应用绑定 ONES API Capability 时必须选择一个 Team，并把该 Team 冻结到应用发布和 Job Execution Scope。运行时仅在该 Team 仍属于当前消息发送人的已验证 ONES Team 集合时执行；消息、Agent 参数和 Handler 输入不能提供或替换 `team_uuid`。第一版不自动跨 Team 聚合，以防提示词或动态参数扩大外部数据范围。
