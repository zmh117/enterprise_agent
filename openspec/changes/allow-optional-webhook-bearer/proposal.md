## Why

用户已明确要求 Webhook 凭据可选：留空也能保存、发布和调用。目前 API 必填校验、发布校验与接收鉴权均要求 Bearer，且配置页缺少可直接参考的 HTTP 示例。

## What Changes

- 凭据留空采用明确的免鉴权模式；填写凭据时继续严格校验 Bearer，错误或不可解析凭据不得降级。
- 鉴权模式随 Publication 冻结，修改草稿不影响现有入口。
- 配置页展示当前 public ID 对应的 curl 示例，按凭据是否填写显示 Authorization 头，并解释事件 ID、发布激活和 HTTP 202。
- 保留角色、来源、应用路由、限流、去重和报文边界校验。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `channel-conversation`：受管 Webhook 支持可选 Bearer，并提供匹配配置的 HTTP 调用示例。

## Impact

涉及 Webhook 管理请求模型、配置规范化、发布校验、接收鉴权和前端配置页及回归测试。使用现有 JSON 配置，不新增数据库表或依赖；已有带 Bearer 的发布保持原行为。
