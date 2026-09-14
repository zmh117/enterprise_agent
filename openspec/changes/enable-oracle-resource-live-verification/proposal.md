## Why

当前 Oracle 技术测试在执行连接前被默认关闭的开关永久拦截。API 镜像又不包含 Instant Client，即使简单打开开关，也无法完成现有规范要求的真实 Thick 验证。用户已同意接通真实验证，而不是绕过校验发布。

## What Changes

- 由 API 授权并委派当前 Oracle 草稿给 tool-mcp 验证；客户端仍只安装在 tool-mcp。
- 请求只包含签名且限时的资源、草稿、操作人标识；接收端重新校验权限并自行解析凭据。
- 区分客户端、网络、认证、服务标识、版本、字符集与只读权限失败；只有真实探针通过才允许发布。
- 保留草稿并发校验、现有本地高权限账号策略及其他 Provider 行为；不新增 Agent 工具。

## Capabilities

### New Capabilities

无新的独立领域。

### Modified Capabilities

- `builtin-tool-resource`: 补充管理端 Oracle 草稿跨服务真实验证、鉴权及安全失败要求。

## Impact

涉及平台资源验证服务、tool-mcp 私有 HTTP 入口、启动装配、部署环境配置及测试。无数据库迁移；无 Runtime 协议或 Agent 工具契约变更。另一环境的真实 Oracle 11.2.0.4 验收需在部署后单独执行，不能以 Mock 通过替代。
