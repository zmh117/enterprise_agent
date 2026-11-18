## Why

现有 Webhook 同时固定 Agent、执行身份和投递，应用又重复配置这些信息，形成重复配置和发布版本冲突。用户需要通过渠道创建入口、由角色控制资源权限，再由应用统一选择 Agent 和钉钉接收人。

## What Changes

- **BREAKING**：Webhook 不再选择 Agent 或投递，通用 JSON 只接受固定 `id`、`message`，保留 Grafana 标准告警；删除自定义映射、模板、过滤和业务路由编辑。
- Webhook 直接关联业务角色，后台自动维护专用机器身份，无需人员配置；复用现有应用、工具、资源范围授权。
- Agent 入口展示启用的 Webhook；应用只能选择固定 Agent Publication 已允许且仍启用的入口，自动生成路由与机器身份。
- 应用统一配置钉钉私聊投递，选择启用机器人及同企业已绑定钉钉的启用人员，支持多选；空名单正常执行并保存结果，不发送。
- 删除“使用 Webhook 配置的接收人”，保留高级 HTTP 回调；限流、去重采用平台默认值。
- 在受理边界固定应用与 Agent 发布版本及结果路由，后续配置变化不能改写已受理事件与 Job。

## Capabilities

### New Capabilities

无，全部归入现有 canonical 领域。

### Modified Capabilities

- `channel-conversation`：Webhook 的简化输入、角色授权和应用路由冻结。
- `business-application`：Agent 允许的入口候选、应用管理的钉钉私聊与高级回调投递。
- `identity-access`：Webhook 页面直接选择业务角色，机器身份与收件人分离。
- `agent-model`：启用 Webhook 的入口分配与发布依赖。
- `execution-delivery`：应用固定结果路由、人员解析、空名单及逐收件人投递。

## Impact

涉及 Webhook 与应用 API、持久化迁移、渠道受理与 Dispatcher、角色委派、收件人目录及投递校验，和管理前端三个配置页面。当前实现使用 Webhook Publication 固定 Agent 与 Delivery，且应用 Webhook 入口不支持 `dingtalk_private`，必须同步修改运行链。保留既有非 Webhook 入口和上一轮跨项目 Agent 候选修复。真实模型调用与真实钉钉发送需与本地合同验证分开记录。
