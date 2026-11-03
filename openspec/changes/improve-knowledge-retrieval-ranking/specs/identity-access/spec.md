## ADDED Requirements

### Requirement: 知识检索在途续期必须保持短期票据和原授权绑定
平台 SHALL 提供固定内部知识 Principal 续期入口 `/api/internal/knowledge/principal/refresh`，Knowledge 服务固定完整 scope SHALL 包含 `internal:knowledge:principal:refresh`，同时验证 Knowledge Service Principal 和尚未到期的 knowledge-mcp Business Principal。入口 MUST 重新核对 RUNNING Job、用户、Session、Publication、完整冻结 scope/authorization hash 和当前业务授权；新票据 TTL MUST 不超过 300 秒，除 jti/iat/nbf/exp 外声明必须与旧票据一致。不得接受请求覆盖 job、用户、Server 或 scope，也不得使用过期票据续期。入口不得成为 Agent 工具或浏览器接口。

#### Scenario: 在途知识请求跨越旧票据到期时间
- **WHEN** 360 秒以内的知识调用仍在执行且旧票据接近到期
- **THEN** Knowledge MCP 在到期前通过双身份入口有界续期，后续调用使用通过本地完整验证的新票据，检索截止不重置

#### Scenario: 续期期间授权或绑定变化
- **WHEN** Job 结束、用户或授权被撤销、scope/Publication/主体绑定变化或旧票据已过期
- **THEN** 平台拒绝续期，Knowledge MCP 终止原调用，不恢复过期票据、不重放模型推理

#### Scenario: 请求取消或结束
- **WHEN** 原请求取消、截止、失败或正常完成
- **THEN** 停止该请求的续期及其 I/O，回收线程并清除内存票据引用，不留下后台续期或影响其他并发请求

#### Scenario: 续期结果不可信
- **WHEN** 返回票据签名、TTL、audience、完整稳定声明或响应结构校验失败
- **THEN** 拒绝替换当前身份并使原调用失败关闭，错误和审计不回显票据或原始异常
