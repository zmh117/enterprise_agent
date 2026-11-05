## ADDED Requirements

### Requirement: Prompt版本差异必须在新执行准入前拒绝
Runtime 版本与就绪元数据 MUST 返回当前代码的 Prompt 模板版本。被动就绪探针 MUST 比较声明与期望版本，缺失、非法或两个接口不一致 SHALL 视为不可接受新执行。池选择 PREPARED 请求的节点时 MUST 使用该请求冻结版本，不得静默改写请求或 digest。Runtime MUST 在占槽、admit、模型或 MCP 工作之前拒绝不匹配的新执行，并以稳定的 `runtime_prompt_version_mismatch` 返回安全的统一部署提示。

#### Scenario: 混合版本节点
- **WHEN** 节点构建标识相同，但 Prompt 模板版本不同
- **THEN** 只有与新请求冻结模板版本一致的节点可以接收新执行，不匹配节点在被动就绪结果中可识别

#### Scenario: 旧节点没有模板声明
- **WHEN** `/version` 或 `/ready` 没有合法模板版本，或两者声明不同
- **THEN** 被动探针拒绝新执行准入，不调用模型或工具，也不回显非法元数据原文

#### Scenario: 旧Worker直接发来不匹配的新请求
- **WHEN** 身份认证通过但请求模板版本与 Runtime 当前常量不同，且请求没有已有运行或终态可恢复
- **THEN** Runtime 在占槽和执行之前返回不可重试的版本不匹配错误，持久请求仍保持原 digest

#### Scenario: 升级后恢复原执行结果
- **WHEN** 请求已有运行实例或持久终态，当前部署 Prompt 版本与原请求不同
- **THEN** 恢复不因新模板版本被拒绝，既有节点/构建身份约束和事件校验保持，原事件不被改写且模型不重新运行
