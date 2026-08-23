# Job 主体快照不绕过实时撤权

> 状态：Job 冻结内部主体且实时撤权仍有效；“ONES 不参与现有 MCP”已失效。当前 Job
> 不冻结 ONES Token，但 `ones-mcp` 在调用时通过短时 Principal JWT 解析并复核当前
> ONES 身份、默认 Team 与加密 ACTIVE credential。

Agent Job 创建时冻结当前内部 `app_user_id`、Application/Agent Publication 和授权摘要，后续不得把执行主体切换为其他用户。每次 MCP 工具调用仍须按当前用户状态、Role scope、资源状态和工具 Manifest 实时校验；用户、角色或资源被停用后，旧 Job 失败关闭。

当前 Job 不冻结 ONES User ID、默认 Team 或个人 Token。ONES 身份属于独立身份事实，不参与现有 MCP 工具执行；未来 ONES MCP 的主体与凭据模型必须通过独立决策引入。
