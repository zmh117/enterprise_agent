## Why

Agent Runtime 协议或 MCP 工具执行策略升级后，发布历史管理接口会把与当前平台不兼容的不可变 Publication 判为错误，导致 Web 的“发布历史”整体不可用。管理员因此无法查看旧事实、创建当前事实草稿并重新发布，系统失去升级后的自助恢复入口。

## What Changes

- 将 Agent Publication 的管理读取与新执行准入校验分离：结构、哈希和冻结工具事实仍严格校验，合法但非当前的 Runtime 协议或 MCP 工具策略统一标记为历史只读，不再使整个发布历史请求失败。
- Agent 详情与发布历史返回协议、工具策略和综合执行兼容状态；Web 显示具体不兼容原因，并禁止把历史只读 Publication 回滚为当前执行版本。
- 当当前 Publication 使用历史协议或历史工具策略且最新草稿已经发布时，Web 提供明确的“创建当前 Runtime 恢复草稿”入口；恢复仍沿用保存草稿、校验、发布三步流程，并生成新的不可变 Publication。
- 新发布、回滚和新 Job 创建继续严格要求当前协议与完整发布事实；已固定旧协议的既有 Job 仍按其不可变快照完成或失败，不改写旧快照，不自动切换任何业务应用固定的 Agent Publication。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-model`：补充 Runtime 协议升级后的管理面只读降级、显式恢复草稿和执行面失败关闭要求。

## Impact

- 后端：Agent 配置服务的 Publication 管理投影与严格执行校验边界、Agent 管理 API 响应。
- 前端：Agent 详情和发布历史的兼容状态、恢复草稿提示与动作。
- 验证：后端服务/API 回归、前端交互测试、OpenSpec 严格校验及本地 Web 部署验收。
- 无数据库迁移、无 Secret 处理变化、无业务应用自动切换。
