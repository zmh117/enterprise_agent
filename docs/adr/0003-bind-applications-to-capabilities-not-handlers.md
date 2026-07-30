# 业务应用绑定 API Capability，不直接绑定 Handler

业务应用、Agent 和角色授权只引用稳定的业务层 API Capability；每个已发布 Capability 版本再解析到确定的 Capability Handler 和 API Connection 版本。Handler、请求路径、报文映射和连接信息保持为平台治理细节。这样业务权限与外部接口实现解耦，同时允许应用发布快照冻结实际执行版本。
