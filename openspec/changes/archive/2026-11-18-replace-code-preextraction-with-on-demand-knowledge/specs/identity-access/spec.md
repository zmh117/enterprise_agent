## ADDED Requirements

### Requirement: SVN 内部结果读取必须使用控制面专属服务身份
内部 SVN 结果端点 SHALL 只接受平台签发的短期 Service Principal，固定 sub/azp 为 code-knowledge-control-plane、aud 为 code-svn-result、scope 为 internal:code-svn:result:read，沿用平台公开 JWKS 和不超过 300 秒 TTL。API 使用自身已持有的签名器生成固定角色 Token，不增加可指定角色的签发接口；Runtime、knowledge-mcp、knowledge-sync 不得获得签名私钥或该角色 bootstrap 凭据。服务身份不替代当前 Job、来源、发布、占用和执行代次核验，也不赋予 SVN 仓库写权限。

#### Scenario: 其他服务 Token 不能读取原文
- **WHEN** Runtime、普通 Knowledge、文件服务或业务 Principal 调用 SVN 内部结果端点
- **THEN** audience/role/scope 校验失败，不返回操作详情或原文

#### Scenario: API 固定角色调用
- **WHEN** 控制面已验证当前用户和 Job 来源权限，并签发固定短期服务 Token
- **THEN** 执行器仍按准入操作和有效占用核验；Token 到期、操作取消或代次变化时拒绝
