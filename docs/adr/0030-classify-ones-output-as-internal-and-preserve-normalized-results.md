# ONES 输出标记为 INTERNAL 并正常保存规范化结果

API Capability Revision 声明数据分级，Capability Release 冻结该值；`ones.work_item.search` 第一版固定为 `INTERNAL`。`INTERNAL` 是访问和后续数据使用边界，不是发布状态或保留期限。通过 Output Schema 与大小限制的规范化 Tool Call 结果和 Agent 最终回复按现有 Job、会话模型正常保存，只能由具备对应业务应用、Job 和 Capability 权限的主体访问；原始 HTTP 响应仍永不落盘，日志和审计不得复制工作项正文。本变更不执行定时清理，`session_policy.retention_days` 继续明确为仅保存、未执行。未来记忆系统若摄取这些数据，必须继承用户、业务应用、Capability 和 `INTERNAL` 来源边界，记忆系统实现不属于本变更。
