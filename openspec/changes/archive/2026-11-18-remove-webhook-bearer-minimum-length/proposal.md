## Why

用户明确要求取消 Webhook Bearer Token 的 32 字符最低长度限制。当前发布校验和运行时鉴权均拒绝短 Token，页面也显示该要求，需要同步调整。

## What Changes

- 允许非空且格式合法的短 Bearer Token，取消最低长度和熵要求。
- 发布、入口鉴权与渠道就绪使用同一格式校验，页面移除 32 字符提示。
- 保留凭据引用解析、唯一绑定、常量时间匹配及既有免鉴权模式。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `channel-conversation`：公共 Webhook 的 Bearer 认证不要求至少 32 个字符或熵阈值。

## Impact

影响 Webhook 验证器、鉴权器、管理端提示和回归测试。当前代码已采用执行用户与可选 Bearer；本次只调整 Token 长度规则，不引入数据库迁移、自动改绑或凭据轮换。
