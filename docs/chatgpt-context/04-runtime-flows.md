# 04 Runtime 流程

## 消息到 Job

1. 入口事件幂等持久化。
2. 路由到已激活 Application Publication。
3. 解析当前发送人的统一身份和角色。
4. 创建 Job，冻结 Agent/Application Publication、MCP Tool 子集与授权摘要。
5. Worker 投递到 Publication 指定的 Runtime。

## Tool Call

1. Runtime 只能看到 Job 快照中的 MCP Tool。
2. Agent 根据本轮用户输入与 Skill 选择是否调用工具及目标参数。
3. `tool-mcp` 复核 Job、tool identifier/schema hash、当前角色、应用和数据范围。
4. 根据 environment/base/workshop/placement 唯一解析已发布 Resource Revision。
5. 短暂解析 Secret Ref，执行有界只读适配器并保存脱敏摘要。

普通问候不触发资源解析。目标零命中、多命中、撤权、schema drift 或 Job 终态均失败关闭。

## 交付

Runtime terminal -> Job terminal -> Delivery Outbox -> connector -> 原会话/配置目标。交付失败独立重试，不回滚已完成 Job。
