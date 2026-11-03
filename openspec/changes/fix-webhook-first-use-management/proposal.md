## Why

当前 Web 新建 Webhook 强制复用已有入口 Connector，但没有入口的部署无法创建第一个 Webhook。后端已有草稿、校验、预览和发布能力，Web 页面却只有定义登记，没有后续管理入口，导致配置流程中断。

## What Changes

- 新建 Webhook 时原子创建独立的受管入站 Connector、服务账号和停用的定义，无须预置 Connector 或导入演示数据。
- 渠道卡片提供 Webhook 配置入口，复用现有后端完成认证引用、JSON 映射、路由、Agent 发布绑定、草稿校验、预览、发布及启停。
- 提供可选 Agent 发布和受管凭据目录，展示可操作的校验错误，不绕过发布与服务账号授权。
- 补充无现有入口、失败回滚、权限、秘密保护及浏览器配置流程的回归证据。

## Capabilities

### New Capabilities

无新增 canonical 领域。

### Modified Capabilities

- `channel-conversation`：明确首次创建的独立入口生命周期，以及从 Web 完成现有 Webhook 管理闭环的要求。

## Impact

涉及 managed_channel、webhook、Connector 类型目录和渠道前端。复用现有表和 Secret 中心，不新增独立配置框架，不修改既有凭据、钉钉连接或业务路由；无需数据库迁移。验收使用合成数据，公网调用、真实 Provider 和实际业务授权不由本修复自动启用。
