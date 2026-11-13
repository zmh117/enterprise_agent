## Why

当前源码问答把成功检索 query 的 hash 绑定到分析，但保存工具再次要求模型填写 question，改写措辞就会触发 CODE_QUESTION_MISMATCH。模型还可在没有保存分析结果时直接结束回答；现有收尾只保留问答记录，无法完成知识积累。

## What Changes

- Runtime 从本次成功的代码检索保留规范问题，并按成功的源码准入绑定 analysis；保存使用宿主绑定的问题，服务端继续核验 hash、版本、权限和证据。
- 已取得源码读取授权却未完成结果保存时，在原 Job 预算内最多追加一次收尾纠正，让同一个 Agent 调用保存工具；不另建任务，不延长预算。
- 用户已选择：补保存仍失败时保留业务回答；后台单独记录未尝试、失败、保存为部分/矛盾结果以及已保存的状态，不把聊天正文直接索引。
- 增加覆盖问题改写、未调用保存、保存失败、重放以及证据不足的回归验证。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `builtin-tool-resource`：保存问题必须来自宿主绑定的成功检索上下文，不依赖模型重复填写。
- `execution-delivery`：源码分析增加预算内一次保存收尾纠正，业务回答与保存结果分开表达。
- `platform-operations`：在已有分析记录中保存可排查的知识保存结果。

## Impact

影响 Python Runtime 的 Knowledge MCP bridge、源码占用状态、SDK Stop hook，以及控制面结果记录；继续使用现有代码知识表、索引任务与 Qdrant 管道。当前其他未提交源码读取/敏感阻断修改不属于本 change。既有已结束任务不补造证据或成功记录；真实模型与部署后的两问重跑单独验收。
