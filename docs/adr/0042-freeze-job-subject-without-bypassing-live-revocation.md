# Job 主体快照不绕过实时撤权

Agent Job 创建时冻结 ONES User ID 和默认 Team ID，后续调用不得切换到新绑定、新账号或新默认 Team。每次外部调用前仍须确认快照 User ID 等于当前启用绑定主体、快照 Team 仍在最新验证 Team 集合中，并解析当前有效的个人 Token。用户解绑、换绑账号、失去快照 Team 或凭据失效时，旧 Job 失败关闭；只轮换 Token 且快照主体与 Team 仍有效时，旧 Job 可以使用新 Token 继续。主体快照用于防止执行漂移，不构成对撤销身份、范围或凭据的豁免。
