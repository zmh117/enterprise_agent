# 业务应用绑定 API Capability，不直接绑定 Handler

Agent Publication 只引用稳定业务层 API Capability，并冻结其 Agent Capability Envelope；Application Publication 只能从所选 Agent 的上限中选择 Capability Release 子集。平台不再建立逐用户或逐角色 Capability Code 授权，钉钉用户通过业务应用访问权获得该应用子集的调用资格。每个已发布 Capability Release 再解析到确定的 Capability Handler 和 API Connection 版本，Handler、请求路径、报文映射和连接信息保持为平台治理细节。
