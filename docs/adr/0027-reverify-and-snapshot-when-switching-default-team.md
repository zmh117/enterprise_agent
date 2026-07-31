# 切换默认 Team 时重新验证并冻结 Job 主体快照

用户更换 ONES 默认 Team 时必须重新输入 ONES 邮箱和密码，由服务端创建新的短时单次 Verification Challenge，并从 ONES 当前返回的 Team 集合中选择默认 Team；不得直接使用历史 Team 集合。确认后原子刷新已验证 Team、默认 Team 和加密 Token。新默认 Team 只影响之后创建的 Agent Job；每个 Job 在创建时冻结当前外部 User ID 和默认 Team ID，已创建 Job 不因后续重绑或 Team 切换而改变执行主体或范围。Token 不进入该快照，仍按应用冻结的认证配置版本解析当前有效个人凭据；但执行前须按 ADR-0042 校验快照主体和 Team 仍有效。
