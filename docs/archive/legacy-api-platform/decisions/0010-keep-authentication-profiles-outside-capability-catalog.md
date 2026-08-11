# 外部登录属于 Connection Authentication Profile

外部登录、Token 提取、主体与范围提取以及运行时认证 Header 注入由版本化 API Connection Authentication Profile 定义。身份与凭据服务可以调用登录接口，但登录不得发布为 API Capability、Capability Handler 或 Agent Tool。业务 Handler 只声明凭据主体策略，不能读取 Token、修改认证 Header 或覆盖外部主体。
