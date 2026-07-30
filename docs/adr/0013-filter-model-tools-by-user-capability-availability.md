# 按用户 Capability 可用状态过滤模型 Tool

每次构建模型 Tool 列表前，平台计算当前用户的 User Capability Availability；不可用的 Capability 不暴露给模型，但可以提供不含敏感信息的原因和中文操作提示。Handler 真正执行前必须再次检查身份、Team、凭据和授权，不能依赖会话或暴露阶段缓存，以防期间发生解绑、Token 失效或撤权。
