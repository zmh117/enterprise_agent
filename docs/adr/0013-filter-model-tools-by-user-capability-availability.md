# 按用户 Capability 可用状态过滤模型 Tool

每次构建模型 Tool 列表前，平台先确认 DingTalk Application Access，再只考虑 Application Capability Allowlist 中的能力，并计算当前用户的 User Capability Availability；不在 Agent 上限、不在应用子集或当前用户不可用的 Capability 均不暴露给模型，但可以提供不含敏感信息的原因和中文操作提示。Handler 真正执行前必须再次检查应用访问、Agent 上限、应用子集、Release 状态、身份、Team 和凭据，不能依赖会话或暴露阶段缓存。
