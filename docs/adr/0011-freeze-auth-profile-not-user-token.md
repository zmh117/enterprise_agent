# 应用冻结认证协议，不冻结用户 Token

Application Publication 固化 Authentication Profile Revision，但不保存具体用户 Token。每次调用根据当前内部用户和被冻结的认证协议版本解析最新有效 External API Credential；用户重新验证只原子轮换加密 Token，不要求重新发布应用。登录地址、Token 提取或认证 Header 规则变化必须发布新的认证协议版本，旧凭据不得跨不兼容协议复用。
