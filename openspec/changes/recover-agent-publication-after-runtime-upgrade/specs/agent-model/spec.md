## ADDED Requirements

### Requirement: Agent Runtime 协议升级后必须可由管理面恢复
系统 SHALL 将 Agent Publication 的管理读取兼容性与新执行准入兼容性分离。结构、哈希、Runtime kind 和快照对应的冻结工具事实完整，但 Runtime 协议或 MCP 工具执行策略不再兼容当前平台的 Publication MUST 在 Agent 管理详情与发布历史中以历史只读状态返回，不得使整个管理请求失败；新发布、回滚和新 Job 创建 MUST 继续只接受综合执行兼容状态为当前的 Publication，已经固定 Publication 与协议的既有 Job MUST NOT 被改写。

#### Scenario: 管理员查看包含旧协议的发布历史
- **WHEN** Agent 发布历史中同时存在当前协议 Publication 和一个或多个格式合法的旧协议 Publication
- **THEN** 管理 API 返回完整有序列表，并分别标记 `current` 与 `historical_read_only`
- **AND** Web 展示旧协议版本的原始 revision、hash、runtime 和只读状态，不显示可用回滚动作

#### Scenario: 管理员查看工具策略已变化的发布版本
- **WHEN** Publication 快照与冻结工具行一致，但其工具已退役或执行策略不再匹配当前代码 Manifest
- **THEN** 管理 API 返回该 Publication 并标记 `historical_read_only` 和 `mcp_tool_policy` 原因
- **AND** Web 显示“工具策略已变化、只读”，不允许回滚或用于新 Job

#### Scenario: 管理员为历史只读当前版本创建恢复草稿
- **WHEN** 当前 Agent Publication 使用格式合法的旧协议或历史工具策略，且管理员具备 Agent 编辑与发布权限
- **THEN** Web 允许管理员从当前可编辑配置创建新的恢复草稿
- **AND** 恢复草稿仍须完成正常校验和显式发布，发布后生成使用当前协议的新不可变 Publication

#### Scenario: 新执行或回滚选择旧协议版本
- **WHEN** 新 Job 创建或 Agent 回滚选择历史协议 Publication
- **THEN** 系统以稳定错误失败关闭，且不切换当前执行版本、不创建 Job

#### Scenario: 已有 Job 固定旧协议版本
- **WHEN** Runtime 协议升级前创建的 Job 已固定旧协议 Publication 与协议版本
- **THEN** Worker 和 retry 继续使用该 Job 的固定事实完成或失败
- **AND** 系统不把该 Job 静默改写到新 Publication 或新协议

#### Scenario: 恢复发布后业务应用保持固定版本
- **WHEN** 管理员完成 Agent 恢复草稿的校验和发布
- **THEN** 系统只更新 Agent Definition 的当前 Publication 指针
- **AND** 已激活业务应用继续使用其固定的 Agent Publication，直到管理员显式更新并重新发布该应用

#### Scenario: 历史协议事实格式损坏
- **WHEN** Publication 的协议事实为空、不是数组、包含重复项或包含非版本字符串
- **THEN** 系统继续判定发布事实完整性失败
- **AND** 不把损坏事实标记为可恢复的历史只读协议

#### Scenario: 冻结工具事实与快照不一致
- **WHEN** Publication 快照中的工具标识、server 或 schema hash 与其冻结工具行不一致
- **THEN** 系统继续判定发布事实完整性失败
- **AND** 不把被篡改或不完整的冻结事实降级为可恢复的历史工具策略
