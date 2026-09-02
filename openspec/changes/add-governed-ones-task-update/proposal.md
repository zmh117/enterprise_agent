## Why

当前 ONES MCP 只允许受治理的只读查询，Agent 无法在用户明确确认后更新现有缺陷 Bug。仓库已经具备钉钉 Action Intent、确认卡片 Outbox 和独立 mutation worker，但其持久化上下文与执行分发仍绑定钉钉 Provider，需要在不扩大为通用 ONES 写接口的前提下复用并泛化这条确认执行链。

## What Changes

- 新增代码固定的 `ones_update_task` mutation Tool，仅支持更新一个已存在的缺陷 Bug；工单、需求及其它 Task 类型在 Provider 写调用前拒绝。
- Tool 采用 Patch 语义：`uuid` 必填，其余字段仅在明确提供时更新；区分未提供、清空值和非法 `null`。
- 以代码白名单和版本化字段目录开放接口文档中全部已验证的缺陷可写字段，但排除状态；将语义参数和已解析的选项/动态实体 UUID 编译为 ONES `update3` 请求，不向模型开放任意 REST、GraphQL 或原始 `field_values` 写入。
- 仅允许钉钉私聊或群聊来源 Job 提出更新，并通过同一来源 Connector 向原操作人私聊投放逐次确认卡片；Web 只承载 ONES 身份绑定，不提供 mutation 确认入口。
- 复用现有钉钉 mutation 卡片模板、按钮和状态，但每个 Action Intent 使用独立卡片实例；卡片以中文完整展示缺陷及全部实际变化的“原值 → 新值”，超过卡片容量时拒绝准备并要求拆分。
- 在准备意图、确认回调和 Provider 执行前分别复核主体、Job Tool 快照、业务授权、ONES 身份、Team、Credential、Task 可见性及编辑权限；身份解绑、换绑、权限撤销或版本漂移时 fail closed。
- 复用现有 Action Intent、Card Outbox、claim/lease、恢复和审计框架，将 `enterprise_agent-external-action-worker` 扩展为按 Provider 路由的执行器，并为 ONES 保存独立且无 Secret 的执行上下文。
- 明确排除创建 Task、非缺陷 Task、批量更新、任意字段写入、状态修改/流转和非钉钉渠道确认。

## Capabilities

### New Capabilities

- `governed-ones-task-update`: 定义 ONES 缺陷 Bug 的受治理 Patch、字段白名单、差异确认、并发保护、执行结果和安全失败行为。

### Modified Capabilities

- `governed-api-capability`: 将 ONES MCP 从仅有代码固定只读 Tool 扩展为额外发布一个受确认保护的代码固定 mutation Tool，同时保留任意接口禁止规则。
- `identity-access`: 增加 ONES mutation 在确认和执行阶段对原始 ONES 身份、Team 与个人 Credential 的重新解析及失效阻断要求。

## Impact

- ONES MCP Manifest、Tool schema、参数规范化、字段目录、Provider 客户端和操作审计。
- `external_action_intent` 的 Provider 中立上下文、Repository/Service、确认卡片渲染和回调校验。
- `enterprise_agent-external-action-worker` 的 Provider 路由、ONES 执行适配器、授权复核、恢复语义与部署依赖。
- Agent/Application Publication、Job Tool Snapshot、角色 Tool 授权和管理界面的 mutation Tool 展示。
- 数据库 migration、容器裁剪/导入边界、回归测试、Compose 校验及真实 ONES/钉钉验收。
