## MODIFIED Requirements

### Requirement: 模型连接测试必须使用真实受限Runtime并防止SSRF
系统 SHALL 提供模型连接测试动作，测试 MUST 使用保存后的模型连接和 active Secret，通过独立 TypeScript Runtime 的官方 Claude Agent SDK 路径执行无工具、单轮、短超时探测。Python API MUST 先执行 RBAC、HTTPS、Provider host allowlist、userinfo、fragment、重定向、回环、链路本地和私网目标校验；Runtime MUST 再按固定 revision/config hash 解析连接。响应 MUST 只包含 Provider Host、模型、Runtime/SDK 版本、耗时和安全结果，不得包含 Key、Secret ref、Prompt、模型响应正文或内部异常详情。

#### Scenario: 测试已保存DeepSeek连接
- **WHEN** Secret 管理员测试已保存、host 被允许且 revision/config hash 固定的 DeepSeek Anthropic-compatible 连接
- **THEN** Python 服务把受限 probe 委托给 TypeScript Runtime，Runtime 使用 active Key 完成无 Tool 探测并返回安全状态和耗时

#### Scenario: 测试未批准URL
- **WHEN** 管理员提交回环、私网、HTTP、带 userinfo 或 host 不在 allowlist 的 Base URL
- **THEN** Python 服务在调用 Runtime 前拒绝连接
- **AND** 审计只记录脱敏 host、actor、结果和 correlation ID

#### Scenario: 连接版本发生漂移
- **WHEN** Runtime 读取到的模型连接 revision 或 config hash 与 probe 请求不一致
- **THEN** Runtime 在调用 Provider 前失败关闭并返回稳定配置漂移错误
