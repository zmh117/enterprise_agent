# 切换默认 Team 时重新验证

用户更换 ONES 默认 Team 时必须重新输入 ONES 邮箱和密码，由服务端创建新的短时单次 Verification Challenge，并从 ONES 当前返回的 Team 集合中选择默认 Team；不得直接使用历史 Team 集合。确认后原子刷新 User ID、显示名称、已验证 Team、默认 Team 和验证时间，不保存 Token。

默认 Team 是外部身份展示和未来 ONES 集成可以引用的身份事实，不注入现有 MCP Job，也不作为当前工具调用凭据。未来 ONES MCP 如需调用身份或凭据，必须通过独立变更重新设计。
